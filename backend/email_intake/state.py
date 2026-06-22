"""SQLite-backed dedup store for processed messages."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import config
from .models import Category


class StateStore:
    """Tracks which Gmail message IDs have already been processed."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or config.DB_PATH
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed (
                    message_id   TEXT PRIMARY KEY,
                    category     TEXT,
                    processed_at TEXT
                )
                """
            )

    def already_seen(self, message_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT 1 FROM processed WHERE message_id = ?",
                (message_id,),
            )
            return cur.fetchone() is not None

    def record(self, message_id: str, category: Category) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO processed (message_id, category, processed_at)
                VALUES (?, ?, ?)
                """,
                (
                    message_id,
                    category.value,
                    datetime.now(tz=timezone.utc).isoformat(),
                ),
            )
