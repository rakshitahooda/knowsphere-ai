"""SQLite persistence for conversations and messages (M4).

Lives next to the documents DB (same file, separate schema). Uses stdlib
sqlite3 like ``repository.py`` — single-writer reads are cheap, WAL mode
allows concurrent history reads during streaming writes.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.db.repository import utc_now_iso


class ConversationNotFoundError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class Message:
    role: str  # "user" | "assistant"
    content: str
    citations: list[dict] | None  # assistant only; parsed JSON
    created_at: str


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    id: str
    title: str
    created_at: str
    message_count: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    citations       TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, id);
"""


class ConversationRepository:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ------------------------------------------------------------------ #
    # conversations                                                       #
    # ------------------------------------------------------------------ #

    def create(self, title: str) -> str:
        conversation_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at) VALUES (?, ?, ?)",
                (conversation_id, title[:120], utc_now_iso()),
            )
        return conversation_id

    def exists(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return row is not None

    def list(self) -> list[ConversationSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.title, c.created_at, COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id
                ORDER BY c.created_at DESC, c.id
                """
            ).fetchall()
        return [
            ConversationSummary(
                id=row["id"],
                title=row["title"],
                created_at=row["created_at"],
                message_count=row["message_count"],
            )
            for row in rows
        ]

    def rename(self, conversation_id: str, title: str) -> None:
        """Set a new title; raises ConversationNotFoundError if missing."""
        if not self.exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title[:120], conversation_id),
            )

    def delete(self, conversation_id: str) -> None:
        """Delete a conversation and all of its messages (idempotent on
        concurrent deletes via the exists() precheck)."""
        if not self.exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            conn.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )

    # ------------------------------------------------------------------ #
    # messages                                                            #
    # ------------------------------------------------------------------ #

    def append(
        self,
        conversation_id: str,
        role: str,
        content: str,
        citations: Sequence[dict] | None = None,
    ) -> int:
        citations_json = json.dumps(citations, ensure_ascii=False) if citations else None
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, citations, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, role, content, citations_json, utc_now_iso()),
            )
            return int(cursor.lastrowid)

    def messages(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
    ) -> list[Message]:
        """Messages of a conversation, oldest first. ``limit`` keeps the most
        recent N (still returned oldest-first, ready for prompt assembly)."""
        query = (
            "SELECT role, content, citations, created_at "
            "FROM messages WHERE conversation_id = ? ORDER BY id DESC"
        )
        with self._connect() as conn:
            if limit is not None and limit >= 0:
                rows = conn.execute(query + " LIMIT ?", (conversation_id, int(limit))).fetchall()
            else:
                rows = conn.execute(query, (conversation_id,)).fetchall()
        rows = list(reversed(rows))  # oldest-first ordering

        def build(row: sqlite3.Row) -> Message:
            citations = json.loads(row["citations"]) if row["citations"] else None
            return Message(
                role=row["role"],
                content=row["content"],
                citations=citations,
                created_at=row["created_at"],
            )

        return [build(row) for row in rows]
