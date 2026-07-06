from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import bcrypt

_DB_PATH = Path(__file__).parent / "data" / "urbantrace.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id             TEXT PRIMARY KEY,
    user_id        INTEGER,
    label          TEXT,
    created_at     TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Short-lived connection per call — avoids lock contention under uvicorn."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
    _seed_admin()


def _seed_admin() -> None:
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")
    if not username or not password:
        return
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return
        conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'admin', ?)",
            (username, _hash_password(password), _now()),
        )


# ── Passwords ───────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# ── Users ────────────────────────────────────────────────────────────────────

def create_user(username: str, password: str) -> dict[str, Any] | None:
    """Registers a new user with role='user'. Returns None if username taken."""
    username = username.strip()
    if not username or not password:
        return None
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return None
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'user', ?)",
            (username, _hash_password(password), _now()),
        )
        return {"id": cur.lastrowid, "username": username, "role": "user"}


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
    if not row or not _verify_password(password, row["password_hash"]):
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def get_user(user_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


# ── Chat sessions ────────────────────────────────────────────────────────────

def create_chat_session(user_id: int | None) -> str:
    session_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (id, user_id, label, created_at, last_active_at) VALUES (?, ?, NULL, ?, ?)",
            (session_id, user_id, now, now),
        )
    return session_id


def touch_chat_session(session_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE chat_sessions SET last_active_at = ? WHERE id = ?",
            (_now(), session_id),
        )


def set_session_label_if_unset(session_id: str, label: str) -> None:
    """Uses the first user message as a short preview label for session lists."""
    label = label.strip()[:80]
    with get_conn() as conn:
        conn.execute(
            "UPDATE chat_sessions SET label = ? WHERE id = ? AND label IS NULL",
            (label, session_id),
        )


def add_message(session_id: str, role: str, content: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, _now()),
        )
        conn.execute(
            "UPDATE chat_sessions SET last_active_at = ? WHERE id = ?",
            (_now(), session_id),
        )


def get_messages(session_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_sessions_for_user(user_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT cs.id, cs.label, cs.created_at, cs.last_active_at,
                   (SELECT COUNT(*) FROM chat_messages WHERE session_id = cs.id) AS message_count
            FROM chat_sessions cs
            WHERE cs.user_id = ?
            ORDER BY cs.last_active_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_sessions() -> list[dict[str, Any]]:
    """Admin view — every session, including guests (user_id IS NULL)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT cs.id, cs.user_id, u.username, cs.label, cs.created_at, cs.last_active_at,
                   (SELECT COUNT(*) FROM chat_messages WHERE session_id = cs.id) AS message_count
            FROM chat_sessions cs
            LEFT JOIN users u ON u.id = cs.user_id
            ORDER BY cs.last_active_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_session_owner(session_id: str) -> int | None:
    """Returns the owning user_id (None for guest sessions), or raises if the session doesn't exist."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM chat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown chat session: {session_id}")
    return row["user_id"]


def prune_empty_guest_sessions(older_than_days: int = 7) -> int:
    """Deletes guest sessions with zero messages older than the cutoff — keeps bot/crawler
    traffic from growing the DB forever. Returns the number of rows deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """
            DELETE FROM chat_sessions
            WHERE user_id IS NULL
              AND created_at < ?
              AND id NOT IN (SELECT DISTINCT session_id FROM chat_messages)
            """,
            (cutoff,),
        )
        return cur.rowcount
