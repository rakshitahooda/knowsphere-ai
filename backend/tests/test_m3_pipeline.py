"""M3 tests: the ingestion pipeline — happy path, dedupe, safety, rollback.

Uses FakeEmbedder + real ChromaDB + real SQLite in per-test directories, so
the full flow runs offline with production-faithful behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.embeddings.fake import FakeEmbedder
from app.core.retrieval.vector_store import ChromaVectorStore
from app.db.repository import DocumentNotFoundError, DocumentRepository
from app.ingestion.chunker import ChunkerConfig
from app.ingestion.parse import (
    DocumentParseError,
    EmptyDocumentError,
    UnsupportedDocumentError,
)
from app.ingestion.pipeline import (
    DEFAULT_MAX_UPLOAD_BYTES,
    DuplicateDocumentError,
    FileTooLargeError,
    DocumentIngestor,
    _sanitize_basename,
)

# --------------------------------------------------------------------- #
# fixtures / helpers                                                     #
# --------------------------------------------------------------------- #


@pytest.fixture()
def workspace(tmp_path: Path) -> dict[str, Path]:
    return {
        "uploads": tmp_path / "uploads",
        "chroma": tmp_path / "chroma",
        "db": tmp_path / "docs.db",
    }


def make_ingestor(workspace: dict[str, Path], **overrides: object) -> DocumentIngestor:
    kwargs: dict[str, object] = {
        "repository": DocumentRepository(workspace["db"]),
        "vector_store": ChromaVectorStore(workspace["chroma"]),
        "embedder": FakeEmbedder(),
        "uploads_dir": workspace["uploads"],
        "max_upload_bytes": DEFAULT_MAX_UPLOAD_BYTES,
        "chunker_config": ChunkerConfig(max_chars=200, overlap_chars=50, min_chars=40),
    }
    kwargs.update(overrides)
    return DocumentIngestor(**kwargs)  # type: ignore[arg-type]


LONG_TEXT = " ".join(
    "The quick brown fox jumps over the lazy dog while the sun rises eastward".split()
    * 12
)


# --------------------------------------------------------------------- #
# happy path + metadata                                                  #
# --------------------------------------------------------------------- #


def test_ingest_txt_end_to_end(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)

    meta = ingestor.ingest(original_name="notes.txt", data=LONG_TEXT.encode())

    assert meta.status == "ready"
    assert meta.original_name == "notes.txt"
    assert meta.size_bytes == len(LONG_TEXT.encode())
    assert meta.num_chunks >= 2  # text is long enough to chunk
    assert meta.content_type == ".txt"  # fallback when content_type omitted
    # a stored file exists with a uuid-prefixed safe name
    stored = workspace["uploads"] / meta.stored_name
    assert stored.is_file()
    assert meta.stored_name.startswith(tuple("0123456789abcdef"))
    # metadata is listed
    assert [d.id for d in ingestor.list_documents()] == [meta.id]


def test_small_document_single_chunk(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)
    meta = ingestor.ingest(original_name="tiny.md", data=b"# just a tiny note")

    assert meta.num_chunks == 1


def test_content_type_recorded_from_upload(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)
    meta = ingestor.ingest(
        original_name="notes.md", data=b"# heading", content_type="text/markdown"
    )
    assert meta.content_type == "text/markdown"


def test_custom_chunker_config_in_effect(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(
        workspace, chunker_config=ChunkerConfig(max_chars=100, overlap_chars=20, min_chars=30)
    )
    meta = ingestor.ingest(original_name="big.txt", data=LONG_TEXT.encode())

    tiny_ingestor = make_ingestor(
        workspace, chunker_config=ChunkerConfig(max_chars=800, overlap_chars=50, min_chars=100)
    )
    with pytest.raises(DuplicateDocumentError):
        tiny_ingestor.ingest(original_name="again.txt", data=LONG_TEXT.encode())
    assert meta.num_chunks > 1


# --------------------------------------------------------------------- #
# duplicate handling                                                     #
# --------------------------------------------------------------------- #


def test_identical_bytes_rejected_even_renamed(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)
    ingestor.ingest(original_name="first.txt", data=b"some unique contents")

    with pytest.raises(DuplicateDocumentError, match="first.txt"):
        ingestor.ingest(original_name="second.txt", data=b"some unique contents")


def test_same_name_different_content_is_allowed(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)
    ingestor.ingest(original_name="report.txt", data=b"quarter one figures")
    meta2 = ingestor.ingest(original_name="report.txt", data=b"quarter two figures")

    assert len(ingestor.list_documents()) == 2


def test_reupload_after_delete_is_allowed(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)
    meta = ingestor.ingest(original_name="cycle.txt", data=b"delete then re-upload me")
    ingestor.delete_document(meta.id)

    again = ingestor.ingest(original_name="cycle.txt", data=b"delete then re-upload me")
    assert again.num_chunks == meta.num_chunks


# --------------------------------------------------------------------- #
# validation / graceful failure                                          #
# --------------------------------------------------------------------- #


def test_zero_byte_upload_rejected(workspace: dict[str, Path]) -> None:
    with pytest.raises(EmptyDocumentError):
        make_ingestor(workspace).ingest(original_name="empty.txt", data=b"")


def test_oversized_upload_rejected_before_disk_write(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace, max_upload_bytes=10)

    with pytest.raises(FileTooLargeError, match="limit"):
        ingestor.ingest(original_name="big.txt", data=b"x" * 11)
    assert list(workspace["uploads"].iterdir()) == []  # nothing written


def test_unsupported_type_rejected(workspace: dict[str, Path]) -> None:
    with pytest.raises(UnsupportedDocumentError, match="\\.exe"):
        make_ingestor(workspace).ingest(original_name="virus.exe", data=b"MZ")


def test_no_filename_rejected(workspace: dict[str, Path]) -> None:
    with pytest.raises(UnsupportedDocumentError, match="filename"):
        make_ingestor(workspace).ingest(original_name="", data=b"data")


def test_corrupted_pdf_rolls_back_all_state(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)

    with pytest.raises(DocumentParseError):
        ingestor.ingest(original_name="broken.pdf", data=b"%PDF-1.4 garbage here")

    # rollback: no files, no DB rows, no vectors
    assert list(workspace["uploads"].iterdir()) == []
    assert ingestor.list_documents() == []
    assert ingestor._vector_store.chunk_count == 0


# --------------------------------------------------------------------- #
# path traversal / safe filenames                                        #
# --------------------------------------------------------------------- #


def test_traversal_tricks_are_neutralized(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)
    payloads = [
        "..\\..\\..\\windows\\evil.txt",
        "../../../../etc/passwd.txt",
        "con:evil:.txt",
    ]

    ids = []
    for name in payloads:
        meta = ingestor.ingest(original_name=name, data=f"payload {name}".encode())
        ids.append(meta.id)
        stored = workspace["uploads"] / meta.stored_name
        # the resolved parent must be exactly the uploads dir
        assert stored.parent.resolve() == workspace["uploads"].resolve()
        assert "\\" not in meta.stored_name and "/" not in meta.stored_name
        assert meta.stored_name.split("_", 1)[1].endswith(".txt")

    assert len(set(ids)) == 3  # unique contents → unique documents


def test_sanitize_basename_rules() -> None:
    assert _sanitize_basename("report FINAL (v2).txt") == "report_FINAL_v2_.txt"
    assert _sanitize_basename("..\\.hidden.md") == "hidden.md"
    assert _sanitize_basename("no-extension") == "no-extension"
    long = _sanitize_basename("x" * 200 + ".txt")
    assert len(long) <= 64


# --------------------------------------------------------------------- #
# deletion lifecycle                                                     #
# --------------------------------------------------------------------- #


def test_delete_removes_db_vectors_and_file(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)
    meta = ingestor.ingest(original_name="doomed.txt", data=LONG_TEXT.encode())

    ingestor.delete_document(meta.id)

    assert ingestor.list_documents() == []
    assert ingestor._vector_store.chunk_count == 0
    assert not (workspace["uploads"] / meta.stored_name).exists()


def test_delete_unknown_document_raises(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)
    with pytest.raises(DocumentNotFoundError):
        ingestor.delete_document("no-such-id")


def test_get_document_metadata_roundtrip(workspace: dict[str, Path]) -> None:
    ingestor = make_ingestor(workspace)
    meta = ingestor.ingest(original_name="round.txt", data=b"roundtrip body")

    fetched = ingestor.get_document(meta.id)
    assert fetched == meta
    with pytest.raises(DocumentNotFoundError):
        ingestor.get_document("missing-id")
