"""SQLite connection management and schema initialization.

Only small, structured, non-secret data lives here (accounts metadata,
key/value settings). Campaign history is intentionally not persisted --
runtime campaign state lives in memory for the duration of the process
(see app.campaign.models).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from app.config.paths import get_database_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL UNIQUE,
    telegram_user_id INTEGER,
    username TEXT,
    display_name TEXT,
    session_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Metadata only for explicitly user-saved campaign reports (see
-- app.campaign.report_library) -- deliberately NOT automatic campaign
-- history; a row only exists here because the user clicked "Save report".
-- The actual CSV content lives in a real file under
-- app.config.paths.get_reports_dir() (or the user's configured reports
-- directory); file_path just points at it.
CREATE TABLE IF NOT EXISTS saved_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    total INTEGER NOT NULL,
    successful INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    skipped INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    is_favorite INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = db_path or get_database_path()
        self._connection: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(str(self._path), check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(SCHEMA)
            self._connection.commit()
        return self._connection

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = self.connect()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
