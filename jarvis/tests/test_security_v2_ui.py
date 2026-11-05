"""Security V2 Phase 5: the security panel shows only what the current identity may see."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from argon2 import PasswordHasher  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from jarvis.core import guest_audit as ga, guest_session as gs, identity, owner_registry as reg_mod  # noqa: E402
from jarvis.core import security, security_settings as ss, security_view as sv  # noqa: E402
from jarvis.core.guest_audit import GuestAudit  # noqa: E402
from jarvis.core.identity import IdentityManager  # noqa: E402
from jarvis.core.owner_registry import OwnerRegistry  # noqa: E402
from jarvis.core.owner_store import OwnerStore  # noqa: E402
from jarvis.ui.panels.guest_security_view import GuestSecurityView  # noqa: E402

FAST = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
_app = QApplication.instance() or QApplication([])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [70_000.0]
        store = OwnerStore(Path(self.tmp.name) / "owner.db")
        self.reg = OwnerRegistry(store, hasher=FAST, clock=lambda: self.now[0])
        self.audit = GuestAudit(store, clock=lambda: self.now[0])
        self.mgr = IdentityManager(clock=lambda: self.now[0])
        reg_mod.reset_for_tests(self.reg); ga.reset_for_tests(self.audit)
        identity.reset_for_tests(self.mgr); gs.reset_for_tests()
        ss.reset_for_tests(ss.SecuritySettings(store, clock=lambda: self.now[0]))
        for stop in (lambda: reg_mod.reset_for_tests(None), lambda: ga.reset_for_tests(None),
                     lambda: identity.reset_for_tests(None), lambda: ss.reset_for_tests(None), gs.reset_for_tests):
            self.addCleanup(stop)
        p = patch("jarvis.core.security.audit", lambda *a, **k: None)
        p.start(); self.addCleanup(p.stop)

    def sign_in(self, strong=False):
        self.mgr.end_session()
        self.reg.login(self.mgr, self.reg.authenticate_pin("first-pin"))
        if strong:
            self.reg.confirm_step_up(self.mgr, "first-pin")


class SnapshotTests(Base):
    def test_legacy_when_no_owners(self):
        self.assertEqual(sv.snapshot()["mode"], "legacy")

    def test_guest_sees_notice_only(self):
        self.reg.bootstrap_first_owner("Lesandu", "first-pin")
        gs.get_guest_service().start()
        security.guard("run_command", {}, lambda: "x")
        s = sv.snapshot()
        self.assertEqual(s["mode"], "guest")
        self.assertIn("Guest Mode", s["notice"])
        self.assertEqual((s["owners"], s["owner_name"], s["guest_summary"], s["can_manage"]), ([], "", "", False))

    def test_owner_sees_owners_and_guest_summary(self):
        self.reg.bootstrap_first_owner("Lesandu", "first-pin")
        gs.get_guest_service().start()
        security.guard("run_command", {}, lambda: "x")
        self.sign_in()
        s = sv.snapshot()
        self.assertEqual((s["mode"], s["owner_name"], s["can_manage"]), ("owner", "Lesandu", True))
        self.assertIn("1 blocked", s["guest_summary"])
        self.assertNotIn("pin_hash", str(s))

    def test_perform_denied_for_guest_and_signed_out(self):
        self.reg.bootstrap_first_owner("Lesandu", "first-pin")
        for start in (False, True):
            if start:
                gs.get_guest_service().start()
            self.assertIn("signed-in owner", sv.perform("monitoring", enabled=False))
            self.assertIn("signed-in owner", sv.perform("delete_latest_guest"))
        self.assertTrue(ss.get_security_settings().monitoring_enabled())

    def test_monitoring_off_needs_step_up_via_panel(self):
        self.reg.bootstrap_first_owner("Lesandu", "first-pin")
        self.sign_in()
        self.now[0] += identity.STEP_UP_WINDOW_SECONDS + 1
        self.assertIn("Not changed", sv.perform("monitoring", enabled=False))
        self.sign_in(strong=True)
        self.assertIn("OFF", sv.perform("monitoring", enabled=False))
        self.assertFalse(sv.snapshot()["monitoring"])


class WidgetTests(Base):
    def setUp(self):
        super().setUp()
        self.reg.bootstrap_first_owner("Lesandu", "first-pin")
        self.view = GuestSecurityView()
        self.addCleanup(self.view.deleteLater)

    def test_guest_sees_banner_and_no_controls(self):
        gs.get_guest_service().start()
        self.view.refresh()
        self.assertFalse(self.view._notice.isHidden())
        self.assertIn("7 days", self.view._notice.text())
        for w in (self.view._toggle, self.view._delete, self.view._owners, self.view._history):
            self.assertTrue(w.isHidden())

    def test_owner_gets_controls_and_no_banner(self):
        gs.get_guest_service().start()
        self.sign_in()
        self.view.refresh()
        self.assertTrue(self.view._notice.isHidden())
        self.assertFalse(self.view._toggle.isHidden())
        self.assertIn("Lesandu", self.view._owners.text())

    def test_delete_asks_first_and_cancel_keeps_history(self):
        gs.get_guest_service().start()
        self.sign_in()
        self.view.refresh()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.view._delete.click()
        self.assertTrue(self.audit._rows())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.view._delete.click()
        self.assertEqual(self.audit._rows(), [])

    def test_signing_out_hides_owner_controls_on_next_refresh(self):
        self.sign_in()
        self.view.refresh()
        self.assertFalse(self.view._toggle.isHidden())
        self.mgr.end_session()
        self.view.refresh()
        self.assertTrue(self.view._toggle.isHidden())


if __name__ == "__main__":
    unittest.main()
