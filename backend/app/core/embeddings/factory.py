"""Factory: Settings-like object → concrete embedder.

Embeddings are LOCAL by default (key-free workflow). If the ML extras are not
installed, constructing the adapter succeeds — only the first embed call
raises ``DependencyMissingError`` with install instructions, keeping startup
cheap and testable.
"""

from __future__ import annotations

from typing import Any

from app.core.embeddings.base import UnsupportedEmbedderError
from app.core.embeddings.fake import FakeEmbedder
from app.core.embeddings.sentence_transformers import SentenceTransformersEmbedder


def build_embedder(settings: Any) -> SentenceTransformersEmbedder | FakeEmbedder:
    """Instantiate the embedder named by ``settings.embedding_provider``."""
    name = getattr(settings, "embedding_provider", "sentence-transformers")

    if name == "sentence-transformers":
        return SentenceTransformersEmbedder(
            model_name=getattr(settings, "embedding_model", "sentence-transformers/all-MiniLM-L6-v2"),
            device=getattr(settings, "embedding_device", "cpu"),
        )

    if name == "fake":
        return FakeEmbedder()

    raise UnsupportedEmbedderError(
        f"no adapter registered for embedding_provider={name!r}", provider=str(name)
    )
