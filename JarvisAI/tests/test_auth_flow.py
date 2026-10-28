"""Regression tests for JARVIS owner authentication, Privacy Lock and restricted actions."""
from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(BASE_DIR))

from security.auth_manager import (
    AuthManager, RESTRICTED_MODE, FULL_ACCESS_MODE, CHALLENGE_MODE, PRIVACY_LOCK,
    configured_cooldown_seconds,
)
from security.voice_auth import SpeakerAuthenticator, compute_cosine_similarity, EMBEDDING_DIM
from core.dispatcher import ActionDispatcher, TIER_1_BASIC, TIER_2_PRIVILEGED


class AuthManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.vault = root / "pin_vault.dat"
        self.state = root / "auth_state.json"
        self.manager = AuthManager(vault_path=self.vault, state_path=self.state, cooldown_seconds=60)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_has_no_default_pin(self):
        self.assertFalse(self.manager.is_pin_enrolled())
        self.assertFalse(self.manager.verify_pin("1234"))
        self.assertEqual(self.manager.get_state(), RESTRICTED_MODE)

    def test_enrolled_host_starts_without_routine_login_but_cloud_needs_voice(self):
        self.manager.set_master_pin("owner-pass-123")
        self.assertTrue(self.manager.verify_pin("owner-pass-123"))
        self.assertEqual(self.manager.get_state(), FULL_ACCESS_MODE)
        self.assertEqual(self.manager.get_auth_method(), "pin")
        restarted = AuthManager(vault_path=self.vault, state_path=self.state, cooldown_seconds=60)
        self.assertEqual(restarted.get_state(), FULL_ACCESS_MODE)
        self.assertTrue(restarted.is_owner_access_allowed())
        self.assertFalse(restarted.owner_factors_verified())

    @patch("security.auth_manager.lock_workstation", return_value=True)
    def test_three_failed_pin_attempts_trigger_persisted_privacy_lock_and_notification(self, lock_workstation):
        self.manager.set_master_pin("owner-pass-123")
        notifications = []
        self.manager.set_privacy_lock_notifier(notifications.append)
        self.assertFalse(self.manager.verify_pin("bad-1"))
        self.assertEqual(self.manager.failed_pin_attempts, 1)
        self.assertFalse(self.manager.verify_pin("bad-2"))
        self.assertEqual(self.manager.failed_pin_attempts, 2)
        self.assertFalse(self.manager.verify_pin("bad-3"))
        self.assertEqual(self.manager.get_state(), PRIVACY_LOCK)
        self.assertTrue(self.manager.requires_owner_reauthentication())
        self.assertTrue(self.state.exists())
        self.assertEqual(len(notifications), 1)
        self.assertIn("Privacy Lock", notifications[0])
        lock_workstation.assert_called_once()

        restarted = AuthManager(vault_path=self.vault, state_path=self.state, cooldown_seconds=60)
        self.assertEqual(restarted.get_state(), PRIVACY_LOCK)
        self.assertTrue(restarted.is_silent())

    @patch("security.auth_manager.lock_workstation", return_value=True)
    def test_cooldown_expiry_requires_pin_and_correct_pin_restores_access(self, _lock_workstation):
        self.manager.set_master_pin("owner-pass-123")
        self.manager.trigger_privacy_lock()
        self.manager.lock_until = time.time() - 1
        self.manager._save_persistent_state()

        self.assertEqual(self.manager.get_state(), CHALLENGE_MODE)
        self.assertTrue(self.manager.requires_owner_reauthentication())
        self.assertTrue(self.manager.needs_pin())
        self.assertTrue(self.manager.is_silent())
        self.assertTrue(self.manager.verify_pin("owner-pass-123"))
        self.assertFalse(self.manager.requires_owner_reauthentication())
        self.assertFalse(self.manager.is_silent())
        self.assertTrue(self.manager.is_owner_access_allowed())

    def test_cooldown_setting_is_limited_to_one_through_five_minutes(self):
        self.assertEqual(configured_cooldown_seconds("1"), 60)
        self.assertEqual(configured_cooldown_seconds("5"), 300)
        self.assertEqual(configured_cooldown_seconds("0"), 60)
        self.assertEqual(configured_cooldown_seconds("6"), 60)
        self.assertEqual(configured_cooldown_seconds("invalid"), 60)

    def test_voice_result_does_not_unlock_privacy_lock_or_override_pin_session(self):
        self.manager.set_master_pin("owner-pass-123")
        self.manager.grant_owner_access("pin")
        state, _ = self.manager.process_voice_result(
            is_master=False, similarity=0.0, is_live=False, is_stranger=True
        )
        self.assertEqual(state, FULL_ACCESS_MODE)
        self.manager.trigger_privacy_lock()
        state, _ = self.manager.process_voice_result(
            is_master=True, similarity=1.0, is_live=True
        )
        self.assertEqual(state, PRIVACY_LOCK)

    def test_voice_adapter_never_saves_plaintext_voice_embedding(self):
        adapter = SpeakerAuthenticator()
        with self.assertRaises(RuntimeError):
            adapter.save_master_profile(np.ones(EMBEDDING_DIM, dtype=np.float32))
        self.assertEqual(compute_cosine_similarity(np.ones(3), np.ones(3)), 1.0)

    def test_no_committed_credential_artifacts(self):
        result = subprocess.run(
            ["git", "ls-files", "JarvisAI/config/pin_vault.dat", "JarvisAI/config/auth_state.json",
             "master_voice.emb", "master_voice.emb.npy", "JarvisAI/config/master_voice.emb.npy"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.stdout.strip(), "")


class DispatcherTests(unittest.TestCase):
    def test_basic_tasks_only_in_restricted_mode(self):
        self.assertEqual(ActionDispatcher.get_action_tier("web_search"), TIER_1_BASIC)
        self.assertEqual(ActionDispatcher.get_action_tier("recall_memory"), TIER_2_PRIVILEGED)
        self.assertEqual(ActionDispatcher.get_action_tier("save_memory"), TIER_2_PRIVILEGED)
        self.assertEqual(ActionDispatcher.get_action_tier("unknown_action"), TIER_2_PRIVILEGED)
        self.assertTrue(ActionDispatcher.can_dispatch("web_search", RESTRICTED_MODE)[0])
        self.assertFalse(ActionDispatcher.can_dispatch("recall_memory", RESTRICTED_MODE)[0])
        self.assertFalse(ActionDispatcher.can_dispatch("unknown_action", CHALLENGE_MODE)[0])
        self.assertFalse(ActionDispatcher.can_dispatch("web_search", PRIVACY_LOCK)[0])


if __name__ == "__main__":
    unittest.main()
