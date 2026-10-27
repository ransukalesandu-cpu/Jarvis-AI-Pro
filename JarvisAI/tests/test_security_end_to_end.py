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
    def is_privacy_lock_active(self):
        return False

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

    def test_dual_factor_live_host_turn_skips_second_confirmation(self):
        self.owner.get_auth_method = mock.Mock(return_value="voice")
        self.owner.owner_factors_verified = mock.Mock(return_value=True)
        with mock.patch.object(self.security, "_untrusted_context", return_value=False), \
             mock.patch.object(self.security, "_voice_id_authorized", return_value=True), \
             mock.patch.object(self.security.confirm_gate, "request") as request:
            result = self.security.guard(
                "shutdown_jarvis", {}, lambda: "ran without a second confirmation"
            )
        self.assertEqual(result, "ran without a second confirmation")
        request.assert_not_called()

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

class LiveOwnerAuthorizationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from security.auth_manager import AuthManager
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.auth = AuthManager(vault_path=root / 'pin.dat', state_path=root / 'auth.json')
        self.audio = _variable_audio()

    def test_direct_voice_grant_and_implicit_liveness_are_rejected(self):
        from security.auth_manager import FULL_ACCESS_MODE
        with self.assertRaises(PermissionError):
            self.auth.grant_owner_access('voice')
        for live in (False, None, 1):
            with self.subTest(live=live):
                state, _ = self.auth.process_voice_result(True, .99, is_live=live)
                self.assertNotEqual(state, FULL_ACCESS_MODE)
        state, _ = self.auth.process_voice_result(True, .99)
        self.assertNotEqual(state, FULL_ACCESS_MODE)

    def test_missing_failing_or_raising_detector_uses_local_pin(self):
        from core import voice_id
        from security.voice_auth import SpeakerAuthenticator
        from security.adaptive_auth import AdaptiveAuthManager
        self.auth.set_master_pin('synthetic-local-pin')
        for detector in (None, lambda _s, _r: False,
                         lambda _s, _r: (_ for _ in ()).throw(RuntimeError('unavailable'))):
            with self.subTest(detector=detector), \
                 mock.patch.object(voice_id, 'is_enrolled', return_value=True), \
                 mock.patch.object(voice_id, 'is_enabled', return_value=True), \
                 mock.patch.object(voice_id, 'backend_ready', return_value=True), \
                 mock.patch.object(voice_id, 'verify', return_value=(True, .99)), \
                 mock.patch.object(self.auth, 'voice_authenticator', SpeakerAuthenticator(anti_spoof_verifier=detector)):
                self.auth.set_state('RESTRICTED_MODE')
                prompt = mock.Mock(return_value='synthetic-local-pin')
                success, method, _ = AdaptiveAuthManager(self.auth).authenticate_sensitive_command(
                    audio_sample=self.audio, pin_prompt_callback=prompt)
                self.assertTrue(success)
                self.assertEqual(method, 'pin')
                prompt.assert_called_once_with()

    def test_live_voice_authorizes_confirmation_but_role_or_pin_alone_does_not(self):
        from core import security, voice_id, confirm
        from security.voice_auth import SpeakerAuthenticator
        self.auth.voice_authenticator = SpeakerAuthenticator(anti_spoof_verifier=lambda _s, _r: True)
        with mock.patch.object(security, '_auth_manager', self.auth), \
             mock.patch.object(security, '_turn_audio_cb', return_value=self.audio), \
             mock.patch.object(voice_id, 'is_enabled', return_value=True), \
             mock.patch.object(voice_id, 'backend_ready', return_value=True), \
             mock.patch.object(voice_id, 'verify', return_value=(True, .99)):
            self.assertTrue(security.authorize_voice_confirmation())
            # Exercise the actual pending-confirmation gate with live verification.
            with mock.patch.object(confirm, '_pending', None), \
                 mock.patch.object(confirm, '_show_cb', mock.Mock()), \
                 mock.patch.object(confirm, '_hide_cb', mock.Mock()):
                confirm.request('sec-send_message', 'Send', '', lambda: 'sent')
                self.assertEqual(confirm.resolve_by_voice('confirm action'), 'approved')
            self.auth.voice_authenticator = SpeakerAuthenticator()
            self.assertFalse(security.authorize_voice_confirmation())
            self.auth.grant_owner_access('pin')
            self.assertFalse(security.authorize_voice_confirmation())
            self.assertTrue(self.auth.is_owner_access_allowed())

    def test_voice_session_is_revoked_when_next_speech_fails_liveness(self):
        from security.voice_auth import SpeakerAuthenticator
        self.auth.process_voice_result(True, .99, is_live=True)
        self.assertTrue(self.auth.is_owner_access_allowed())
        self.auth.voice_authenticator = SpeakerAuthenticator()
        self.auth.process_voice_authentication(self.audio)
        self.assertFalse(self.auth.is_owner_access_allowed())

    def test_guard_falls_back_to_pin_even_with_owner_role_and_similarity_callback(self):
        from core import security, voice_id
        self.auth.set_master_pin('synthetic-local-pin')
        with mock.patch.object(security, '_auth_manager', self.auth), \
             mock.patch.object(security, '_voice_id_is_required', return_value=True), \
             mock.patch.object(security, '_voice_id_role_cb', return_value='owner'), \
             mock.patch.object(security, '_voice_id_verifier_cb', return_value=True), \
             mock.patch.object(security, '_turn_audio_cb', return_value=self.audio), \
             mock.patch.object(security, '_pin_prompt_cb', return_value='synthetic-local-pin') as prompt, \
             mock.patch.object(security, '_untrusted_context', return_value=False), \
             mock.patch.object(security, '_rate_check', return_value=None), \
             mock.patch.object(security, 'audit'), \
             mock.patch.object(security.confirm_gate, 'request', return_value='pending'), \
             mock.patch.object(voice_id, 'is_enrolled', return_value=True), \
             mock.patch.object(voice_id, 'verify', return_value=(True, .99)):
            result = security.guard('file_controller', {'action': 'delete'}, lambda: self.fail('Unconfirmed action'))
        self.assertEqual(result, 'pending')
        prompt.assert_called_once_with()
        self.assertEqual(self.auth.get_auth_method(), 'pin')


if __name__ == "__main__":
    unittest.main()
