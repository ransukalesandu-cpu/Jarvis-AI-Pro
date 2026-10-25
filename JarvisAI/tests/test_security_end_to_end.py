"""Regression tests for owner voice anti-spoof fail-closed behavior and action gates."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _variable_audio(sample_rate: int = 16000) -> np.ndarray:
    t = np.arange(sample_rate, dtype=np.float32) / sample_rate
    envelope = 0.2 + 0.15 * np.sin(2 * np.pi * 2 * t)
    return (envelope * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


class VoiceAntiSpoofTests(unittest.TestCase):
    def test_quality_heuristic_is_not_sufficient_to_authenticate(self):
        from security.voice_auth import SpeakerAuthenticator

        auth = SpeakerAuthenticator()
        quality_ok, message = auth.check_liveness(_variable_audio())
        self.assertTrue(quality_ok)
        self.assertIn("liveness is unverified", message)
        self.assertEqual(auth.verify(_variable_audio()), (False, 0.0, False))

    def test_missing_or_failing_anti_spoof_detector_fails_closed(self):
        from security.voice_auth import SpeakerAuthenticator

        for detector in (None, lambda _samples, _rate: False,
                         lambda _samples, _rate: (_ for _ in ()).throw(RuntimeError("detector failed"))):
            with self.subTest(detector=detector):
                auth = SpeakerAuthenticator(anti_spoof_verifier=detector)
                self.assertEqual(auth.verify(_variable_audio()), (False, 0.0, False))

    def test_detector_must_return_literal_true(self):
        from security.voice_auth import SpeakerAuthenticator

        auth = SpeakerAuthenticator(anti_spoof_verifier=lambda _samples, _rate: 1)
        self.assertEqual(auth.verify(_variable_audio()), (False, 0.0, False))

    def test_owner_match_requires_both_detector_and_encrypted_voice_id(self):
        from security.voice_auth import SpeakerAuthenticator
        from core import voice_id

        auth = SpeakerAuthenticator(anti_spoof_verifier=lambda samples, rate: rate == 16000 and len(samples) > 0)
        with mock.patch.object(voice_id, "is_enabled", return_value=True), \
             mock.patch.object(voice_id, "backend_ready", return_value=True), \
             mock.patch.object(voice_id, "verify", return_value=(True, 0.91)):
            self.assertEqual(auth.verify(_variable_audio()), (True, 0.91, True))


class _OwnerSession:
    def get_state(self):
        from core.security import FULL_ACCESS_MODE
        return FULL_ACCESS_MODE

    def is_silent(self):
        return False

    def is_owner_access_allowed(self):
        return True

    def get_auth_method(self):
        return "pin"

    def requires_owner_reauthentication(self):
        return False


DANGEROUS_CALLS = (
    ("file_controller", {"action": "delete", "path": "/tmp/example.txt"}),
    ("code_helper", {"action": "run", "command": "python generated.py"}),
    ("shutdown_jarvis", {}),
    ("send_message", {"action": "send", "recipient": "test", "message": "hello"}),
    ("email_gmail", {"action": "send", "to": "test@example.invalid", "message": "hello"}),
)


class DangerousActionGateTests(unittest.TestCase):
    def setUp(self):
        from core import security
        self.security = security
        self.owner = _OwnerSession()
        self.patches = [
            mock.patch.object(security, "_auth_manager", self.owner),
            mock.patch.object(security.ActionDispatcher, "can_dispatch", return_value=(True, "")),
            mock.patch.object(security, "_voice_id_is_required", return_value=False),
            mock.patch.object(security, "_rate_check", return_value=None),
            mock.patch.object(security, "audit"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_dangerous_actions_wait_for_explicit_confirmation(self):
        for name, params in DANGEROUS_CALLS:
            with self.subTest(action=name):
                executed = []
                with mock.patch.object(
                    self.security.confirm_gate, "request",
                    return_value="[CONFIRMATION_PENDING]",
                ) as request:
                    result = self.security.guard(name, params, lambda: executed.append(name) or "ran")
                self.assertEqual(result, "[CONFIRMATION_PENDING]")
                self.assertEqual(executed, [], "side effect ran before approval")
                request.assert_called_once()
                self.assertEqual(request.call_args.kwargs["key"], f"sec-{name}")
                self.assertTrue(callable(request.call_args.kwargs["run"]))

    def test_untrusted_external_content_cannot_trigger_dangerous_actions(self):
        for name, params in DANGEROUS_CALLS:
            with self.subTest(action=name):
                executed = []
                with mock.patch.object(self.security, "_untrusted_context", return_value=True), \
                     mock.patch.object(self.security.confirm_gate, "request") as request:
                    result = self.security.guard(name, params, lambda: executed.append(name) or "ran")
                self.assertIn("rather than from you directly", result)
                self.assertEqual(executed, [])
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
