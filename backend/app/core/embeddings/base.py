"""Embedding boundary — the retrieval-side twin of ``core/llm/base.py``.

``Embedder`` converts text into float vectors. Retrieval only ever sees this
protocol, so the vector store (M3) never learns whether embeddings came from
a local CPU model or a fake in tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    """Contract for text-embedding backends."""

    #: Short identifier, e.g. "sentence-transformers", "fake".
    provider_name: str

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts; order and length of input are preserved."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query (same space as embed_texts)."""
        ...


class EmbeddingError(Exception):
    """Base class for embedding failures."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider


class DependencyMissingError(EmbeddingError):
    """The embedding library is not installed (see requirements-ml.txt)."""


class UnsupportedEmbedderError(EmbeddingError):
    """The configured embedding provider has no registered adapter."""
