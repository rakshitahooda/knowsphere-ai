"""Provider-agnostic embedding layer.

App code imports only: Embedder, build_embedder, FakeEmbedder,
SentenceTransformersEmbedder, EmbeddingError(+DependencyMissingError).
"""

from app.core.embeddings.base import (
    DependencyMissingError,
    Embedder,
    EmbeddingError,
    UnsupportedEmbedderError,
)
from app.core.embeddings.factory import build_embedder
from app.core.embeddings.fake import FakeEmbedder
from app.core.embeddings.sentence_transformers import SentenceTransformersEmbedder

__all__ = [
    "DependencyMissingError",
    "Embedder",
    "EmbeddingError",
    "UnsupportedEmbedderError",
    "FakeEmbedder",
    "SentenceTransformersEmbedder",
    "build_embedder",
]
