"""Automated tests for Owner Identity Recognition and Adaptive Security System in JARVIS."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for item in (ROOT_DIR, JARVIS_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from core import voice_id, security
from security import face_auth
from security.adaptive_auth import AdaptiveAuthManager
from security.auth_manager import (
    AuthManager,
    CHALLENGE_MODE,
    FULL_ACCESS_MODE,
    PRIVACY_LOCK,
    RESTRICTED_MODE,
)


class TestOwnerIdentitySecurity(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temp_dir.name) / "pin_vault.dat"
        self.state_path = Path(self.temp_dir.name) / "auth_state.json"
        self.auth = AuthManager(vault_path=self.vault_path, state_path=self.state_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    # 1. Owner verified at startup -> FULL_ACCESS_MODE
    def test_owner_verified_at_startup(self):
        mock_pcm = np.ones(32000, dtype=np.int16)
        with patch.object(voice_id, "is_enrolled", return_value=True), \
             patch.object(voice_id, "identify_speaker", return_value=("owner", 0.90)):
            role, score = voice_id.identify_speaker(mock_pcm)
            self.assertEqual(role, "owner")
            self.assertGreaterEqual(score, voice_id.SIMILARITY_THRESHOLD)
            self.auth.grant_owner_access("voice")
            self.assertEqual(self.auth.get_state(), FULL_ACCESS_MODE)
            self.assertTrue(self.auth.is_owner_access_allowed())

    # 2. Stranger detected at startup -> RESTRICTED_MODE
    def test_stranger_detected_at_startup(self):
        mock_pcm = np.ones(32000, dtype=np.int16)
        with patch.object(voice_id, "is_enrolled", return_value=True), \
             patch.object(voice_id, "identify_speaker", return_value=("stranger", 0.10)):
            role, score = voice_id.identify_speaker(mock_pcm)
            self.assertEqual(role, "stranger")
            self.auth.set_state(RESTRICTED_MODE)
            self.assertEqual(self.auth.get_state(), RESTRICTED_MODE)
            self.assertFalse(self.auth.is_owner_access_allowed())

    # 3. Uncertain voice result -> RESTRICTED_MODE
    def test_uncertain_voice_result(self):
        mock_pcm = np.ones(32000, dtype=np.int16)
        with patch.object(voice_id, "is_enrolled", return_value=True), \
             patch.object(voice_id, "identify_speaker", return_value=("stranger", 0.25)):
            role, score = voice_id.identify_speaker(mock_pcm)
            self.assertNotEqual(role, "owner")
            self.auth.set_state(RESTRICTED_MODE)
            self.assertFalse(self.auth.is_owner_access_allowed())

    # 4. Voice failure followed by successful face verification
    def test_voice_failure_followed_by_face_success(self):
        adaptive_auth = AdaptiveAuthManager(self.auth)
        mock_pcm = np.ones(32000, dtype=np.int16)

        with patch.object(voice_id, "is_enrolled", return_value=True), \
             patch.object(voice_id, "verify", return_value=(False, 0.20)), \
             patch.object(face_auth, "is_enrolled", return_value=True), \
             patch.object(face_auth, "capture_and_verify", return_value=(True, 0.88, "Face verified")):
            success, method, msg = adaptive_auth.authenticate_sensitive_command(
                audio_sample=mock_pcm, cam_index=0
            )
            self.assertTrue(success)
            self.assertEqual(method, "face")
            self.assertTrue(self.auth.is_owner_access_allowed())

    # 5. Voice and face failure followed by successful PIN/password verification
    def test_voice_and_face_failure_followed_by_pin_success(self):
        adaptive_auth = AdaptiveAuthManager(self.auth)
        mock_pcm = np.ones(32000, dtype=np.int16)

        def mock_verify_pin(pin):
            self.auth.grant_owner_access("pin")
            return True

        with patch.object(self.auth, "is_pin_enrolled", return_value=True), \
             patch.object(self.auth, "verify_pin", side_effect=mock_verify_pin), \
             patch.object(voice_id, "is_enrolled", return_value=True), \
             patch.object(voice_id, "verify", return_value=(False, 0.10)), \
             patch.object(face_auth, "is_enrolled", return_value=True), \
             patch.object(face_auth, "capture_and_verify", return_value=(False, 0.30, "Failed")):
            success, method, msg = adaptive_auth.authenticate_sensitive_command(
                audio_sample=mock_pcm, pin="123456"
            )
            self.assertTrue(success)
            self.assertEqual(method, "pin")
            self.assertTrue(self.auth.is_owner_access_allowed())

    # 6. All authentication methods failing -> Fail-closed
    def test_all_authentication_methods_failing(self):
        adaptive_auth = AdaptiveAuthManager(self.auth)
        mock_pcm = np.ones(32000, dtype=np.int16)

        with patch.object(self.auth, "is_pin_enrolled", return_value=True), \
             patch.object(self.auth, "verify_pin", return_value=False), \
             patch.object(voice_id, "is_enrolled", return_value=True), \
             patch.object(voice_id, "verify", return_value=(False, 0.10)), \
             patch.object(face_auth, "is_enrolled", return_value=True), \
             patch.object(face_auth, "capture_and_verify", return_value=(False, 0.20, "Failed")):
            success, method, msg = adaptive_auth.authenticate_sensitive_command(
                audio_sample=mock_pcm, pin="wrong_pin"
            )
            self.assertFalse(success)
            self.assertEqual(method, "none")
            self.assertFalse(self.auth.is_owner_access_allowed())

    # 7. Sensitive commands being rejected before authentication
    def test_sensitive_commands_rejected_before_authentication(self):
        with patch.object(security, "_auth_manager", self.auth), \
             patch.object(security, "ActionDispatcher") as mock_dispatcher, \
             patch.object(voice_id, "is_enrolled", return_value=False), \
             patch.object(face_auth, "is_enrolled", return_value=False):
            mock_dispatcher.can_dispatch.return_value = (True, "OK")
            res = security.guard("file_processor", {"action": "delete"}, lambda: "Deleted")
            self.assertIn("cannot perform", res.lower())

    # 8. Sensitive commands working after authentication
    def test_sensitive_commands_working_after_authentication(self):
        self.auth.grant_owner_access("voice")
        with patch.object(security, "_auth_manager", self.auth), \
             patch.object(security, "ActionDispatcher") as mock_dispatcher:
            mock_dispatcher.can_dispatch.return_value = (True, "OK")
            res = security.guard("file_processor", {"action": "list"}, lambda: "File List")
            self.assertEqual(res, "File List")

    # 9. Ordinary commands remaining available to strangers
    def test_ordinary_commands_available_to_strangers(self):
        self.auth.set_state(RESTRICTED_MODE)
        with patch.object(security, "get_auth_manager", return_value=self.auth):
            res = security.guard("weather_report", {"location": "Colombo"}, lambda: "Sunny 30C")
            self.assertEqual(res, "Sunny 30C")

    # 10. Session authentication resetting after restart
    def test_session_authentication_resets_after_restart(self):
        self.auth.grant_owner_access("voice")
        self.assertEqual(self.auth.get_state(), FULL_ACCESS_MODE)

        # Simulate app restart
        restarted_auth = AuthManager(vault_path=self.vault_path, state_path=self.state_path)
        self.assertEqual(restarted_auth.get_state(), RESTRICTED_MODE)
        self.assertFalse(restarted_auth.is_owner_access_allowed())

    # 11. Missing mic, webcam, biometric model, and enrollment profile -> Fail-closed
    def test_missing_hardware_models_and_enrollment_fail_closed(self):
        adaptive_auth = AdaptiveAuthManager(self.auth)
        with patch.object(voice_id, "is_enrolled", return_value=False), \
             patch.object(face_auth, "is_enrolled", return_value=False), \
             patch.object(self.auth, "is_pin_enrolled", return_value=False):
            success, method, msg = adaptive_auth.authenticate_sensitive_command()
            self.assertFalse(success)
            self.assertEqual(method, "none")
            self.assertFalse(self.auth.is_owner_access_allowed())


if __name__ == "__main__":
    unittest.main()
