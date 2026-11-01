"""Sentence-transformers embedding adapter — local, CPU by default.

Key properties:

- *Lazy loading*: the heavy model (~90 MB for all-MiniLM-L6-v2) is loaded on
  the first actual embed call, not at construction. Constructing/factories in
  tests or route setup therefore cost nothing and download nothing.
- *CPU default*: matches the 16 GB-RAM / Windows 11 target; no GPU code paths.
- *Unit-normalized* vectors so cosine similarity equals a plain dot product
  in the vector store (M3) — cheaper and less error-prone.

``sentence_transformers`` is imported lazily inside ``_ensure_loaded`` so the
base install stays lightweight; a missing install raises a clear
``DependencyMissingError`` instead of an import traceback.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.embeddings.base import DependencyMissingError

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class SentenceTransformersEmbedder:
    """Local embeddings via sentence-transformers (torch/CPU)."""

    provider_name = "sentence-transformers"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        device: str = "cpu",
        batch_size: int = 16,
    ) -> None:
        self.model_name = model_name
        self._device = device
        self._batch_size = batch_size
        self._model = None  # loaded on first use
        self._np = None  # numpy bound during lazy _ensure_loaded
        self.dimension: int | None = None

    # ------------------------------------------------------------------ #

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # keep base install lightweight
            raise DependencyMissingError(
                "sentence-transformers / numpy are not installed. "
                "Install ML extras with: pip install -r requirements-ml.txt",
                provider=self.provider_name,
            ) from exc
        self._model = SentenceTransformer(self.model_name, device=self._device)
        self.dimension = self._model.get_sentence_embedding_dimension()
        self._np = np

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        self._ensure_loaded()
        assert self._model is not None  # set by _ensure_loaded
        if not texts:
            return []
        # normalize_embeddings → unit vectors; dot((a,b)) = cosine similarity
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return self._np.asarray(vectors).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]
