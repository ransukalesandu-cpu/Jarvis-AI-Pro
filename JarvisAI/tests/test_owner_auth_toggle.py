"""Tests for the temporary owner-authentication development switch."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from security import auth_manager


class TemporaryOwnerAuthBypassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.manager = auth_manager.AuthManager(
            vault_path=root / "pin.dat",
            state_path=root / "auth_state.json",
        )

    def test_owner_factors_are_skipped_when_switch_is_off(self):
        with mock.patch.object(auth_manager, "OWNER_AUTH_ENABLED", False):
            self.assertEqual(self.manager.get_state(), auth_manager.FULL_ACCESS_MODE)
            self.assertTrue(self.manager.is_owner_access_allowed())
            self.assertFalse(self.manager.needs_pin())
            self.assertTrue(self.manager.owner_factors_verified())
            state, message = self.manager.process_voice_authentication(b"")
            self.assertEqual(state, auth_manager.FULL_ACCESS_MODE)
            self.assertIn("temporarily disabled", message)

    def test_privacy_lock_still_blocks_during_its_cooldown(self):
        with mock.patch.object(auth_manager, "OWNER_AUTH_ENABLED", False), \
             mock.patch.object(auth_manager, "lock_workstation", return_value=True):
            self.manager.trigger_privacy_lock()
            self.assertEqual(self.manager.get_state(), auth_manager.PRIVACY_LOCK)
            self.assertTrue(self.manager.is_silent())
            self.assertFalse(self.manager.is_owner_access_allowed())


if __name__ == "__main__":
    unittest.main()
