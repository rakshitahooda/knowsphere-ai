"""Query-side retrieval: question → top-k relevant chunks.

Pure composition over the two existing interfaces (``Embedder`` produces the
query vector, ``ChromaVectorStore`` searches it). Ranking, limiting and
threshold filtering happen here so the RAG pipeline never touches Chroma
directly.

Similarity semantics: Chroma returns cosine *distance* in [0, 2]; converted
similarity = 1 - distance ∈ [-1, 1]. ``min_similarity`` filters everything
below the floor — set it to 0 to keep all top-k hits.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.embeddings.base import Embedder
from app.core.retrieval.vector_store import RetrievedChunk

TOP_K_MIN = 1
TOP_K_MAX = 20


@dataclass(frozen=True)
class RetrieverConfig:
    top_k: int = 5
    min_similarity: float = 0.30

    def __post_init__(self) -> None:
        if self.top_k < TOP_K_MIN:
            raise ValueError(f"top_k must be >= {TOP_K_MIN}")
        if not 0.0 <= self.min_similarity <= 1.0:
            raise ValueError("min_similarity must be within [0, 1]")


class Retriever:
    def __init__(
        self,
        *,
        store: object,  # ChromaVectorStore; typed loosely to avoid cycle
        embedder: Embedder,
        config: RetrieverConfig | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._config = config or RetrieverConfig()

    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        min_similarity: float | None = None,
    ) -> list[RetrievedChunk]:
        """Embed *query* and return the most relevant chunks above the floor.

        ``top_k``/``min_similarity`` override the configured defaults
        (per-request tuning); both are clamped/validated defensively.
        """
        effective_k = self._clamp_top_k(top_k if top_k is not None else self._config.top_k)
        floor = (
            self._config.min_similarity if min_similarity is None else float(min_similarity)
        )
        if not 0.0 <= floor <= 1.0:
            raise ValueError("min_similarity must be within [0, 1]")

        query_vector = self._embedder.embed_query(query)
        hits = self._store.search(query_vector, top_k=effective_k)  # type: ignore[attr-defined]
        return [hit for hit in hits if (1.0 - hit.distance) >= floor]

    @staticmethod
    def _clamp_top_k(value: int) -> int:
        return max(TOP_K_MIN, min(TOP_K_MAX, int(value)))
