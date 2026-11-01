"""M4 tests: retriever — ranking, top-k, similarity threshold filtering.

Offline via FakeEmbedder + real Chroma in tmp dirs.
"""

from __future__ import annotations

import pytest

from app.core.embeddings.fake import FakeEmbedder
from app.core.retrieval.retriever import Retriever, RetrieverConfig
from app.core.retrieval.vector_store import ChromaVectorStore
from app.ingestion.chunker import Chunk

# --------------------------------------------------------------------- #
# fixtures                                                               #
# --------------------------------------------------------------------- #


@pytest.fixture()
def store(tmp_path) -> ChromaVectorStore:
    return ChromaVectorStore(tmp_path / "chroma")


def seed(store: ChromaVectorStore, doc_id: str, texts: list[str]) -> None:
    chunks = [Chunk(text=t, page=i + 1, section=1, index=i) for i, t in enumerate(texts)]
    store.add_chunks(doc_id, chunks, FakeEmbedder().embed_texts(texts))


# --------------------------------------------------------------------- #
# ranking + top-k                                                        #
# --------------------------------------------------------------------- #


def test_top_hit_is_the_most_similar_chunk(store: ChromaVectorStore) -> None:
    seed(store, "pets", ["dog chases ball", "dog barks loudly", "quantum spin precession"])
    retriever = Retriever(store=store, embedder=FakeEmbedder())

    hits = retriever.retrieve("dog chases ball")

    assert hits[0].text == "dog chases ball"  # identical text ranks first
    distances = [h.distance for h in hits]
    assert distances == sorted(distances)  # ranked by ascending distance


def test_top_k_limits_number_of_results(store: ChromaVectorStore) -> None:
    seed(store, "pets", [
        "dog chases ball", "dog barks loudly", "dog eats food", "dog sleeps",
    ])
    retriever = Retriever(store=store, embedder=FakeEmbedder(), config=RetrieverConfig())

    hits = retriever.retrieve("dog", top_k=2)

    assert len(hits) == 2


def test_configured_top_k_used_when_no_override(store: ChromaVectorStore) -> None:
    seed(store, "pets", ["dog one", "dog two", "dog three"])
    retriever = Retriever(
        store=store, embedder=FakeEmbedder(), config=RetrieverConfig(top_k=2)
    )

    assert len(retriever.retrieve("dog")) == 2


def test_per_request_top_k_clamped_to_bounds(store: ChromaVectorStore) -> None:
    retriever = Retriever(store=store, embedder=FakeEmbedder())
    assert retriever._clamp_top_k(99) == 20
    assert retriever._clamp_top_k(-3) == 1


# --------------------------------------------------------------------- #
# similarity threshold                                                   #
# --------------------------------------------------------------------- #


def test_threshold_filters_distant_chunks(store: ChromaVectorStore) -> None:
    seed(store, "mixed", ["dog chases ball", "quantum flux capacitor"])
    retriever = Retriever(store=store, embedder=FakeEmbedder())

    strict = retriever.retrieve("dog chases ball", top_k=2, min_similarity=0.99)
    # only the (identical-text) chunk reaches similarity ≈ 1.0
    assert [h.text for h in strict] == ["dog chases ball"]

    loose = retriever.retrieve("dog chases ball", top_k=2, min_similarity=0.0)
    assert len(loose) == 2  # nothing filtered at zero floor


def test_configured_threshold_applies_by_default(store: ChromaVectorStore) -> None:
    seed(store, "mixed", ["dog chases ball", "quantum flux capacitor"])
    retriever = Retriever(
        store=store,
        embedder=FakeEmbedder(),
        config=RetrieverConfig(min_similarity=0.99),
    )

    hits = retriever.retrieve("dog chases ball")
    assert [h.text for h in hits] == ["dog chases ball"]  # distant chunk filtered


def test_retrieve_on_empty_store_returns_nothing(tmp_path) -> None:
    retriever = Retriever(
        store=ChromaVectorStore(tmp_path / "chroma"),
        embedder=FakeEmbedder(),
    )
    assert retriever.retrieve("anything") == []


def test_invalid_threshold_rejected(store: ChromaVectorStore) -> None:
    retriever = Retriever(store=store, embedder=FakeEmbedder())
    with pytest.raises(ValueError, match="min_similarity"):
        retriever.retrieve("dog", min_similarity=1.5)


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError):
        RetrieverConfig(top_k=0)
    with pytest.raises(ValueError):
        RetrieverConfig(min_similarity=1.2)
