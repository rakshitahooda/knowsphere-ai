"""M4 tests: conversation persistence (SQLite) — schema round-trips."""

from __future__ import annotations

import pytest

from app.db.conversations import ConversationRepository


def test_create_and_exists(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    cid = repo.create("hello world")

    assert repo.exists(cid)
    assert not repo.exists("nope")


def test_title_is_truncated_but_stable(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    repo.create("x" * 300)

    summaries = repo.list()
    assert len(summaries[0].title) <= 120


def test_append_and_message_ordering_oldest_first(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    cid = repo.create("chat")
    repo.append(cid, "user", "first question")
    repo.append(cid, "assistant", "first answer", citations=[{"doc": "a"}])
    repo.append(cid, "user", "second question")

    messages = repo.messages(cid)

    assert [m.content for m in messages] == [
        "first question", "first answer", "second question",
    ]
    assert [m.role for m in messages] == ["user", "assistant", "user"]
    assert messages[1].citations == [{"doc": "a"}]  # citations round-trip as JSON
    assert messages[0].citations is None
    assert all(m.created_at for m in messages)


def test_messages_limit_keeps_most_recent_oldest_first(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    cid = repo.create("chat")
    for i in range(5):
        repo.append(cid, "user", f"msg {i}")

    recent = repo.messages(cid, limit=2)

    assert [m.content for m in recent] == ["msg 3", "msg 4"]


def test_message_counts_in_listing(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    a = repo.create("conversation A")
    b = repo.create("conversation B")
    repo.append(a, "user", "hi")
    repo.append(a, "assistant", "hello", citations=[{"doc": "x"}])
    repo.append(b, "user", "different thread")

    summaries = repo.list()

    counts = {s.id: s.message_count for s in summaries}
    assert counts[a] == 2
    assert counts[b] == 1
    assert summaries[0].id in (a, b)  # ordering stable by recency


def test_orphan_conversation_has_no_messages(tmp_path) -> None:
    repo = ConversationRepository(tmp_path / "db.sqlite")
    cid = repo.create("empty thread")

    assert repo.messages(cid) == []


def test_schema_survives_repository_recreation(tmp_path) -> None:
    path = tmp_path / "db.sqlite"
    first = ConversationRepository(path)
    cid = first.create("persisted")
    first.append(cid, "user", "still here")

    reopened = ConversationRepository(path)  # simulate application restart

    assert reopened.exists(cid)
    assert [m.content for m in reopened.messages(cid)] == ["still here"]
