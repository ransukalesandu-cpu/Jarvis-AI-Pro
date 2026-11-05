"""Run history for proactive triggers (kept in the existing owner SQLite database).

One row per attempt, whatever the outcome, so "did my 7:30 briefing run?" has an
answer. Only the newest ``KEEP_PER_TRIGGER`` rows per trigger are kept.
"""
from __future__ import annotations

import time
from typing import Optional

KEEP_PER_TRIGGER = 200
STATUSES = ("ok", "failed", "skipped_quiet", "skipped_busy", "blocked", "started")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trigger_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'turn',
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    started REAL NOT NULL,
    finished REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS trigger_runs_name ON trigger_runs(name, id);
"""
_ready: set[str] = set()


def _store(store=None):
    if store is None:
        from jarvis.core.owner_store import get_owner_store
        store = get_owner_store()
    if str(store.path) not in _ready:
        store.ensure_schema(_SCHEMA)
        _ready.add(str(store.path))
    return store


def record(name: str, status: str, *, mode: str = "turn", detail: str = "",
           started: Optional[float] = None, finished: Optional[float] = None,
           store=None) -> int:
    if status not in STATUSES:
        raise ValueError(f"unknown run status '{status}'")
    now = time.time()
    store = _store(store)
    with store.connect() as db:
        cur = db.execute(
            "INSERT INTO trigger_runs(name, mode, status, detail, started, finished) VALUES (?,?,?,?,?,?)",
            (name, mode, status, str(detail)[:500], now if started is None else started,
             now if finished is None else finished))
        row_id = int(cur.lastrowid)
        db.execute(
            "DELETE FROM trigger_runs WHERE name = ? AND id NOT IN "
            "(SELECT id FROM trigger_runs WHERE name = ? ORDER BY id DESC LIMIT ?)",
            (name, name, KEEP_PER_TRIGGER))
    return row_id


def update(run_id: int, status: str, detail: str = "", store=None) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown run status '{status}'")
    store = _store(store)
    with store.connect() as db:
        db.execute("UPDATE trigger_runs SET status = ?, detail = ?, finished = ? WHERE id = ?",
                   (status, str(detail)[:500], time.time(), int(run_id)))


def runs(name: Optional[str] = None, limit: int = 20, store=None) -> list[dict]:
    store = _store(store)
    limit = max(1, min(int(limit), KEEP_PER_TRIGGER))
    with store.connect() as db:
        if name:
            rows = db.execute("SELECT * FROM trigger_runs WHERE name = ? ORDER BY id DESC LIMIT ?",
                              (name, limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM trigger_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def reset_for_tests() -> None:
    _ready.clear()
