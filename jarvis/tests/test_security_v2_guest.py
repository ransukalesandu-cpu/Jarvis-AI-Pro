"""Security V2 Phase 3: Guest Mode, minimal audit, owner-only history, 7-day expiry."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from argon2 import PasswordHasher

from jarvis.actions import guest_history as gh
from jarvis.core import guest_audit as ga, guest_session as gs, identity, owner_registry as reg_mod
from jarvis.core import security
from jarvis.core.guest_audit import GuestAudit, GuestAuditError, RETENTION_SECONDS
from jarvis.core.identity import IdentityManager
from jarvis.core.owner_registry import OwnerRegistry
from jarvis.core.owner_store import OwnerStore

FAST = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [50_000.0]
        self.store = OwnerStore(Path(self.tmp.name) / "owner.db")
        self.reg = OwnerRegistry(self.store, hasher=FAST, clock=lambda: self.now[0])
        self.audit = GuestAudit(self.store, clock=lambda: self.now[0])
        self.mgr = IdentityManager(clock=lambda: self.now[0])
        reg_mod.reset_for_tests(self.reg)
        ga.reset_for_tests(self.audit)
        identity.reset_for_tests(self.mgr)
        gs.reset_for_tests()
        for stop in (lambda: reg_mod.reset_for_tests(None), lambda: ga.reset_for_tests(None),
                     lambda: identity.reset_for_tests(None), gs.reset_for_tests):
            self.addCleanup(stop)
        p = patch("jarvis.core.security.audit", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        self.svc = gs.get_guest_service()

    def boot(self):
        return self.reg.bootstrap_first_owner("Lesandu", "first-pin")


class StartTests(Base):
    def test_no_guest_mode_without_owners(self):
        self.assertIsNone(self.svc.start())
        self.assertFalse(self.mgr.guest_mode_active())

    def test_guest_starts_with_visible_notice_and_audit(self):
        self.boot()
        notice = self.svc.start()
        self.assertIn("Guest Mode", notice)
        self.assertIn("7 days", notice)
        self.assertTrue(self.mgr.guest_mode_active())
        types = [e["event_type"] for e in self.audit._rows()]
        self.assertEqual(types, ["guest_session_started", "guest_notice_shown"])

    def test_notice_states_what_is_not_recorded(self):
        for word in ("does not record", "passwords", "keystrokes", "audio", "screen"):
            self.assertIn(word, ga.NOTICE)


class IsolationTests(Base):
    def setUp(self):
        super().setUp()
        self.boot()
        self.svc.start()

    def test_guard_denies_dangerous_and_owner_data_tools_and_records_it(self):
        ran = []
        for tool in ("run_command", "files", "recall_memory", "jarvis_settings", "guest_history"):
            out = security.guard(tool, {}, lambda: ran.append(tool) or "ran")
            self.assertIn("Guest Mode", out)
        self.assertEqual(ran, [])
        events = [e for e in self.audit._rows() if e["event_type"] == "restricted_action_denied"]
        self.assertEqual({e["safe_metadata"]["tool"] for e in events},
                         {"run_command", "files", "recall_memory", "jarvis_settings", "guest_history"})

    def test_allowlisted_safe_tool_still_works(self):
        # weather_report passes both the Guest allowlist and the older restricted-mode gate
        # (which is stricter still for battery_status), so Guest never gets more than before.
        self.assertEqual(security.guard("weather_report", {}, lambda: "ok"), "ok")

    def test_guest_cannot_read_history_even_by_calling_handler(self):
        self.audit.record("s1", "restricted_action_denied", "shell_execution", "denied", tool="run_command")
        self.assertEqual(gh.guest_history({"action": "summary"}), gh._DENY)
        self.assertEqual(gh.guest_history({"action": "delete_latest", "confirm": True}), gh._DENY)
        self.assertEqual(len(self.audit._rows("WHERE guest_session_id='s1'")), 1)


class PasswordSeparationTests(Base):
    """A guest/task/website password must never make someone an owner."""
    def setUp(self):
        super().setUp()
        self.boot()
        self.svc.start()

    def test_wrong_pin_stays_guest_and_is_logged_without_the_value(self):
        ok, _ = self.svc.owner_login_pin("netflix-password-123")
        self.assertFalse(ok)
        self.assertTrue(self.mgr.guest_mode_active())
        blob = json.dumps(self.audit._rows())
        self.assertNotIn("netflix-password-123", blob)
        self.assertIn("authentication_failed", blob)

    def test_task_credential_success_does_not_change_identity(self):
        before = self.mgr.current()
        res = identity.verify_task_credential("netflix", "hunter2", lambda s: s == "hunter2")
        self.assertTrue(res.ok)
        self.assertEqual(self.mgr.current(), before)
        self.assertTrue(self.mgr.guest_mode_active())
        self.assertIn("Guest Mode", security.guard("run_command", {}, lambda: "ran"))

    def test_typed_text_is_not_a_credential_unless_requested(self):
        self.assertIsNone(self.svc.handle_typed_text("what's the weather", False))
        self.assertIsNone(self.svc.handle_typed_text("first-pin", False))      # plain text never logs in
        self.assertTrue(self.mgr.guest_mode_active())

    def test_slash_owner_and_legacy_prompt_both_use_the_registry(self):
        self.assertEqual(self.svc.handle_typed_text("/owner nope", False)[0], False)
        self.assertEqual(self.svc.handle_typed_text("nope", True)[0], False)
        ok, _ = self.svc.handle_typed_text("/owner first-pin", False)
        self.assertTrue(ok)
        self.assertFalse(self.mgr.guest_mode_active())
        self.assertEqual(self.mgr.current().role, identity.ROLE_OWNER)

    def test_no_typed_interception_outside_guest_mode(self):
        self.mgr.end_session()
        self.assertIsNone(self.svc.handle_typed_text("/owner first-pin", False))


class AuditContentTests(Base):
    def test_metadata_is_allowlisted_and_free_text_is_dropped(self):
        self.audit.record("s", "restricted_action_denied", "shell_execution", "denied",
                          tool="run_command", tier="DANGEROUS", reason="guest_default_deny",
                          command="rm -rf /", password="p@ss", transcript="private words", path="C:/secret")
        row = self.audit._rows()[0]
        self.assertEqual(set(row["safe_metadata"]), {"tool", "tier", "reason"})
        blob = json.dumps(row)
        for leaked in ("rm -rf", "p@ss", "private words", "C:/secret"):
            self.assertNotIn(leaked, blob)

    def test_odd_tool_names_and_values_are_neutralised(self):
        self.audit.record("s", "restricted_action_denied", "bogus", tool="C:\\x y", tier="weird", reason="free text")
        row = self.audit._rows()[0]
        self.assertEqual(row["safe_metadata"], {"tool": "other"})
        self.assertEqual(row["action_category"], "unknown")

    def test_unknown_event_type_refused(self):
        with self.assertRaises(GuestAuditError):
            self.audit.record("s", "keystroke_logged")

    def test_schema_has_no_free_text_columns(self):
        with self.store.connect() as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(guest_audit_events)")}
        self.assertTrue(cols.isdisjoint({"transcript", "prompt", "content", "message", "audio", "screenshot", "password"}))


class RetentionAndDeletionTests(Base):
    def test_rows_expire_after_seven_days(self):
        self.audit.record("old", "guest_session_started")
        self.now[0] += RETENTION_SECONDS - 1
        self.assertEqual(len(self.audit._rows()), 1)
        self.now[0] += 2
        self.assertEqual(self.audit._rows(), [])

    def test_purge_expired_removes_only_expired(self):
        self.audit.record("old", "guest_session_started")
        self.now[0] += RETENTION_SECONDS + 5
        self.audit.record("new", "guest_session_started")
        self.assertEqual(self.audit.purge_expired(), 1)
        self.assertEqual({r["guest_session_id"] for r in self.audit._rows()}, {"new"})

    def test_delete_latest_deletes_only_latest_and_verifies(self):
        self.audit.record("a", "guest_session_started")
        self.now[0] += 10
        self.audit.record("b", "guest_session_started")
        self.audit.record("b", "restricted_action_denied", "shell_execution", "denied", tool="run_command")
        self.assertEqual(self.audit.latest_session_id(), "b")
        self.assertEqual(self.audit.delete_session("b"), 2)
        self.assertEqual({r["guest_session_id"] for r in self.audit._rows()}, {"a"})


class OwnerViewTests(Base):
    def setUp(self):
        super().setUp()
        self.boot()
        self.svc.start()
        security.guard("run_command", {}, lambda: "ran")
        security.guard("files", {}, lambda: "ran")
        self.svc.owner_login_pin("zzz-bad-pin")

    def owner_in(self):
        ok, summary = self.svc.owner_login_pin("first-pin")
        self.assertTrue(ok)
        return summary

    def test_login_summary_reports_blocked_attempts_once(self):
        summary = self.owner_in()
        self.assertIn("Guest activity", summary)
        self.assertIn("2 blocked", summary)
        self.assertIn("1 failed", summary)
        self.assertEqual(self.svc.login_summary(), "")           # already reviewed

    def test_owner_can_read_and_delete_latest(self):
        self.owner_in()
        self.assertIn("run_command", gh.guest_history({"action": "latest"}))
        self.assertIn("confirmation", gh.guest_history({"action": "delete_latest"}))
        self.assertIn("Deleted", gh.guest_history({"action": "delete_latest", "confirm": True}))
        self.assertEqual(gh.guest_history({"action": "summary"}), "No Guest activity is recorded.")

    def test_history_never_contains_conversation_content(self):
        self.owner_in()
        text = gh.guest_history({"action": "latest"})
        self.assertNotIn("first-pin", text)
        self.assertNotIn("zzz-bad-pin", text)


class WiringTests(unittest.TestCase):
    def test_tool_registered_with_tier_and_category(self):
        self.assertEqual(security.tier_for("guest_history", {}), security.TIER_DANGEROUS)
        self.assertEqual(identity.category_for("guest_history"), "guest_history")
        self.assertNotIn("guest_history", identity.GUEST_ALLOWED_TOOLS)
        self.assertEqual(gh.TOOL["name"], "guest_history")


if __name__ == "__main__":
    unittest.main()
