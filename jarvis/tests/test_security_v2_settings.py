"""Security V2 Phase 4: Security ON/OFF, baseline kept, cloud migration file (static checks only)."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from argon2 import PasswordHasher

from jarvis.actions import security_settings as act
from jarvis.core import guest_audit as ga, guest_session as gs, identity, owner_registry as reg_mod
from jarvis.core import security, security_settings as ss
from jarvis.core.guest_audit import GuestAudit
from jarvis.core.identity import IdentityManager
from jarvis.core.owner_registry import OwnerRegistry
from jarvis.core.owner_store import OwnerStore

FAST = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
ROOT = Path(__file__).resolve().parents[2]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [90_000.0]
        self.store = OwnerStore(Path(self.tmp.name) / "owner.db")
        self.reg = OwnerRegistry(self.store, hasher=FAST, clock=lambda: self.now[0])
        self.audit = GuestAudit(self.store, clock=lambda: self.now[0])
        self.cfg = ss.SecuritySettings(self.store, clock=lambda: self.now[0])
        self.mgr = IdentityManager(clock=lambda: self.now[0])
        reg_mod.reset_for_tests(self.reg); ga.reset_for_tests(self.audit)
        identity.reset_for_tests(self.mgr); ss.reset_for_tests(self.cfg); gs.reset_for_tests()
        for stop in (lambda: reg_mod.reset_for_tests(None), lambda: ga.reset_for_tests(None),
                     lambda: identity.reset_for_tests(None), lambda: ss.reset_for_tests(None), gs.reset_for_tests):
            self.addCleanup(stop)
        p = patch("jarvis.core.security.audit", lambda *a, **k: None)
        p.start(); self.addCleanup(p.stop)
        self.reg.bootstrap_first_owner("Lesandu", "first-pin")

    def owner(self, strong=False):
        self.mgr.end_session()
        self.reg.login(self.mgr, self.reg.authenticate_pin("first-pin"))
        if strong:
            self.reg.confirm_step_up(self.mgr, "first-pin")


class SwitchTests(Base):
    def test_default_on(self):
        self.assertTrue(self.cfg.monitoring_enabled())

    def test_guest_cannot_change_it(self):
        self.mgr.start_guest()
        for flag in (True, False):
            with self.assertRaises(ss.SettingsError):
                self.cfg.set_monitoring(self.mgr, flag)
        self.assertTrue(self.cfg.monitoring_enabled())

    def test_turning_off_needs_step_up_but_on_does_not(self):
        self.owner()
        self.now[0] += identity.STEP_UP_WINDOW_SECONDS + 1
        with self.assertRaises(ss.SettingsError):
            self.cfg.set_monitoring(self.mgr, False)
        self.owner(strong=True)
        self.cfg.set_monitoring(self.mgr, False)
        self.assertFalse(self.cfg.monitoring_enabled())
        self.owner()
        self.now[0] += identity.STEP_UP_WINDOW_SECONDS + 1
        self.cfg.set_monitoring(self.mgr, True)
        self.assertTrue(self.cfg.monitoring_enabled())

    def test_tool_is_owner_only_and_guest_denied_by_guard(self):
        self.mgr.start_guest()
        self.assertIn("signed-in owner", act.security_settings({"action": "off"}))
        self.assertIn("Guest Mode", security.guard("security_settings", {"action": "off"}, lambda: "ran"))
        self.assertTrue(self.cfg.monitoring_enabled())


class OffKeepsBaselineTests(Base):
    def turn_off(self):
        self.owner(strong=True)
        self.cfg.set_monitoring(self.mgr, False)
        self.mgr.end_session()

    def test_off_stops_logging_and_notice_says_so(self):
        self.turn_off()
        notice = gs.get_guest_service().start()
        self.assertIn("switched off", notice)
        security.guard("run_command", {}, lambda: "ran")
        self.assertEqual(self.audit._rows(), [])

    def test_off_still_denies_guest_everything_dangerous(self):
        self.turn_off()
        gs.get_guest_service().start()
        ran = []
        for tool in ("run_command", "files", "recall_memory", "jarvis_settings", "guest_history", "security_settings"):
            self.assertIn("Guest Mode", security.guard(tool, {}, lambda: ran.append(tool) or "ran"))
        self.assertEqual(ran, [])

    def test_off_does_not_let_a_task_password_elevate(self):
        self.turn_off()
        gs.get_guest_service().start()
        self.assertTrue(identity.verify_task_credential("site", "pw", lambda s: s == "pw").ok)
        self.assertTrue(self.mgr.guest_mode_active())

    def test_existing_entries_survive_off(self):
        gs.get_guest_service().start()
        self.assertEqual(len(self.audit._rows()), 2)
        self.turn_off()
        self.assertEqual(len(self.audit._rows()), 2)

    def test_status_lists_baseline_in_both_states(self):
        self.assertIn("Always enforced", self.cfg.status_text())
        self.turn_off()
        text = self.cfg.status_text()
        self.assertIn("OFF", text)
        for line in ss.BASELINE:
            self.assertIn(line, text)


class MigrationFileTests(unittest.TestCase):
    sql = (ROOT / "supabase/migrations/202611050001_security_v2_guest_audit.sql").read_text()

    def test_rls_and_no_client_access(self):
        self.assertIn("enable row level security", self.sql)
        self.assertRegex(self.sql, r"revoke all on public\.jarvis_guest_audit_events from anon, authenticated")
        self.assertRegex(self.sql, r"grant all on public\.jarvis_guest_audit_events to service_role")
        self.assertNotRegex(self.sql, r"grant[^;]*to\s+(anon|authenticated)")

    def test_no_free_text_or_secret_columns(self):
        cols = re.findall(r"^\s{2}(\w+)\s+(?:text|jsonb|uuid|timestamptz)", self.sql, re.M)
        self.assertTrue({"transcript", "prompt", "content", "message", "audio", "screenshot", "password",
                         "command"}.isdisjoint(cols), cols)

    def test_seven_day_expiry_and_purge(self):
        self.assertIn("interval '7 days'", self.sql)
        self.assertIn("jarvis_purge_expired_guest_audit", self.sql)
        self.assertIn("expires_at <= created_at + interval '7 days'", self.sql)

    def test_no_service_key_or_destructive_ddl(self):
        self.assertNotRegex(self.sql.lower(), r"drop table|truncate|service_role_key|eyj")


if __name__ == "__main__":
    unittest.main()
