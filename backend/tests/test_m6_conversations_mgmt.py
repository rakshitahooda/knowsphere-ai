"""M6 tests: conversation rename/delete — repository + HTTP routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.conversations import ConversationNotFoundError, ConversationRepository
from app.main import create_app

# --------------------------------------------------------------------- #
# repository level                                                       #
# --------------------------------------------------------------------- #


def test_rename_updates_title_only(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    cid = repo.create("original title")

    repo.rename(cid, "renamed")

    summaries = [s for s in repo.list() if s.id == cid]
    assert summaries[0].title == "renamed"
    assert summaries[0].message_count == 0  # messages untouched


def test_rename_truncates_long_titles(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    cid = repo.create("x")

    repo.rename(cid, "t" * 300)

    assert [s for s in repo.list() if s.id == cid][0].title == "t" * 120


def test_rename_missing_conversation_raises(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    with pytest.raises(ConversationNotFoundError):
        repo.rename("missing", "nope")


def test_delete_removes_conversation_and_messages(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    cid = repo.create("doomed")
    repo.append(cid, "user", "hello")
    repo.append(cid, "assistant", "hi")

    repo.delete(cid)

    assert not repo.exists(cid)
    assert repo.messages(cid) == []
    assert all(summary.id != cid for summary in repo.list())


def test_delete_missing_conversation_raises(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    with pytest.raises(ConversationNotFoundError):
        repo.delete("ghost")


# --------------------------------------------------------------------- #
# HTTP route level (real app, fake providers)                            #
# --------------------------------------------------------------------- #


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    with TestClient(create_app(Settings())) as c:
        yield c


def _make_conversation(client: TestClient, question: str) -> str:
    import json as _json

    response = client.post("/api/chat", json={"question": question})
    assert response.status_code == 200
    for line in response.text.split("\n"):
        if not line.startswith("data: ") or "conversation_id" not in line:
            continue
        payload = _json.loads(line[len("data: "):])
        if "conversation_id" in payload:
            return payload["conversation_id"]
    raise AssertionError("no meta event with conversation_id")


def test_rename_route_roundtrip(client: TestClient) -> None:
    cid = _make_conversation(client, "rename me")

    response = client.patch(f"/api/conversations/{cid}", json={"title": "  better name  "})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == cid
    assert body["title"] == "better name"  # whitespace stripped
    listing = client.get("/api/conversations")
    assert any(item["title"] == "better name" for item in listing.json())


def test_rename_route_404_on_missing(client: TestClient) -> None:
    response = client.patch("/api/conversations/nope", json={"title": "x"})
    assert response.status_code == 404


def test_rename_route_400_on_blank_title(client: TestClient) -> None:
    cid = _make_conversation(client, "seed")
    response = client.patch(f"/api/conversations/{cid}", json={"title": "   "})
    assert response.status_code == 400


def test_rename_route_422_on_too_long_title(client: TestClient) -> None:
    response = client.patch("/api/conversations/any", json={"title": "t" * 121})
    assert response.status_code == 422


def test_delete_route_removes_conversation(client: TestClient) -> None:
    cid = _make_conversation(client, "delete me")

    response = client.delete(f"/api/conversations/{cid}")
    assert response.status_code == 204

    listing = client.get("/api/conversations")
    assert listing.json() == []
    assert client.get(f"/api/conversations/{cid}/messages").status_code == 404


def test_delete_route_404_on_missing(client: TestClient) -> None:
    assert client.delete("/api/conversations/ghost").status_code == 404


def test_delete_routes_are_independent(client: TestClient) -> None:
    """Deleting one conversation leaves others intact."""
    first = _make_conversation(client, "first")
    second = _make_conversation(client, "second")

    client.delete(f"/api/conversations/{first}")

    remaining = {item["id"] for item in client.get("/api/conversations").json()}
    assert remaining == {second}
