"""Server copy of the Guest audit trail: only allowlisted fields leave the PC, deletions follow."""
from __future__ import annotations

import pytest

from jarvis.core import guest_audit_sync as sync_mod
from jarvis.core.guest_audit import RETENTION_SECONDS, GuestAudit
from jarvis.core.guest_audit_sync import GuestAuditSync
from jarvis.core.owner_store import OwnerStore

ALLOWED_KEYS = {"event_id", "guest_session_id", "event_type", "action_category", "outcome", "ts", "safe_metadata"}


class FakeServer:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.down = False

    def __call__(self, payload):
        self.calls.append(payload)
        if self.down:
            raise RuntimeError("guest audit sync failed (URLError)")
        if payload["operation"] == "guest_audit_upload":
            for e in payload["events"]:
                assert set(e) == ALLOWED_KEYS
                assert set(e["safe_metadata"]) <= {"tool", "tier", "reason"}
                self.rows[e["event_id"]] = e
            return {"ok": True, "stored": [e["event_id"] for e in payload["events"]]}
        if payload["operation"] == "guest_audit_delete_session":
            self.rows = {k: v for k, v in self.rows.items() if v["guest_session_id"] != payload["guest_session_id"]}
            return {"ok": True, "deleted": True}
        raise AssertionError(payload)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    now = [100_000.0]
    store = OwnerStore(tmp_path / "owner.db")
    audit = GuestAudit(store, clock=lambda: now[0])
    server = FakeServer()
    sync = GuestAuditSync(audit, caller=server, clock=lambda: now[0])
    monkeypatch.setattr(sync_mod, "_sync", sync)
    return audit, server, sync, now


def test_uploads_only_new_minimal_events(env):
    audit, server, sync, now = env
    audit.record("sess1", "guest_session_started")
    audit.record("sess1", "restricted_action_denied", "shell_execution", "denied",
                 tool="run_command", tier="DANGEROUS", reason="guest_default_deny", command="rm -rf /")
    assert sync.sync_once() == 2
    assert len(server.rows) == 2
    denied = next(r for r in server.rows.values() if r["event_type"] == "restricted_action_denied")
    assert denied["safe_metadata"] == {"tool": "run_command", "tier": "DANGEROUS", "reason": "guest_default_deny"}
    assert sync.sync_once() == 0                       # nothing new: no duplicate upload
    audit.record("sess1", "guest_session_ended")
    assert sync.sync_once() == 1


def test_expired_events_are_never_uploaded(env):
    audit, server, sync, now = env
    audit.record("old", "guest_session_started")
    now[0] += RETENTION_SECONDS + 1
    assert sync.sync_once() == 0 and server.rows == {}


def test_offline_keeps_events_pending(env):
    audit, server, sync, now = env
    audit.record("s", "guest_session_started")
    server.down = True
    assert sync.sync_once() == 0 and "URLError" in sync.last_error
    server.down = False
    assert sync.sync_once() == 1


def test_monitoring_off_uploads_nothing(env):
    audit, server, sync, now = env
    audit.record("s", "guest_session_started")
    with audit._store.connect() as db:
        db.execute("INSERT OR REPLACE INTO security_settings VALUES ('guest_monitoring', 'off', 0)")
    assert sync.sync_once() == 0 and server.calls == []


def test_local_delete_removes_server_copy_and_queues_when_offline(env):
    audit, server, sync, now = env
    audit.record("a", "guest_session_started")
    audit.record("b", "guest_session_started")
    sync.sync_once()
    audit.delete_session("a")
    assert {r["guest_session_id"] for r in server.rows.values()} == {"b"}
    server.down = True
    audit.delete_session("b")
    assert {r["guest_session_id"] for r in server.rows.values()} == {"b"}      # queued
    server.down = False
    sync.sync_once()
    assert server.rows == {}


def test_disabled_without_supabase_or_by_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert sync_mod.sync_enabled() is False
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("JARVIS_GUEST_AUDIT_SYNC", "0")
    assert sync_mod.sync_enabled() is False


def test_no_sync_object_means_local_delete_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_mod, "_sync", None)
    audit = GuestAudit(OwnerStore(tmp_path / "o.db"), clock=lambda: 10.0)
    audit.record("x", "guest_session_started")
    assert audit.delete_session("x") == 1
