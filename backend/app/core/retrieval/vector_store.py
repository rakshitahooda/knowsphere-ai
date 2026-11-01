"""ChromaDB persistent vector store — the only module that knows Chroma.

Wraps a single collection with a fixed cosine-similarity space. Everything
comes in through our own types (``Chunk``) and the ``Embedder`` protocol's
vectors, so swapping the store later (pgvector, managed Chroma, ...) touches
only this file.

Persistence: ``chromadb.PersistentClient`` with a fixed path → data survives
application restarts (requirement 15). Telemetry is disabled.

Batching: writes are chunked into groups of 64 — plenty fast, tiny memory
footprint (16 GB RAM target).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.ingestion.chunker import Chunk

COLLECTION_NAME = "knowsphere_docs"
_WRITE_BATCH = 64
_PAGE_SENTINEL = -1  # Chroma metadata must be scalar; page=None → -1


class VectorStoreError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A chunk pulled back by similarity search (with provenance)."""

    document_id: str
    text: str
    page: int | None
    section: int
    chunk_index: int  # ordinal within the source document
    distance: float  # cosine distance: 0 = identical, 2 = opposite


class ChromaVectorStore:
    def __init__(self, persist_dir: Path, collection_name: str = COLLECTION_NAME) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------ #
    # properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def chunk_count(self) -> int:
        return self._collection.count()

    # ------------------------------------------------------------------ #
    # write operations                                                    #
    # ------------------------------------------------------------------ #

    def add_chunks(
        self,
        document_id: str,
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]],
    ) -> int:
        """Index a document's chunks; deterministic ids make re-ingestion of
        the SAME document id idempotent (overwrites in place). Returns count."""
        if len(chunks) != len(vectors):
            raise VectorStoreError(
                f"chunk/vector length mismatch: {len(chunks)} vs {len(vectors)}"
            )
        if not chunks:
            return 0

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        embeddings: list[list[float]] = []

        for chunk, vector in zip(chunks, vectors, strict=True):
            if len(vector) == 0:
                raise VectorStoreError("empty embedding vector")
            ids.append(f"{document_id}:{chunk.index}")
            documents.append(chunk.text)
            metadatas.append(
                {
                    "doc_id": document_id,
                    "page": _PAGE_SENTINEL if chunk.page is None else chunk.page,
                    "section": chunk.section,
                    "chunk_index": chunk.index,
                }
            )
            embeddings.append([float(component) for component in vector])

        for start in range(0, len(ids), _WRITE_BATCH):
            end = start + _WRITE_BATCH
            self._collection.add(
                ids=ids[start:end],
                documents=documents[start:end],
                embeddings=embeddings[start:end],
                metadatas=metadatas[start:end],
            )
        return len(ids)

    def delete_document(self, document_id: str) -> int:
        """Remove every vector belonging to *document_id*. Returns deleted."""
        before = self._collection.count()
        self._collection.delete(where={"doc_id": document_id})
        deleted = before - self._collection.count()
        if deleted < 0:  # defensive: never report a negative count
            deleted = 0
        return deleted

    # ------------------------------------------------------------------ #
    # read operations                                                     #
    # ------------------------------------------------------------------ #

    def search(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int = 5,
        document_id: str | None = None,
    ) -> list[RetrievedChunk]:
        """Similarity search via the Embedder-produced query vector."""
        if self._collection.count() == 0:
            return []
        result = self._collection.query(
            query_embeddings=[[float(v) for v in query_vector]],
            n_results=max(1, top_k),
            include=["documents", "metadatas", "distances"],
            where={"doc_id": document_id} if document_id else None,
        )
        hits: list[RetrievedChunk] = []
        documents_col = result.get("documents") or []
        metadatas_col = result.get("metadatas") or []
        distances_col = result.get("distances") or []
        for docs, metas, dists in zip(documents_col, metadatas_col, distances_col, strict=False):
            for text, meta, distance in zip(docs, metas, dists, strict=False):
                page = meta.get("page", _PAGE_SENTINEL)
                hits.append(
                    RetrievedChunk(
                        document_id=str(meta["doc_id"]),
                        text=text,
                        page=None if page == _PAGE_SENTINEL else int(page),
                        section=int(meta.get("section", 0)),
                        chunk_index=int(meta.get("chunk_index", -1)),
                        distance=float(distance),
                    )
                )
        return hits
