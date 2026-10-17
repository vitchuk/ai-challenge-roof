from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config

DB_PATH: Path = config.DATA_DIR / "app.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                elapsed_ms INTEGER,
                sources TEXT,
                debug TEXT,
                tools TEXT,
                extra TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS pr_seen (
                pr_number INTEGER PRIMARY KEY,
                head_sha TEXT NOT NULL,
                comment_updated_at TEXT,
                viewed_at TEXT NOT NULL
            );
            """
        )
        _migrate(connection)


def _migrate(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(messages)")}
    if "tools" not in columns:
        connection.execute("ALTER TABLE messages ADD COLUMN tools TEXT")
    if "extra" not in columns:
        connection.execute("ALTER TABLE messages ADD COLUMN extra TEXT")


def create_chat(title: str = "Новый чат") -> dict:
    chat_id = uuid.uuid4().hex
    timestamp = _now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (chat_id, title, timestamp, timestamp),
        )
    return {"id": chat_id, "title": title, "created_at": timestamp, "updated_at": timestamp}


def list_chats() -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, title, created_at, updated_at FROM chats ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def delete_chat(chat_id: str) -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        connection.execute("DELETE FROM chats WHERE id = ?", (chat_id,))


def delete_all_chats() -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM messages")
        connection.execute("DELETE FROM chats")


def get_chat(chat_id: str) -> dict | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
    return dict(row) if row else None


def _rename_if_needed(connection: sqlite3.Connection, chat_id: str, text: str) -> None:
    row = connection.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone()
    if row and row["title"] in ("Новый чат", ""):
        title = text.strip().replace("\n", " ")[:60] or "Новый чат"
        connection.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))


def add_message(
    chat_id: str,
    role: str,
    content: str,
    *,
    elapsed_ms: int | None = None,
    sources: list | None = None,
    debug: dict | None = None,
    tools: list | None = None,
    extra: dict | None = None,
) -> dict:
    timestamp = _now()
    with _connect() as connection:
        if role == "user":
            _rename_if_needed(connection, chat_id, content)
        cursor = connection.execute(
            """
            INSERT INTO messages (chat_id, role, content, elapsed_ms, sources, debug, tools, extra, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                role,
                content,
                elapsed_ms,
                json.dumps(sources, ensure_ascii=False) if sources is not None else None,
                json.dumps(debug, ensure_ascii=False) if debug is not None else None,
                json.dumps(tools, ensure_ascii=False) if tools is not None else None,
                json.dumps(extra, ensure_ascii=False) if extra is not None else None,
                timestamp,
            ),
        )
        connection.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (timestamp, chat_id))
        message_id = cursor.lastrowid
    return {
        "id": message_id,
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "elapsed_ms": elapsed_ms,
        "sources": sources or [],
        "debug": debug,
        "tools": tools or [],
        "extra": extra,
        "created_at": timestamp,
    }


def get_messages(chat_id: str) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, chat_id, role, content, elapsed_ms, sources, debug, tools, extra, created_at
            FROM messages WHERE chat_id = ? ORDER BY id ASC
            """,
            (chat_id,),
        ).fetchall()
    messages: list[dict] = []
    for row in rows:
        message = dict(row)
        message["sources"] = json.loads(message["sources"]) if message["sources"] else []
        message["debug"] = json.loads(message["debug"]) if message["debug"] else None
        message["tools"] = json.loads(message["tools"]) if message["tools"] else []
        message["extra"] = json.loads(message["extra"]) if message["extra"] else None
        messages.append(message)
    return messages


def recent_history(chat_id: str, limit: int) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT role, content FROM messages
            WHERE chat_id = ? ORDER BY id DESC LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()
    history = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
    return [item for item in history if item["role"] in ("user", "assistant")]


def list_pr_seen() -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT pr_number, head_sha, comment_updated_at, viewed_at FROM pr_seen"
        ).fetchall()
    return [dict(row) for row in rows]


def get_pr_seen(pr_number: int) -> dict | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT pr_number, head_sha, comment_updated_at, viewed_at FROM pr_seen WHERE pr_number = ?",
            (pr_number,),
        ).fetchone()
    return dict(row) if row else None


def upsert_pr_seen(pr_number: int, head_sha: str, comment_updated_at: str | None) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO pr_seen (pr_number, head_sha, comment_updated_at, viewed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pr_number) DO UPDATE SET
                head_sha = excluded.head_sha,
                comment_updated_at = excluded.comment_updated_at,
                viewed_at = excluded.viewed_at
            """,
            (pr_number, head_sha, comment_updated_at, _now()),
        )
