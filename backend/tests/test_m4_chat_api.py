"""M4 tests: /api/chat SSE endpoint + conversation endpoints (HTTP layer).

Runs against the real app with fake embedder + fake LLM (env-overridden),
real Chroma/SQLite in tmp dirs.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

# --------------------------------------------------------------------- #
# helpers                                                                #
# --------------------------------------------------------------------- #


@contextmanager
def _make_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path, **settings_overrides
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    with TestClient(create_app(Settings(**settings_overrides))) as client:
        yield client


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    with _make_client(monkeypatch, tmp_path) as c:
        yield c


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, payload) tuples."""
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        name = next(line[len("event: "):] for line in lines if line.startswith("event: "))
        data = json.loads(next(line[len("data: "):] for line in lines if line.startswith("data: ")))
        events.append((name, data))
    return events


def seed_documents(client: TestClient, count: int = 2) -> None:
    body = ("dog chases ball in the yard while the sun sets " * 10).encode()
    client.post("/api/documents", files={"file": ("pets.txt", body, "text/plain")})
    if count > 1:
        client.post(
            "/api/documents",
            files={"file": ("physics.txt", b"quantum spin precession makes particles turn", "text/plain")},
        )


def ask(client: TestClient, question: str, **extra):
    return client.post("/api/chat", json={"question": question, **extra})


# --------------------------------------------------------------------- #
# happy path                                                             #
# --------------------------------------------------------------------- #


def test_chat_streams_full_sse_protocol_with_citations(client: TestClient) -> None:
    seed_documents(client)

    response = ask(client, "does the dog chase the ball?")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]

    assert names[0] == "meta"
    assert names.count("delta") >= 2  # multi-chunk stream
    assert names[-1] == "done"

    meta = events[0][1]
    assert meta["has_context"] is True
    assert meta["citations"], "citations must be present for a seeded corpus"
    citation = meta["citations"][0]
    assert citation["document_name"] == "pets.txt"
    assert citation["chunk_index"] >= 0 and "snippet" in citation

    conversation_id = meta["conversation_id"]
    messages = client.get(f"/api/conversations/{conversation_id}/messages")
    assert messages.status_code == 200
    assert [m["role"] for m in messages.json()] == ["user", "assistant"]
    assert messages.json()[1]["citations"]


def test_conversation_round_trip_persists_history(client: TestClient) -> None:
    seed_documents(client, count=1)

    first = ask(client, "first question")
    conversation_id = parse_sse(first.text)[0][1]["conversation_id"]

    second = ask(client, "second question", conversation_id=conversation_id)
    assert parse_sse(second.text)[0][1]["conversation_id"] == conversation_id

    listing = client.get("/api/conversations")
    assert listing.status_code == 200
    assert listing.json()[0]["message_count"] == 4  # 2 user + 2 assistant turns


def test_empty_collection_never_fabricates_citations(monkeypatch, tmp_path) -> None:
    with _make_client(monkeypatch, tmp_path) as client:  # seeded with NOTHING

        response = ask(client, "anything")

    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["meta", "delta", "done"]
    assert events[0][1]["has_context"] is False
    assert events[0][1]["citations"] == []
    assert "could not find" in events[1][1]["text"]


# --------------------------------------------------------------------- #
# request validation / error mapping                                     #
# --------------------------------------------------------------------- #


def test_blank_question_maps_to_400(client: TestClient) -> None:
    response = ask(client, "   ")
    assert response.status_code == 400


def test_empty_question_maps_to_422(client: TestClient) -> None:
    assert ask(client, "").status_code == 422


def test_top_k_bounds_enforced(client: TestClient) -> None:
    assert ask(client, "hi", top_k=0).status_code == 422
    assert ask(client, "hi", top_k=99).status_code == 422


def test_unknown_conversation_maps_to_404(client: TestClient) -> None:
    assert ask(client, "hello there", conversation_id="ghost").status_code == 404


def test_unknown_conversation_details_404(client: TestClient) -> None:
    assert client.get("/api/conversations/ghost/messages").status_code == 404


# --------------------------------------------------------------------- #
# provider failure paths (offline-simulated)                             #
# --------------------------------------------------------------------- #


def test_offline_ollama_yields_in_stream_error_event(tmp_path, monkeypatch) -> None:
    """Default key-free provider pointed at a dead port (Ollama not running)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    settings = Settings(llm_provider="ollama", ollama_base_url="http://127.0.0.1:1")

    with TestClient(create_app(settings)) as client:
        # seed via the API so retrieval has context and the LLM is reached
        seed_documents(client, count=1)
        response = ask(
            client,
            "does the dog chase the ball in the yard?",
        )

    assert response.status_code == 200  # stream started; failure is in-stream
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "error"
    assert events[-1][1]["kind"] == "provider_unavailable"


def test_openrouter_without_key_surfaced_as_not_configured(tmp_path, monkeypatch) -> None:
    """OpenRouter selected with an empty key must fail per-request, not
    crash startup, and must be a clear in-stream error."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    settings = Settings(llm_provider="openrouter", openrouter_api_key="")

    with TestClient(create_app(settings)) as client:
        seed_documents(client, count=1)
        response = ask(client, "does the dog chase the ball?")

    events = parse_sse(response.text)
    assert events[0][0] == "meta"
    assert events[-1][0] == "error"
    assert events[-1][1]["kind"] == "provider_not_configured"
    assert "OPENROUTER_API_KEY" in events[-1][1]["message"]
