"""M3 tests: ChromaDB vector store — add/search/delete/persistence.

Uses the FakeEmbedder (32-dim, overlap-correlated) so similarity ranking is
deterministic and offline. A REAL persistent chroma collection is created in
each test's tmp directory — persistence across "restarts" is simulated by
constructing a fresh ChromaVectorStore over the same path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.embeddings.fake import FakeEmbedder
from app.core.retrieval.vector_store import ChromaVectorStore, VectorStoreError
from app.ingestion.chunker import Chunk

# --------------------------------------------------------------------- #
# helpers                                                                #
# --------------------------------------------------------------------- #


def chunk(text: str, index: int, page: int | None = 1) -> Chunk:
    return Chunk(text=text, page=page, section=1, index=index)


def fake_vectors(texts: list[str]) -> list[list[float]]:
    return FakeEmbedder().embed_texts(texts)


# --------------------------------------------------------------------- #
# indexing + search                                                      #
# --------------------------------------------------------------------- #


@pytest.fixture()
def store(tmp_path: Path) -> ChromaVectorStore:
    return ChromaVectorStore(tmp_path / "chroma")


def test_add_and_count(store: ChromaVectorStore) -> None:
    texts = ["dog chases ball", "dog barks loudly", "quantum particles"]
    added = store.add_chunks("docA", [chunk(t, i) for i, t in enumerate(texts)], fake_vectors(texts))

    assert added == 3
    assert store.chunk_count == 3


def test_search_returns_most_similar_first(store: ChromaVectorStore) -> None:
    texts = ["quantum particles spin", "dog chases ball", "dog barks loudly"]
    query = FakeEmbedder().embed_query("dog chases ball")
    store.add_chunks("docA", [chunk(t, i) for i, t in enumerate(texts)], fake_vectors(texts))

    hits = store.search(query, top_k=3)

    assert hits[0].text == "dog chases ball"
    assert hits[0].document_id == "docA"
    assert hits[0].page == 1
    assert hits[0].section == 1
    # distances ordered ascending (cosine distance)
    assert [h.distance for h in hits] == sorted(h.distance for h in hits)


def test_top_k_limits_results(store: ChromaVectorStore) -> None:
    texts = [f"sentence number {i} about dogs" for i in range(5)]
    vectors = fake_vectors(texts)
    store.add_chunks("docA", [chunk(t, i) for i, t in enumerate(texts)], vectors)

    hits = store.search(vectors[0], top_k=2)

    assert len(hits) == 2
    assert hits[0].text == texts[0]


def test_search_on_empty_store_returns_empty(store: ChromaVectorStore) -> None:
    assert store.search(FakeEmbedder().embed_query("anything"), top_k=3) == []


def test_chunk_vector_length_mismatch_rejected(store: ChromaVectorStore) -> None:
    with pytest.raises(VectorStoreError, match="mismatch"):
        store.add_chunks("docX", [chunk("a", 0)], [])


def test_empty_embedding_rejected(store: ChromaVectorStore) -> None:
    with pytest.raises(VectorStoreError, match="empty embedding"):
        store.add_chunks("docX", [chunk("a", 0)], [[]])


def test_page_none_roundtrips_via_sentinel(store: ChromaVectorStore) -> None:
    store.add_chunks("docN", [chunk("plain text chunk", 0, page=None)], fake_vectors(["plain text chunk"]))

    hits = store.search(FakeEmbedder().embed_query("plain text chunk"))

    assert hits and hits[0].page is None


# --------------------------------------------------------------------- #
# deletion                                                               #
# --------------------------------------------------------------------- #


def test_delete_document_removes_only_its_vectors(store: ChromaVectorStore) -> None:
    texts_a = ["alpha text one", "alpha text two"]
    texts_b = ["bravo text one"]
    store.add_chunks("docA", [chunk(t, i) for i, t in enumerate(texts_a)], fake_vectors(texts_a))
    store.add_chunks("docB", [chunk(t, 0) for t in texts_b], fake_vectors(texts_b))

    deleted = store.delete_document("docA")

    assert deleted == 2
    assert store.chunk_count == 1
    remaining = store.search(fake_vectors(["bravo text one"])[0])
    assert remaining and remaining[0].document_id == "docB"


def test_delete_unknown_document_is_noop(store: ChromaVectorStore) -> None:
    assert store.delete_document("ghost") == 0


def test_document_scoped_search(store: ChromaVectorStore) -> None:
    texts_a = ["dog chases ball in doc A"]
    texts_b = ["dog chases ball in doc B"]
    store.add_chunks("docA", [chunk(t, 0) for t in texts_a], fake_vectors(texts_a))
    store.add_chunks("docB", [chunk(t, 0) for t in texts_b], fake_vectors(texts_b))

    hits = store.search(FakeEmbedder().embed_query("dog chases ball"), document_id="docB")

    assert len(hits) == 1
    assert hits[0].document_id == "docB"


# --------------------------------------------------------------------- #
# persistence (restart simulation)                                       #
# --------------------------------------------------------------------- #


def test_vectors_persist_across_store_reconstruction(tmp_path: Path) -> None:
    persist_dir = tmp_path / "chroma"
    texts = ["persistent embedding container"]
    vectors = fake_vectors(texts)

    first = ChromaVectorStore(persist_dir)
    first.add_chunks("docP", [chunk(texts[0], 0)], vectors)
    assert first.chunk_count == 1

    # simulate application restart: brand-new client over the same directory
    second = ChromaVectorStore(persist_dir)
    assert second.chunk_count == 1
    hits = second.search(FakeEmbedder().embed_query("persistent embedding container"))
    assert hits and hits[0].text == texts[0]
