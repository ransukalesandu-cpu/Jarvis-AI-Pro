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

from jarvis.core.routines import RoutineStore, normalize_name, validate_steps

SCHEMA_VERSION = 2
MAX_ROUTINES = 100
MAX_RULES = 100
MAX_FACTS = 300
MAX_FACT_CHARS = 500

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
CREATE TABLE IF NOT EXISTS rules (
    name TEXT PRIMARY KEY,
    source TEXT NOT NULL,              -- event source: email | schedule | file | * | any custom
    conditions TEXT NOT NULL,          -- JSON {field: text it must contain}
    action TEXT NOT NULL,              -- notify | flag | tool
    action_args TEXT NOT NULL,         -- JSON (message / tool + args)
    enabled INTEGER NOT NULL DEFAULT 1,
    created REAL NOT NULL,
    updated REAL NOT NULL,
    last_fired REAL,
    fire_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created REAL NOT NULL,
    updated REAL NOT NULL
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
        self.rules = RuleStore(self)
        self.facts = FactStore(self)

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


RULE_ACTIONS = ("notify", "flag", "tool")


def _rule_key(name: str) -> str:
    key = " ".join(str(name or "").strip().lower().split())
    if not key:
        raise ValueError("a rule needs a name")
    return key[:80]


class RuleStore:
    """Rules: when an event from `source` matches every condition, run `action`."""

    def __init__(self, store: OwnerStore):
        self._store = store

    @staticmethod
    def _row(row) -> dict:
        return {"name": row["name"], "source": row["source"],
                "conditions": json.loads(row["conditions"]), "action": row["action"],
                "action_args": json.loads(row["action_args"]), "enabled": bool(row["enabled"]),
                "last_fired": row["last_fired"], "fire_count": row["fire_count"]}

    def save(self, name: str, source: str, conditions: dict, action: str,
             action_args: dict | None = None, enabled: bool = True) -> dict:
        key = _rule_key(name)
        source = str(source or "*").strip().lower() or "*"
        action = str(action or "notify").strip().lower()
        if action not in RULE_ACTIONS:
            raise ValueError(f"action must be one of {', '.join(RULE_ACTIONS)}")
        if not isinstance(conditions, dict):
            raise ValueError("conditions must be {field: text}")
        args = dict(action_args or {})
        if action == "tool" and not str(args.get("tool") or "").strip():
            raise ValueError("a tool rule needs action_args.tool")
        now = time.time()
        with self._store.connect() as db:
            exists = db.execute("SELECT 1 FROM rules WHERE name=?", (key,)).fetchone()
            if not exists and db.execute("SELECT COUNT(*) FROM rules").fetchone()[0] >= MAX_RULES:
                raise ValueError(f"already {MAX_RULES} rules; delete one first")
            db.execute(
                "INSERT INTO rules(name, source, conditions, action, action_args, enabled, created, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET source=excluded.source, "
                "conditions=excluded.conditions, action=excluded.action, "
                "action_args=excluded.action_args, enabled=excluded.enabled, updated=excluded.updated",
                (key, source, json.dumps({str(k): str(v) for k, v in conditions.items()}),
                 action, json.dumps(args), int(bool(enabled)), now, now))
        return self.get(key)

    def get(self, name: str) -> Optional[dict]:
        with self._store.connect() as db:
            row = db.execute("SELECT * FROM rules WHERE name=?", (_rule_key(name),)).fetchone()
        return self._row(row) if row else None

    def list(self, source: str | None = None) -> list[dict]:
        with self._store.connect() as db:
            rows = db.execute("SELECT * FROM rules ORDER BY name").fetchall()
        out = [self._row(r) for r in rows]
        if source:
            out = [r for r in out if r["source"] in (source, "*", "any")]
        return out

    def delete(self, name: str) -> bool:
        with self._store.connect() as db:
            return db.execute("DELETE FROM rules WHERE name=?", (_rule_key(name),)).rowcount > 0

    def set_enabled(self, name: str, enabled: bool) -> bool:
        with self._store.connect() as db:
            return db.execute("UPDATE rules SET enabled=?, updated=? WHERE name=?",
                              (int(bool(enabled)), time.time(), _rule_key(name))).rowcount > 0

    def mark_fired(self, name: str) -> None:
        with self._store.connect() as db:
            db.execute("UPDATE rules SET last_fired=?, fire_count=fire_count+1 WHERE name=?",
                       (time.time(), _rule_key(name)))


class FactStore:
    """Short facts the owner asked JARVIS to remember, loaded every session."""

    def __init__(self, store: OwnerStore):
        self._store = store

    def remember(self, key: str, value: str) -> dict:
        k = " ".join(str(key or "").strip().split())[:120]
        v = str(value or "").strip()
        if not k or not v:
            raise ValueError("a fact needs a short name and a value")
        if len(v) > MAX_FACT_CHARS:
            raise ValueError(f"keep a fact under {MAX_FACT_CHARS} characters")
        now = time.time()
        with self._store.connect() as db:
            exists = db.execute("SELECT 1 FROM facts WHERE key=?", (k,)).fetchone()
            if not exists and db.execute("SELECT COUNT(*) FROM facts").fetchone()[0] >= MAX_FACTS:
                raise ValueError(f"already {MAX_FACTS} facts; forget one first")
            db.execute("INSERT INTO facts(key, value, created, updated) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                       (k, v, now, now))
        return {"key": k, "value": v}

    def get(self, key: str) -> Optional[str]:
        with self._store.connect() as db:
            row = db.execute("SELECT value FROM facts WHERE key=?", (key.strip(),)).fetchone()
        return row["value"] if row else None

    def list(self) -> list[dict]:
        with self._store.connect() as db:
            rows = db.execute("SELECT key, value FROM facts ORDER BY updated DESC").fetchall()
        return [{"key": r["key"], "value": r["value"]} for r in rows]

    def delete(self, key: str) -> bool:
        with self._store.connect() as db:
            return db.execute("DELETE FROM facts WHERE key=?", (key.strip(),)).rowcount > 0


def session_context(store: Optional["OwnerStore"] = None, max_chars: int = 2500) -> str:
    """Compact block for the system prompt: facts, rule names, routine names."""
    store = store or get_owner_store()
    lines = []
    facts = store.facts.list()[:40]
    if facts:
        lines.append("Facts the owner asked you to remember:")
        lines += [f"- {f['key']}: {f['value']}" for f in facts]
    rules = [r for r in store.rules.list() if r["enabled"]][:25]
    if rules:
        lines.append("Active rules (run automatically when their event happens):")
        for r in rules:
            cond = ", ".join(f"{k} contains '{v}'" for k, v in r["conditions"].items()) or "any"
            lines.append(f"- {r['name']}: on {r['source']} where {cond} -> {r['action']}")
    routines = store.routines.list()[:30]
    if routines:
        lines.append("Saved routines: " + ", ".join(r["name"] for r in routines))
    if not lines:
        return ""
    text = "[OWNER STORE]\n" + "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


_STORE: Optional[OwnerStore] = None
_STORE_LOCK = threading.Lock()


def get_owner_store() -> OwnerStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            from jarvis.core.user_data import user_data_file
            _STORE = OwnerStore(user_data_file("owner.db"))
        return _STORE


def reset_owner_store_for_tests(store: Optional[OwnerStore] = None) -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = store
