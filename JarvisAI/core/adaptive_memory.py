"""Privacy-first local memory for JARVIS personalization.

Only confirmed, allow-listed facts are persisted. Raw conversations are never stored.
Transient emotion/tone hints are deliberately not part of the durable memory schema.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

ALLOWED_CATEGORIES = {"preference", "habit", "interest", "routine", "tone", "goal", "accessibility"}
_MAX_VALUE_CHARS = 500


def default_database_path() -> Path:
    override = os.getenv("JARVIS_MEMORY_DB", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".jarvis" / "memory.sqlite3"


class MemoryStore:
    """SQLite store with explicit opt-in and explicit confirmation for each memory."""

    def __init__(self, database_path: str | Path | None = None):
        self.path = Path(database_path) if database_path else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(category, value)
                )
            """)
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES('memory_enabled', '0')"
            )

    @property
    def enabled(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='memory_enabled'"
            ).fetchone()
        return bool(row and row["value"] == "1")

    def set_enabled(self, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('memory_enabled', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("1" if enabled else "0",),
            )

    def confirm_memory(self, category: str, value: str, confidence: float = 1.0) -> int:
        """Persist a user-confirmed fact; does not implicitly enable memory."""
        category = str(category or "").strip().lower()
        value = str(value or "").strip()
        if category not in ALLOWED_CATEGORIES:
            raise ValueError("Unsupported memory category")
        if not value or len(value) > _MAX_VALUE_CHARS:
            raise ValueError("Memory value must contain 1-500 characters")
        if not self.enabled:
            raise PermissionError("Memory is disabled; enable it explicitly first")
        score = max(0.0, min(float(confidence), 1.0))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories(category, value, confidence) VALUES(?, ?, ?) "
                "ON CONFLICT(category, value) DO UPDATE SET confidence=excluded.confidence",
                (category, value, score),
            )
            row = conn.execute(
                "SELECT id FROM memories WHERE category=? AND value=?", (category, value)
            ).fetchone()
        return int(row["id"])

    def list_memories(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, category, value, confidence, created_at FROM memories "
                "ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_memory(self, memory_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id=?", (int(memory_id),))
        return cursor.rowcount > 0

    def clear(self) -> None:
        """Delete all stored memory facts without changing the user's opt-in setting."""
        with self._connect() as conn:
            conn.execute("DELETE FROM memories")
