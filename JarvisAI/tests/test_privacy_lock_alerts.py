"""Tests for Privacy Lock alert payloads and opt-in Twilio delivery."""

import unittest
from unittest.mock import patch

from notifications.alert_service import build_privacy_lock_alert, send_twilio_alert


class PrivacyLockAlertTests(unittest.TestCase):
    def test_payload_is_compatible_with_dashboard_privacy_events(self):
        payload = build_privacy_lock_alert(
            180, "JARVIS Privacy Lock activated. Private access is blocked."
        )
        self.assertEqual(payload["event"], "PRIVACY_LOCK")
        self.assertEqual(payload["type"], "privacy_lock")
        self.assertEqual(payload["duration"], 180)
        self.assertEqual(payload["cooldown_remaining"], 180)
        self.assertIn("Private access is blocked", payload["text"])

    def test_duration_is_bounded(self):
        self.assertEqual(build_privacy_lock_alert(-10)["duration"], 0)
        self.assertEqual(build_privacy_lock_alert(999)["duration"], 300)

    @patch("plugins.phone_call.is_twilio_configured", return_value=True)
    @patch("plugins.phone_call.get_twilio_config", return_value={
        "account_sid": "AC-test",
        "auth_token": "not-a-real-token",
        "phone_number": "+15550000000",
        # An explicit alert recipient is intentionally absent.
    })
    def test_sms_is_not_sent_without_explicit_recipient(self, _config, _configured):
        with patch("twilio.rest.Client") as client:
            self.assertFalse(send_twilio_alert("test alert"))
            client.assert_not_called()

    @patch("plugins.phone_call.is_twilio_configured", return_value=True)
    @patch("plugins.phone_call.get_twilio_config", return_value={
        "account_sid": "AC-test",
        "auth_token": "not-a-real-token",
        "phone_number": "+15550000000",
        "alert_recipient_number": "+15550000001",
    })
    def test_sms_uses_explicit_recipient(self, _config, _configured):
        with patch("twilio.rest.Client") as client:
            self.assertTrue(send_twilio_alert("test alert"))
            client.assert_called_once_with("AC-test", "not-a-real-token")
            client.return_value.messages.create.assert_called_once_with(
                body="test alert",
                from_="+15550000000",
                to="+15550000001",
            )


if __name__ == "__main__":
    unittest.main()
