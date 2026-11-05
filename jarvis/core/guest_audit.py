"""Minimal, transparent audit trail for Guest sessions (Security V2, Phase 3).

What is stored, in full: a random session id, an event type from a fixed list, a
permission category from a fixed list, an outcome, a timestamp, an expiry, and at
most three metadata fields (tool name, risk tier, reason code), each validated
against an allowlist. There is no free-text field, so a prompt, a password, a
command line, a file path, audio or a screenshot cannot end up here.

Retention: every row expires 7 days after it was written. This module enforces
that locally (``purge_expired`` runs at start-up and before any read); the
server-side copy and scheduled purge belong to Phase 4. Owners can delete the
latest Guest session; deletion is verified before it is reported.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from typing import Any, Optional

RETENTION_SECONDS = 7 * 24 * 3600

EVENT_TYPES = frozenset({
    "guest_session_started", "guest_session_ended", "guest_notice_shown",
    "restricted_action_attempted", "restricted_action_denied",
    "authentication_failed", "security_policy_blocked_action",
})
OUTCOMES = frozenset({"allowed", "denied", "info"})
CATEGORIES = frozenset({
    "none", "general_chat", "owner_memory", "personal_data", "secret_access", "settings_read", "settings_write",
    "voice_identity", "owner_management", "security_management", "computer_control", "file_management",
    "shell_execution", "browser_automation", "plugin_execution", "task_automation", "guest_history", "unknown",
})
REASONS = frozenset({"guest_default_deny", "not_signed_in", "wrong_credential", "locked", "session_timeout", "policy"})
TIERS = frozenset({"SAFE", "SENSITIVE", "DANGEROUS"})
_TOOL_RE = re.compile(r"^[a-z0-9_]{1,40}$")

NOTICE_OFF = ("Guest Mode. You are not signed in as the owner, so some abilities are restricted. "
              "Security monitoring is switched off, so nothing about this session is logged.")

NOTICE = (
    "Guest Mode. You are not signed in as the owner, so some abilities are restricted. "
    "JARVIS keeps a short security log of this session: when it started and ended, and which "
    "restricted actions were attempted or blocked (tool name, risk level and a reason code). "
    "It does not record what you say, passwords, keystrokes, audio or your screen. "
    "These entries are deleted automatically after 7 days."
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guest_audit_events (
    event_id TEXT PRIMARY KEY,
    guest_session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    action_category TEXT NOT NULL,
    outcome TEXT NOT NULL,
    ts REAL NOT NULL,
    expires_at REAL NOT NULL,
    safe_metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS guest_audit_session ON guest_audit_events(guest_session_id, ts);
CREATE INDEX IF NOT EXISTS guest_audit_expiry ON guest_audit_events(expires_at);
CREATE TABLE IF NOT EXISTS guest_audit_meta (key TEXT PRIMARY KEY, value REAL NOT NULL);
"""


class GuestAuditError(RuntimeError):
    pass


def clean_metadata(raw: dict[str, Any]) -> dict[str, str]:
    """Keep only allowlisted keys with allowlisted values; everything else is dropped."""
    out: dict[str, str] = {}
    tool = str(raw.get("tool", "")).strip().lower()
    if tool:
        out["tool"] = tool if _TOOL_RE.match(tool) else "other"
    tier = str(raw.get("tier", "")).strip().upper()
    if tier in TIERS:
        out["tier"] = tier
    reason = str(raw.get("reason", "")).strip().lower()
    if reason in REASONS:
        out["reason"] = reason
    return out


class GuestAudit:
    def __init__(self, store=None, clock=time.time):
        if store is None:
            from jarvis.core.owner_store import get_owner_store
            store = get_owner_store()
        store.ensure_schema(_SCHEMA)
        from jarvis.core.security_settings import SCHEMA as _SETTINGS_SCHEMA
        store.ensure_schema(_SETTINGS_SCHEMA)
        self._store = store
        self._clock = clock
        self._lock = threading.RLock()

    # ── writing ──────────────────────────────────────────────────────────────
    def record(self, session_id: str, event_type: str, category: str = "none",
               outcome: str = "info", **metadata: Any) -> Optional[str]:
        """Store one event. Unknown event types are refused; unknown categories become 'unknown'."""
        if event_type not in EVENT_TYPES:
            raise GuestAuditError(f"unknown guest event type: {event_type!r}")
        if not self.monitoring_enabled():
            return None                                   # Security OFF: nothing new is written
        category = category if category in CATEGORIES else "unknown"
        outcome = outcome if outcome in OUTCOMES else "info"
        now = self._clock()
        event_id = secrets.token_hex(8)
        with self._lock, self._store.connect() as db:
            db.execute("INSERT INTO guest_audit_events VALUES (?,?,?,?,?,?,?,?)",
                       (event_id, str(session_id)[:32], event_type, category, outcome, now,
                        now + RETENTION_SECONDS, json.dumps(clean_metadata(metadata), sort_keys=True)))
        return event_id

    def monitoring_enabled(self) -> bool:
        with self._store.connect() as db:
            row = db.execute("SELECT value FROM security_settings WHERE key='guest_monitoring'").fetchone()
        return True if row is None else row[0] == "on"

    # ── retention ────────────────────────────────────────────────────────────
    def purge_expired(self) -> int:
        with self._lock, self._store.connect() as db:
            return db.execute("DELETE FROM guest_audit_events WHERE expires_at <= ?", (self._clock(),)).rowcount

    # ── reading (callers must check for an owner session first) ──────────────
    def _rows(self, where: str = "", args: tuple = ()) -> list[dict]:
        self.purge_expired()
        with self._store.connect() as db:
            rows = db.execute(f"SELECT * FROM guest_audit_events {where} ORDER BY ts, rowid", args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["safe_metadata"] = clean_metadata(json.loads(d["safe_metadata"] or "{}"))
            out.append(d)
        return out

    def sessions(self, since: float = 0.0, limit: int = 20) -> list[dict]:
        rows = self._rows("WHERE ts > ?", (since,))
        grouped: dict[str, dict] = {}
        for r in rows:
            g = grouped.setdefault(r["guest_session_id"], {
                "session_id": r["guest_session_id"], "started": r["ts"], "ended": None,
                "events": 0, "denied": 0, "attempted": 0, "auth_failed": 0})
            g["events"] += 1
            g["denied"] += r["event_type"] in {"restricted_action_denied", "security_policy_blocked_action"}
            g["attempted"] += r["event_type"] == "restricted_action_attempted"
            g["auth_failed"] += r["event_type"] == "authentication_failed"
            if r["event_type"] == "guest_session_ended":
                g["ended"] = r["ts"]
        return sorted(grouped.values(), key=lambda g: g["started"], reverse=True)[:limit]

    def latest_session_id(self) -> Optional[str]:
        found = self.sessions(limit=1)
        return found[0]["session_id"] if found else None

    def events_for(self, session_id: str) -> list[dict]:
        return self._rows("WHERE guest_session_id=?", (str(session_id),))

    def denied_since(self, since: float = 0.0) -> list[dict]:
        return [r for r in self._rows("WHERE ts > ?", (since,))
                if r["event_type"] in {"restricted_action_denied", "security_policy_blocked_action"}]

    # ── review marker: when an owner last looked at the Guest log ────────────
    def last_review(self) -> float:
        with self._store.connect() as db:
            row = db.execute("SELECT value FROM guest_audit_meta WHERE key='last_review'").fetchone()
        return float(row[0]) if row else 0.0

    def mark_reviewed(self) -> None:
        with self._lock, self._store.connect() as db:
            db.execute("INSERT OR REPLACE INTO guest_audit_meta VALUES ('last_review', ?)", (self._clock(),))

    # ── deletion ─────────────────────────────────────────────────────────────
    def delete_session(self, session_id: str) -> int:
        """Delete one session's events and verify nothing of it remains before returning."""
        with self._lock, self._store.connect() as db:
            deleted = db.execute("DELETE FROM guest_audit_events WHERE guest_session_id=?",
                                 (str(session_id),)).rowcount
        left = self._rows("WHERE guest_session_id=?", (str(session_id),))
        if left:
            raise GuestAuditError("deletion could not be confirmed; some events remain")
        return deleted

    # ── human-readable summaries (built only from recorded events) ───────────
    @staticmethod
    def _when(ts: float) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))

    def summary_text(self, since: float = 0.0, limit: int = 5) -> str:
        found = self.sessions(since, limit)
        if not found:
            return "No Guest activity is recorded."
        lines = []
        for g in found:
            span = f"{self._when(g['started'])}" + (f" to {self._when(g['ended'])}" if g["ended"] else " (no end recorded)")
            lines.append(f"Guest session {span}: {g['denied']} blocked, {g['attempted']} attempted restricted "
                         f"actions, {g['auth_failed']} failed sign-ins.")
        return "\n".join(lines)

    def detail_text(self, session_id: str) -> str:
        rows = self.events_for(session_id)
        if not rows:
            return "No events are recorded for that session."
        out = []
        for r in rows:
            m = r["safe_metadata"]
            extra = ", ".join(f"{k}={v}" for k, v in m.items())
            out.append(f"{self._when(r['ts'])}  {r['event_type']}  [{r['action_category']}] {r['outcome']}"
                       + (f"  ({extra})" if extra else ""))
        return "\n".join(out)


_audit: Optional[GuestAudit] = None
_audit_lock = threading.Lock()


def get_guest_audit() -> GuestAudit:
    global _audit
    with _audit_lock:
        if _audit is None:
            _audit = GuestAudit()
        return _audit


def reset_for_tests(audit: Optional[GuestAudit] = None) -> None:
    global _audit
    with _audit_lock:
        _audit = audit
