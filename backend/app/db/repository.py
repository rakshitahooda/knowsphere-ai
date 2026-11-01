"""SQLite persistence for document metadata.

Deliberately uses the stdlib ``sqlite3`` module (no ORM dependency): the
metadata model is a single table, and fewer dependencies means fewer
Windows/16GB headaches. Schema is created idempotently on construction, so
pointing a repository at a restart-persistent path just works (WAL mode for
safe concurrent reads while uploads write).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class DocumentNotFoundError(KeyError):
    """No document row for the requested id."""


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    id: str
    original_name: str
    stored_name: str  # filename actually on disk inside uploads dir
    content_type: str
    size_bytes: int
    num_chunks: int
    status: str  # "ready" (future: "parsing", "failed")
    created_at: str  # ISO-8601 UTC


_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    stored_name   TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    num_chunks    INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'ready',
    sha256        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DocumentRepository:
    """CRUD over the ``documents`` table."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ #

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def add(self, meta: DocumentMeta, sha256: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO documents
                    (id, original_name, stored_name, content_type,
                     size_bytes, num_chunks, status, sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meta.id,
                    meta.original_name,
                    meta.stored_name,
                    meta.content_type,
                    meta.size_bytes,
                    meta.num_chunks,
                    meta.status,
                    sha256,
                    meta.created_at,
                ),
            )

    def get(self, document_id: str) -> DocumentMeta:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        if row is None:
            raise DocumentNotFoundError(document_id)
        return self._to_meta(row)

    def get_by_sha256(self, sha256: str) -> DocumentMeta | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE sha256 = ?", (sha256,)
            ).fetchone()
        return self._to_meta(row) if row is not None else None

    def list(self) -> list[DocumentMeta]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC, id"
            ).fetchall()
        return [self._to_meta(row) for row in rows]

    def delete(self, document_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return cursor.rowcount > 0

    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_meta(row: sqlite3.Row) -> DocumentMeta:
        return DocumentMeta(
            id=row["id"],
            original_name=row["original_name"],
            stored_name=row["stored_name"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            num_chunks=row["num_chunks"],
            status=row["status"],
            created_at=row["created_at"],
        )
