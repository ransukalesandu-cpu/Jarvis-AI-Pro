"""
Unit tests for 3-Strike Privacy Lockout, Windows Native LockWorkStation,
Clamped Timer, and Multi-Device Emergency Alerts.
"""

import unittest
from unittest.mock import MagicMock, patch

from security.auth_manager import (
    AuthManager, get_auth_manager, STATE_NORMAL, STATE_PRIVACY_LOCK, STATE_RESTRICTED_MODE
)
from security.lockdown import (
    clamp_duration, trigger_privacy_lock, clear_privacy_lock, set_lock_workstation_mock,
    register_silencing_hooks, is_privacy_locked
)
from memory.config_manager import (
    get_privacy_lock_duration_seconds, save_privacy_lock_duration_seconds
)
from notifications.alert_service import (
    dispatch_privacy_lock_alert, register_websocket_broadcast_callback
)
from core.dispatcher import ActionDispatcher


class TestLockdownSequence(unittest.TestCase):

    def setUp(self):
        self.auth_mgr = AuthManager()
        self.auth_mgr.reset_attempts()
        self.auth_mgr.set_state(STATE_NORMAL)
        self.auth_mgr.set_pin("1234")

    def test_three_strikes_trigger_lockdown(self):
        """Verify exactly 3 incorrect PIN entries trigger the lockdown sequence."""
        self.auth_mgr.verify_pin("9999")  # Attempt 1
        self.assertEqual(self.auth_mgr.failed_pin_attempts, 1)
        self.assertEqual(self.auth_mgr.get_state(), STATE_NORMAL)

        self.auth_mgr.verify_pin("8888")  # Attempt 2
        self.assertEqual(self.auth_mgr.failed_pin_attempts, 2)
        self.assertEqual(self.auth_mgr.get_state(), STATE_NORMAL)

        # Attempt 3 -> triggers PRIVACY_LOCK
        self.auth_mgr.verify_pin("7777")
        self.assertEqual(self.auth_mgr.failed_pin_attempts, 3)
        self.assertEqual(self.auth_mgr.get_state(), STATE_PRIVACY_LOCK)
        self.assertTrue(self.auth_mgr.is_locked())

    def test_lock_workstation_invoked_on_third_failed_attempt(self):
        """Verify LockWorkStation mock is invoked on the 3rd failed attempt."""
        lock_mock = MagicMock()
        set_lock_workstation_mock(lock_mock)

        self.auth_mgr.verify_pin("0000")
        self.auth_mgr.verify_pin("0000")
        self.assertFalse(lock_mock.called)

        self.auth_mgr.verify_pin("0000")
        self.assertTrue(lock_mock.called)

        # Clean up mock
        set_lock_workstation_mock(None)

    def test_duration_clamping(self):
        """Verify duration clamping: <60s clamps to 60s, >300s clamps to 300s."""
        self.assertEqual(clamp_duration(10), 60)
        self.assertEqual(clamp_duration(50), 60)
        self.assertEqual(clamp_duration(180), 180)
        self.assertEqual(clamp_duration(300), 300)
        self.assertEqual(clamp_duration(500), 300)
        self.assertEqual(clamp_duration(9999), 300)

    def test_commands_and_wake_words_ignored_while_locked(self):
        """Verify commands and dispatchers are blocked in PRIVACY_LOCK state."""
        self.auth_mgr.set_state(STATE_PRIVACY_LOCK)

        dispatcher = ActionDispatcher()
        allowed, reason = dispatcher.can_execute("open_app", user_role="owner")
        self.assertFalse(allowed)
        self.assertIn("PRIVACY_LOCK", reason)

        with self.assertRaises(PermissionError):
            dispatcher.dispatch("open_app", {}, lambda: "executed", user_role="owner")

    def test_alert_dispatcher_triggers_twilio_and_websocket(self):
        """Verify alert dispatcher triggers Twilio SMS and WebSocket notification payloads."""
        ws_mock = MagicMock()
        register_websocket_broadcast_callback(ws_mock)

        with patch("notifications.alert_service.send_twilio_alert") as twilio_mock:
            twilio_mock.return_value = True
            payload = dispatch_privacy_lock_alert(180)

            self.assertEqual(payload["event"], "PRIVACY_LOCK")
            self.assertEqual(payload["duration"], 180)
            self.assertIn("180 seconds", payload["message"])

            twilio_mock.assert_called_once()
            self.assertIn("180 seconds", twilio_mock.call_args[0][0])
            ws_mock.assert_called_once_with(payload)

    def test_lockdown_expiration_resets_attempts_and_restores_mic(self):
        """Verify expiration resets attempts to 0 and restores mic in RESTRICTED_MODE."""
        mic_restore_mock = MagicMock()
        register_silencing_hooks(mic_restore=mic_restore_mock)

        self.auth_mgr.record_failed_attempt()
        self.auth_mgr.record_failed_attempt()
        self.auth_mgr.record_failed_attempt()
        self.assertEqual(self.auth_mgr.get_state(), STATE_PRIVACY_LOCK)
        self.assertEqual(self.auth_mgr.failed_pin_attempts, 3)

        # Explicitly clear privacy lock (as timer expiration worker does)
        clear_privacy_lock()

        self.assertEqual(self.auth_mgr.failed_pin_attempts, 0)
        self.assertEqual(self.auth_mgr.get_state(), STATE_RESTRICTED_MODE)
        mic_restore_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
