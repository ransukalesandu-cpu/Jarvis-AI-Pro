"""Server-side copy of the Guest audit trail (Security V2, Phase 4 follow-up).

Uploads the minimal, allowlisted Guest events from the local ``owner.db`` to the
``jarvis-guest-audit`` Edge Function, which is the only writer of
``public.jarvis_guest_audit_events`` (7-day expiry, hourly pg_cron purge).

* Runs only when Supabase is configured with a stable signed-in identity in the OS
  credential vault (the same requirement as personal cloud memory) and Guest
  monitoring is ON. ``JARVIS_GUEST_AUDIT_SYNC=0`` turns it off.
* Only the fields the server accepts are sent: event id, session id, event type,
  category, outcome, timestamp and the cleaned tool/tier/reason metadata.
* When an owner deletes a Guest session locally, the server copy is deleted too;
  if the cloud is unreachable the deletion is queued and retried.
* The service-role key never leaves the Edge Function.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

FUNCTION = "jarvis-guest-audit"
BATCH = 100
INTERVAL_S = 600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guest_audit_synced (event_id TEXT PRIMARY KEY, synced_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS guest_audit_pending_delete (guest_session_id TEXT PRIMARY KEY, queued_at REAL NOT NULL);
"""

Caller = Callable[[dict[str, Any]], dict[str, Any]]


def sync_enabled() -> bool:
    if os.environ.get("JARVIS_GUEST_AUDIT_SYNC", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    try:
        from jarvis.core import privacy
        if privacy.offline_enabled():
            return False
    except Exception:
        return False
    return bool(os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_ANON_KEY", "").strip())


def call_function(payload: dict[str, Any], *, timeout: float = 10.0) -> dict[str, Any]:
    """POST to the user-scoped Edge Function with the signed-in user's token and a fresh nonce."""
    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    public_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not base_url or not public_key:
        raise RuntimeError("Supabase is not configured")
    from jarvis.core.supabase_cloud_provider import _get_access_token, has_persistent_auth_session

    access_token = _get_access_token(base_url, public_key, timeout)
    if not has_persistent_auth_session():
        raise RuntimeError("guest audit sync needs a stable Supabase identity in the credential vault")
    request = urllib.request.Request(
        f"{base_url}/functions/v1/{FUNCTION}",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json", "apikey": public_key, "Authorization": "Bearer " + access_token,
            "X-Jarvis-Host-Timestamp": str(int(time.time())), "X-Jarvis-Host-Nonce": secrets.token_urlsafe(24),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured https Supabase URL
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"guest audit sync failed with HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"guest audit sync failed ({type(exc).__name__})") from None
    if not isinstance(decoded, dict) or decoded.get("ok") is not True:
        err = str(decoded.get("error") or "invalid_response")[:80] if isinstance(decoded, dict) else "invalid_response"
        raise RuntimeError(f"guest audit sync failed ({err})")
    return decoded


class GuestAuditSync:
    def __init__(self, audit=None, caller: Optional[Caller] = None, clock: Callable[[], float] = time.time) -> None:
        if audit is None:
            from jarvis.core.guest_audit import get_guest_audit
            audit = get_guest_audit()
        self._audit = audit
        self._store = audit._store
        self._store.ensure_schema(_SCHEMA)
        self._call = caller or call_function
        self._clock = clock
        self._lock = threading.Lock()
        self.last_error = ""

    def pending(self, limit: int = BATCH) -> list[dict]:
        now = self._clock()
        with self._store.connect() as db:
            rows = db.execute(
                "SELECT e.* FROM guest_audit_events e LEFT JOIN guest_audit_synced s ON s.event_id = e.event_id "
                "WHERE s.event_id IS NULL AND e.expires_at > ? ORDER BY e.ts LIMIT ?", (now, limit)).fetchall()
        from jarvis.core.guest_audit import clean_metadata
        return [{"event_id": r["event_id"], "guest_session_id": r["guest_session_id"], "event_type": r["event_type"],
                 "action_category": r["action_category"], "outcome": r["outcome"], "ts": float(r["ts"]),
                 "safe_metadata": clean_metadata(json.loads(r["safe_metadata"] or "{}"))} for r in rows]

    def queue_delete(self, session_id: str) -> None:
        with self._store.connect() as db:
            db.execute("INSERT OR REPLACE INTO guest_audit_pending_delete VALUES (?, ?)", (str(session_id)[:32], self._clock()))

    def delete_remote(self, session_id: str) -> bool:
        """Delete the server copy now; queue it for later when the cloud is unreachable."""
        self.queue_delete(session_id)
        return self._flush_deletes() >= 1

    def _flush_deletes(self) -> int:
        with self._store.connect() as db:
            ids = [r[0] for r in db.execute("SELECT guest_session_id FROM guest_audit_pending_delete").fetchall()]
        done = 0
        for sid in ids:
            try:
                self._call({"operation": "guest_audit_delete_session", "guest_session_id": sid})
            except RuntimeError as e:
                self.last_error = str(e)
                break
            with self._store.connect() as db:
                db.execute("DELETE FROM guest_audit_pending_delete WHERE guest_session_id=?", (sid,))
                db.execute("DELETE FROM guest_audit_synced WHERE event_id NOT IN (SELECT event_id FROM guest_audit_events)")
            done += 1
        return done

    def sync_once(self) -> int:
        """Upload pending events (and pending deletions). Returns how many events were stored."""
        with self._lock:
            if not self._audit.monitoring_enabled():
                return 0
            self._flush_deletes()
            uploaded = 0
            while True:
                batch = self.pending()
                if not batch:
                    break
                try:
                    result = self._call({"operation": "guest_audit_upload", "events": batch})
                except RuntimeError as e:
                    self.last_error = str(e)
                    break
                stored = {str(x) for x in result.get("stored", [])} & {e["event_id"] for e in batch}
                if not stored:
                    break
                now = self._clock()
                with self._store.connect() as db:
                    db.executemany("INSERT OR IGNORE INTO guest_audit_synced VALUES (?, ?)", [(i, now) for i in stored])
                    db.execute("DELETE FROM guest_audit_synced WHERE event_id NOT IN (SELECT event_id FROM guest_audit_events)")
                uploaded += len(stored)
                if len(batch) < BATCH:
                    break
            if uploaded:
                self.last_error = ""
            return uploaded


_sync: Optional[GuestAuditSync] = None
_thread: Optional[threading.Thread] = None


def get_sync() -> Optional[GuestAuditSync]:
    return _sync


def start_background_sync() -> Optional[GuestAuditSync]:
    """Called once from JarvisLive. No-op unless Supabase is configured and sync is enabled."""
    global _sync, _thread
    if _thread is not None or not sync_enabled():
        return _sync
    _sync = GuestAuditSync()
    stop = threading.Event()

    def loop():
        while True:
            try:
                _sync.sync_once()
            except Exception as e:
                _sync.last_error = type(e).__name__
            if stop.wait(INTERVAL_S):
                return

    _thread = threading.Thread(target=loop, name="guest-audit-sync", daemon=True)
    _thread.start()
    return _sync


def on_local_delete(session_id: str) -> None:
    """Hook from GuestAudit.delete_session: remove the server copy too (fail-soft, queued)."""
    s = _sync
    if s is None:
        return
    try:
        s.delete_remote(session_id)
    except Exception as e:
        s.last_error = type(e).__name__
