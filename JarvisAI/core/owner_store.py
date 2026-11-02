"""The owner's small persistent store: SQLite in the user data folder.

One file, ``<user data>/owner.db``, holds:

* routines — named tool-call sequences (core/routines.py)
* rules    — "when <event> matches <condition>, do <action>" (Module 6)
* facts    — short things the owner asked JARVIS to remember (Module 6)

Everything is small text; the store caps each table so it stays small.
Connections are opened per call (SQLite is fast at that and it keeps the store
safe to use from tool threads).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from core.routines import RoutineStore, normalize_name, validate_steps

SCHEMA_VERSION = 1
MAX_ROUTINES = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS routines (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL,
    created REAL NOT NULL,
    updated REAL NOT NULL,
    last_run REAL
);
"""


class OwnerStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._extra_schema: list[str] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(_SCHEMA)
            db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema', ?)",
                       (str(SCHEMA_VERSION),))
        self.routines = SqliteRoutineStore(self)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = sqlite3.connect(str(self.path), timeout=10)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            finally:
                db.close()

    def ensure_schema(self, sql: str) -> None:
        with self.connect() as db:
            db.executescript(sql)


class SqliteRoutineStore(RoutineStore):
    def __init__(self, store: OwnerStore):
        self._store = store

    def save(self, name: str, steps: list[dict], description: str = "") -> None:
        key = normalize_name(name)
        clean = validate_steps(steps)
        now = time.time()
        with self._store.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM routines").fetchone()[0]
            exists = db.execute("SELECT 1 FROM routines WHERE name=?", (key,)).fetchone()
            if not exists and count >= MAX_ROUTINES:
                raise ValueError(f"already {MAX_ROUTINES} routines saved; delete one first")
            db.execute(
                "INSERT INTO routines(name, description, steps, created, updated) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                "description=excluded.description, steps=excluded.steps, updated=excluded.updated",
                (key, description or "", json.dumps(clean), now, now))

    def _row(self, row) -> dict:
        return {"name": row["name"], "description": row["description"],
                "steps": json.loads(row["steps"]), "last_run": row["last_run"]}

    def get(self, name: str) -> Optional[dict]:
        key = normalize_name(name)
        with self._store.connect() as db:
            row = db.execute("SELECT * FROM routines WHERE name=?", (key,)).fetchone()
        return self._row(row) if row else None

    def list(self) -> list[dict]:
        with self._store.connect() as db:
            rows = db.execute("SELECT * FROM routines ORDER BY name").fetchall()
        return [self._row(r) for r in rows]

    def delete(self, name: str) -> bool:
        key = normalize_name(name)
        with self._store.connect() as db:
            return db.execute("DELETE FROM routines WHERE name=?", (key,)).rowcount > 0

    def mark_run(self, name: str) -> None:
        with self._store.connect() as db:
            db.execute("UPDATE routines SET last_run=? WHERE name=?",
                       (time.time(), normalize_name(name)))


_STORE: Optional[OwnerStore] = None
_STORE_LOCK = threading.Lock()


def get_owner_store() -> OwnerStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            from core.user_data import user_data_file
            _STORE = OwnerStore(user_data_file("owner.db"))
        return _STORE


def reset_owner_store_for_tests(store: Optional[OwnerStore] = None) -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = store
