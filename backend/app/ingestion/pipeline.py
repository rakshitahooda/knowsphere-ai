"""Ingestion pipeline — the single choke point for getting a document into
the searchable store (and cleanly out of it).

Safety properties (requirements 8/9):
- content hash (sha256) dedupe: identical bytes are rejected even if renamed
- safe stored filenames: uuid prefix + sanitized basename; directory
  components (including traversal like ".." and "\") are stripped by
  ``Path(...).name`` AND the character allowlist, so a stored file can never
  land outside ``uploads_dir``
- each parse/chunk/embed/index step is wrapped: on failure, partially
  written state (uploaded file, vector entries) is rolled back

Memory (16 GB target): uploads <= 20 MB (the API reads the capped upload
fully into memory), embedding runs in small batches (32).
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from pathlib import Path

from app.core.embeddings.base import Embedder
from app.core.retrieval.vector_store import ChromaVectorStore
from app.db.repository import (
    DocumentMeta,
    DocumentNotFoundError,
    DocumentRepository,
    utc_now_iso,
)
from app.ingestion.chunker import ChunkerConfig, chunk_sections
from app.ingestion.parse import (
    EmptyDocumentError,
    IngestionError,
    SUPPORTED_SUFFIXES,
    UnsupportedDocumentError,
    parse_document,
)

DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
_EMBED_BATCH = 32
_UNLINK_ATTEMPTS = 4  # Windows can transiently lock fresh files (AV scans)
_UNLINK_DELAY_S = 0.05


class FileTooLargeError(IngestionError):
    pass


class DuplicateDocumentError(IngestionError):
    pass


def _unlink_with_retries(path: Path) -> None:
    """unlink with short retries for Windows' transient file locks."""
    last_error: OSError | None = None
    for attempt in range(_UNLINK_ATTEMPTS):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError as error:  # PermissionError ⊂ OSError
            last_error = error
            if attempt < _UNLINK_ATTEMPTS - 1:
                time.sleep(_UNLINK_DELAY_S)
    raise last_error if last_error is not None else PermissionError(f"cannot unlink {path}")  # pragma: no cover


def _sanitize_basename(original_name: str) -> str:
    """Reduce a user-supplied filename to one safe component.

    ``Path(...).name`` drops directory parts; the regex allowlist keeps only
    ``[A-Za-z0-9._-]`` (backslashes, colons, '../' runs become underscores).
    A uuid hex prefix makes the result collision-proof on disk.
    """
    base = Path(original_name).name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", base).lstrip(".") or "upload"
    return sanitized[:64]


class DocumentIngestor:
    """Coordinates repository, vector store, embedder and parsers."""

    def __init__(
        self,
        *,
        repository: DocumentRepository,
        vector_store: ChromaVectorStore,
        embedder: Embedder,
        uploads_dir: Path,
        max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
        chunker_config: ChunkerConfig | None = None,
        embed_batch_size: int = _EMBED_BATCH,
    ) -> None:
        self._repository = repository
        self._vector_store = vector_store
        self._embedder = embedder
        self._uploads_dir = Path(uploads_dir)
        self._max_upload_bytes = max_upload_bytes
        self._chunker_config = chunker_config or ChunkerConfig()
        self._embed_batch_size = max(1, embed_batch_size)
        self._uploads_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # ingest                                                              #
    # ------------------------------------------------------------------ #

    def ingest(
        self,
        *,
        original_name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> DocumentMeta:
        """Take raw upload bytes to a fully indexed document. Raises the
        structured IngestionError taxonomy; the API maps grades to statuses."""
        if not original_name or not original_name.strip():
            raise UnsupportedDocumentError("upload has no filename")
        original_name = original_name.strip()

        if len(data) == 0:
            raise EmptyDocumentError(f"{original_name!r} is empty (0 bytes)")
        if len(data) > self._max_upload_bytes:
            limit_mib = self._max_upload_bytes / (1024 * 1024)
            raise FileTooLargeError(
                f"{original_name!r} is {len(data) / (1024 * 1024):.1f} MiB; "
                f"limit is {limit_mib:.0f} MiB"
            )

        suffix = Path(original_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
            raise UnsupportedDocumentError(
                f"unsupported document type {suffix!r} (supported: {supported})"
            )

        # Dedupe by CONTENT hash — renaming cannot bypass it.
        sha256 = hashlib.sha256(data).hexdigest()
        existing = self._repository.get_by_sha256(sha256)
        if existing is not None:
            raise DuplicateDocumentError(
                f"{original_name!r} contains identical content to an already "
                f"indexed document {existing.original_name!r}"
            )

        stored_name = f"{uuid.uuid4().hex}_{_sanitize_basename(original_name)}"
        stored_path = self._uploads_dir / stored_name

        document_id = uuid.uuid4().hex
        file_written = False
        vectors_stored = False
        try:
            stored_path.write_bytes(data)
            file_written = True

            # Parse from the in-memory bytes (never a disk handle — see
            # parse.py docstring) so failures cannot lock the stored file.
            sections = parse_document(data, original_name)
            chunks = chunk_sections(sections, self._chunker_config)
            if not chunks:  # defensive: parser guarantees >=1 section
                raise EmptyDocumentError(f"{original_name!r} produced no chunks")

            vectors = self._embed_chunk_texts([chunk.text for chunk in chunks])
            self._vector_store.add_chunks(document_id, chunks, vectors)
            vectors_stored = True

            meta = DocumentMeta(
                id=document_id,
                original_name=original_name,
                stored_name=stored_name,
                content_type=content_type or suffix,
                size_bytes=len(data),
                num_chunks=len(chunks),
                status="ready",
                created_at=utc_now_iso(),
            )
            self._repository.add(meta, sha256)
            return meta
        except IngestionError:
            self._rollback(document_id, stored_path, file_written, vectors_stored)
            raise
        except Exception:
            # Unexpected failure (disk full, SQLite error, chroma error, ...):
            # never leave partial state behind.
            self._rollback(document_id, stored_path, file_written, vectors_stored)
            raise

    # ------------------------------------------------------------------ #
    # query + lifecycle                                                   #
    # ------------------------------------------------------------------ #
    def list_documents(self) -> list[DocumentMeta]:
        return self._repository.list()

    def get_document(self, document_id: str) -> DocumentMeta:
        try:
            return self._repository.get(document_id)
        except DocumentNotFoundError as exc:
            raise DocumentNotFoundError(document_id) from exc

    def delete_document(self, document_id: str) -> None:
        """Remove DB row, vector entries and the stored file.

        The unlink is best-effort with retries: on Windows a freshly written
        file can be transiently locked (e.g. antivirus scanning) — a locked
        file must not block the logical deletion."""
        meta = self.get_document(document_id)
        self._vector_store.delete_document(document_id)
        self._repository.delete(document_id)
        stored_file = self._uploads_dir / meta.stored_name
        try:
            _unlink_with_retries(stored_file)
        except OSError:  # pragma: no cover - persistent lock
            # logical deletion stays authoritative; file cleanup can be
            # retried by a maintenance pass later
            pass

    # ------------------------------------------------------------------ #
    # internals                                                           #
    # ------------------------------------------------------------------ #

    def _embed_chunk_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed in bounded batches (16 GB-friendly)."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._embed_batch_size):
            batch = texts[start : start + self._embed_batch_size]
            vectors.extend(self._embedder.embed_texts(batch))
        return vectors

    def _rollback(
        self,
        document_id: str,
        stored_path: Path,
        file_written: bool,
        vectors_stored: bool,
    ) -> None:
        """Best-effort cleanup after any ingest failure.

        Vector entries are deleted whenever they were written (the store
        knows the document id even though no DB row was created yet); the
        uploaded file is removed when it exists. Rollback failures are
        swallowed — cleanup must never mask the original error.
        """
        if vectors_stored:
            try:
                self._vector_store.delete_document(document_id)
            except Exception:  # noqa: BLE001 — see docstring
                pass
        if file_written:
            try:
                _unlink_with_retries(stored_path)
            except OSError:  # pragma: no cover — locked file on Windows
                pass

