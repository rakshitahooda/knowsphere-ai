"""M2 tests: embedding layer (interfaces, factory, fakes, error paths).

Real ``sentence-transformers`` runs are opt-in via KNOWSPHERE_EMBED_SMOKE=1
(they download/load the real model); the default suite stays offline.
"""

from __future__ import annotations

import math
import os
from types import SimpleNamespace

import pytest

from app.core.embeddings import (
    DependencyMissingError,
    EmbeddingError,
    UnsupportedEmbedderError,
)
from app.core.embeddings.factory import build_embedder
from app.core.embeddings.fake import FakeEmbedder
from app.core.embeddings.sentence_transformers import SentenceTransformersEmbedder

# --------------------------------------------------------------------- #
# helpers                                                                #
# --------------------------------------------------------------------- #


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def settings_for(provider: str, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "embedding_provider": provider,
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_device": "cpu",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# --------------------------------------------------------------------- #
# FakeEmbedder — the contract retrieval code will rely on offline        #
# --------------------------------------------------------------------- #


def test_fake_embedder_is_deterministic_and_normalized() -> None:
    fake = FakeEmbedder()
    a1 = fake.embed_query("the fast brown fox")
    a2 = fake.embed_query("the fast brown fox")

    assert a1 == a2  # deterministic: identical input → identical vector
    assert len(a1) == fake.dimension == 32
    assert abs(math.sqrt(sum(x * x for x in a1)) - 1.0) < 1e-9  # unit length


def test_fake_embedder_similarity_reflects_word_overlap() -> None:
    fake = FakeEmbedder()
    dog = fake.embed_query("dog chases ball")
    dog_similar = fake.embed_query("dog chases ball again")
    unrelated = fake.embed_query("quantum flux capacitor")

    assert cosine(dog, dog_similar) > 0.8
    assert cosine(dog, unrelated) < 0.5  # 32-dim hash space keeps this low


def test_fake_embedder_batches_preserve_order_and_empty_input() -> None:
    fake = FakeEmbedder()
    texts = ["alpha", "beta", "gamma"]
    batch = fake.embed_texts(texts)

    assert [fake.embed_query(t) for t in texts] == batch  # order preserved
    assert fake.embed_texts([]) == []  # empty input handled
    assert fake.embed_query("") == fake.embed_query("")  # no crash on blank


# --------------------------------------------------------------------- #
# factory + real adapter (construction must stay cheap)                   #
# --------------------------------------------------------------------- #


def test_factory_builds_sentence_transformers_adapter_lazy() -> None:
    embedder = build_embedder(settings_for("sentence-transformers"))
    assert isinstance(embedder, SentenceTransformersEmbedder)
    # Construction must NOT import torch or download anything:
    assert embedder._model is None
    assert embedder.dimension is None
    assert embedder.model_name == "sentence-transformers/all-MiniLM-L6-v2"
    assert embedder._device == "cpu"  # Windows 11 / 16 GB target default


def test_factory_builds_fake_embedder() -> None:
    embedder = build_embedder(settings_for("fake"))
    assert isinstance(embedder, FakeEmbedder)


def test_factory_rejects_unknown_embedder() -> None:
    with pytest.raises(UnsupportedEmbedderError, match="cloud-embed-v9"):
        build_embedder(settings_for("cloud-embed-v9"))


def test_missing_dependency_raises_helpful_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ML extras installed → first embed call fails with install hint."""
    import builtins

    real_import = builtins.__import__

    def no_sentence_transformers(name: str, *args: object, **kwargs: object):
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", no_sentence_transformers)

    embedder = build_embedder(settings_for("sentence-transformers"))
    with pytest.raises(DependencyMissingError, match="requirements-ml.txt"):
        embedder.embed_texts(["hello"])


# --------------------------------------------------------------------- #
# optional real-model smoke test (network + torch required)               #
# --------------------------------------------------------------------- #

requires_ml = pytest.mark.skipif(
    os.environ.get("KNOWSPHERE_EMBED_SMOKE", "") != "1",
    reason="set KNOWSPHERE_EMBED_SMOKE=1 and install requirements-ml.txt to run",
)


@requires_ml
def test_real_sentence_transformers_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real all-MiniLM-L6-v2 on CPU: dimension 384, sane similarity."""
    monkeypatch.setenv("HF_HOME", "data/model-cache")
    embedder = SentenceTransformersEmbedder("sentence-transformers/all-MiniLM-L6-v2")
    vectors = embedder.embed_texts(
        ["The cat sat on the mat.", "A cat rested on a rug.", "Quarterly revenue report."]
    )
    assert len(vectors) == 3
    assert embedder.dimension == 384
    cat_a, cat_b, report = vectors
    assert cosine(cat_a, cat_b) > 0.7
    assert cosine(cat_a, report) < 0.3
