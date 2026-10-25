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

    # 4. Face authorization disabled check
    def test_face_authorization_is_disabled(self):
        adaptive_auth = AdaptiveAuthManager(self.auth)
        self.assertFalse(face_auth.is_authorization_enabled())

        matched, score, msg = face_auth.verify_frame(np.zeros((100, 100, 3), dtype=np.uint8))
        self.assertFalse(matched)
        self.assertIn("disabled", msg.lower())

        with patch.object(face_auth, "is_enrolled", return_value=True):
            matched, score, msg = face_auth.capture_and_verify()
            self.assertFalse(matched)
            self.assertIn("disabled", msg.lower())

    # 5. Voice failure followed by PIN prompt success
    def test_voice_failure_followed_by_pin_success(self):
        adaptive_auth = AdaptiveAuthManager(self.auth)
        mock_pcm = np.ones(32000, dtype=np.int16).tobytes()

        def fake_pin_prompt():
            return "correct_pin"

        with patch.object(self.auth, "is_pin_enrolled", return_value=True), \
             patch.object(self.auth, "verify_pin", side_effect=lambda p: (self.auth.grant_owner_access("pin"), True)[1]), \
             patch.object(voice_id, "is_enrolled", return_value=True), \
             patch.object(voice_id, "verify", return_value=(False, 0.10)):
            success, method, msg = adaptive_auth.authenticate_sensitive_command(
                audio_sample=mock_pcm, pin_prompt_callback=fake_pin_prompt
            )
            self.assertTrue(success)
            self.assertEqual(method, "pin")
            self.assertTrue(self.auth.is_owner_access_allowed())

    # 6. Real turn_audio provider binding
    def test_turn_audio_provider_integration(self):
        mock_pcm = np.ones(32000, dtype=np.int16).tobytes()
        audio_called = [False]

        def audio_provider():
            audio_called[0] = True
            return mock_pcm

        security.bind(
            logger=None,
            voice_id_required=lambda: True,
            voice_id_verifier=lambda: False,
            voice_id_role=lambda: "stranger",
            turn_audio_provider=audio_provider,
            pin_prompt_callback=lambda: None,
        )

        with patch.object(security, "_auth_manager", self.auth), \
             patch.object(security, "ActionDispatcher") as mock_dispatcher, \
             patch.object(voice_id, "is_enrolled", return_value=True), \
             patch.object(voice_id, "verify", return_value=(False, 0.10)):
            mock_dispatcher.can_dispatch.return_value = (True, "OK")
            res = security.guard("file_processor", {"action": "delete"}, lambda: "Deleted")
            self.assertTrue(audio_called[0])
            self.assertIn("cannot perform", res.lower())

    # 7. PIN prompt failure/cancellation does not bypass auth
    def test_pin_prompt_cancel_fails_closed(self):
        adaptive_auth = AdaptiveAuthManager(self.auth)

        with patch.object(self.auth, "is_pin_enrolled", return_value=True), \
             patch.object(voice_id, "is_enrolled", return_value=False):
            success, method, msg = adaptive_auth.authenticate_sensitive_command(
                pin_prompt_callback=lambda: None
            )
            self.assertFalse(success)
            self.assertEqual(method, "none")
            self.assertFalse(self.auth.is_owner_access_allowed())

    # 8. Failed PIN attempts trigger Privacy Lock after 3 strikes
    def test_failed_pin_attempts_trigger_privacy_lock(self):
        if not hasattr(self.auth, "_hasher") or self.auth._hasher is None:
            from security import auth_manager
            if not auth_manager._ARGON2_AVAILABLE:
                self.skipTest("argon2-cffi not installed")

        self.auth.set_master_pin("correct123")
        self.assertFalse(self.auth.verify_pin("wrong1"))
        self.assertEqual(self.auth.failed_pin_attempts, 1)
        self.assertFalse(self.auth.verify_pin("wrong2"))
        self.assertEqual(self.auth.failed_pin_attempts, 2)
        self.assertFalse(self.auth.verify_pin("wrong3"))
        self.assertTrue(self.auth.is_privacy_lock_active())

    # 9. Successful PIN verification grants owner access in AuthManager
    def test_successful_pin_grants_owner_access(self):
        if not hasattr(self.auth, "_hasher") or self.auth._hasher is None:
            from security import auth_manager
            if not auth_manager._ARGON2_AVAILABLE:
                self.skipTest("argon2-cffi not installed")

        self.auth.set_master_pin("secret123")
        self.assertFalse(self.auth.is_owner_access_allowed())
        verified = self.auth.verify_pin("secret123")
        self.assertTrue(verified)
        self.assertTrue(self.auth.is_owner_access_allowed())
        self.assertEqual(self.auth.get_auth_method(), "pin")

    # 10. Face profile loading error preserves existing corrupt profile
    def test_face_profile_decryption_error_preserves_file(self):
        temp_face_file = Path(self.temp_dir.name) / "corrupt_face.dat"
        corrupt_content = b"INVALID_CORRUPT_ENCRYPTED_HEADER_DATA"
        temp_face_file.write_bytes(corrupt_content)

        with patch.object(face_auth, "FACE_PROFILE_FILE", temp_face_file), \
             patch.object(face_auth, "backend_ready", return_value=True), \
             patch.object(face_auth, "_extract_face_embedding", return_value=np.ones(8192, dtype=np.float32)):
            ok, msg = face_auth.enroll_frame(np.zeros((100, 100, 3), dtype=np.uint8))
            self.assertFalse(ok)
            self.assertIn("could not be decrypted", msg.lower())
            self.assertEqual(temp_face_file.read_bytes(), corrupt_content)

    # 11. Camera failure handling
    def test_camera_failure_handling(self):
        with patch.object(face_auth, "is_authorization_enabled", return_value=True), \
             patch.object(face_auth, "is_enrolled", return_value=True), \
             patch.object(face_auth, "backend_ready", return_value=True):
            with patch("cv2.VideoCapture") as mock_cap:
                mock_cap.return_value.isOpened.return_value = False
                matched, score, msg = face_auth.capture_and_verify()
                self.assertFalse(matched)
                self.assertIn("could not be opened", msg.lower())

    # 12. Ordinary commands remaining available to strangers
    def test_ordinary_commands_available_to_strangers(self):
        self.auth.set_state(RESTRICTED_MODE)
        with patch.object(security, "get_auth_manager", return_value=self.auth):
            res = security.guard("weather_report", {"location": "Colombo"}, lambda: "Sunny 30C")
            self.assertEqual(res, "Sunny 30C")

    # 13. Session authentication resetting after restart
    def test_session_authentication_resets_after_restart(self):
        self.auth.grant_owner_access("voice")
        self.assertEqual(self.auth.get_state(), FULL_ACCESS_MODE)

        # Simulate app restart
        restarted_auth = AuthManager(vault_path=self.vault_path, state_path=self.state_path)
        self.assertEqual(restarted_auth.get_state(), RESTRICTED_MODE)
        self.assertFalse(restarted_auth.is_owner_access_allowed())

    # 14. Invalid PIN length and mismatched confirmation validation
    def test_invalid_pin_length_and_mismatched_confirmation(self):
        with self.assertRaises(ValueError):
            self.auth.set_master_pin("123")  # Less than 4 chars

        with self.assertRaises(ValueError):
            self.auth.set_master_pin("a" * 65)  # More than 64 chars

    # 15. Unknown/unclassified high-impact actions default to requiring authentication
    def test_unknown_action_defaults_to_sensitive_or_dangerous(self):
        tier = security.tier_for("unknown_custom_plugin_action", {"foo": "bar"})
        self.assertIn(tier, (security.TIER_SENSITIVE, security.TIER_DANGEROUS))

    # 16. Voice similarity alone never granting owner access without anti-spoof
    def test_voice_similarity_alone_never_grants_access_without_anti_spoof(self):
        from security.voice_auth import SpeakerAuthenticator
        authenticator = SpeakerAuthenticator(anti_spoof_verifier=None)
        mock_pcm = np.ones(16000, dtype=np.int16)
        with patch.object(voice_id, "is_enabled", return_value=True), \
             patch.object(voice_id, "backend_ready", return_value=True), \
             patch.object(voice_id, "verify", return_value=(True, 0.95)):
            matched, score, verified_live = authenticator.verify(mock_pcm)
            self.assertFalse(verified_live)
            self.assertFalse(matched)

    # 17. Session authorization reuse avoids repeated prompts
    def test_session_authorization_avoids_repeated_prompts(self):
        if not hasattr(self.auth, "_hasher") or self.auth._hasher is None:
            from security import auth_manager
            if not auth_manager._ARGON2_AVAILABLE:
                self.skipTest("argon2-cffi not installed")

        self.auth.set_master_pin("correct_pin_123")
        self.assertTrue(self.auth.verify_pin("correct_pin_123"))
        self.assertTrue(self.auth.is_owner_access_allowed())

        # Second action does not ask for PIN because session is FULL_ACCESS_MODE
        adaptive_auth = AdaptiveAuthManager(self.auth)
        prompt_called = [False]
        def fake_prompt():
            prompt_called[0] = True
            return "correct_pin_123"

        success, method, msg = adaptive_auth.authenticate_sensitive_command(pin_prompt_callback=fake_prompt)
        self.assertTrue(success)
        self.assertFalse(prompt_called[0])

    # 18. Thread safety across concurrent authentication requests
    def test_concurrent_authentication_requests(self):
        import threading
        if not hasattr(self.auth, "_hasher") or self.auth._hasher is None:
            from security import auth_manager
            if not auth_manager._ARGON2_AVAILABLE:
                self.skipTest("argon2-cffi not installed")

        self.auth.set_master_pin("secure_pin_99")
        results = []

        def worker():
            res = self.auth.verify_pin("secure_pin_99")
            results.append(res)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(all(results))
        self.assertTrue(self.auth.is_owner_access_allowed())


if __name__ == "__main__":
    unittest.main()
