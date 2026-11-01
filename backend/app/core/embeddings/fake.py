"""Deterministic offline embedder for tests.

Produces 32-dim unit vectors from a *bag of hashed words*, so similar texts
get similar vectors. 32 dims keeps hash collisions rare enough for clean
test semantics (unrelated sentences ≈ 0, overlapping sentences high).

This makes the fake useful beyond smoke tests: the M3/M4 retrieval tests can
build a small in-memory corpus and assert on ranking, all offline.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

DIMENSION = 32


class FakeEmbedder:
    """Hash-based bag-of-words embedder; pure math, no model, no network."""

    provider_name = "fake"
    dimension = DIMENSION

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vectors.append(self._hash_vector(text))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def _hash_vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        if not tokens:
            tokens = ["empty"]
        for token in tokens:
            digest = hashlib.sha1(token.encode("utf-8")).hexdigest()
            index = int(digest, 16) % self.dimension
            vec[index] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec
