"""Tests for the user-confirmed Supabase personal-memory setting and action policy."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from actions import jarvis_settings
from core.security import TIER_DANGEROUS, TIER_SENSITIVE, tier_for


class PersonalCloudMemorySettingsTests(unittest.TestCase):
    def test_enabling_requires_confirmation_and_server_consent_before_local_enable(self):
        getter = Mock(return_value=False)
        setter = Mock()
        consent = Mock()
        with patch.dict(jarvis_settings._BOOL_SETTINGS, {
            "personal_cloud_memory": (
                getter, setter, "Personal profile memory."
            )
        }), patch.object(
            jarvis_settings.confirm_gate,
            "request",
            side_effect=lambda **kwargs: kwargs["run"](),
        ) as confirm, patch(
            "core.personal_cloud_memory.set_cloud_personal_memory_consent",
            consent,
        ):
            result = jarvis_settings._set_setting("personal_cloud_memory", "on")

        confirm.assert_called_once()
        consent.assert_called_once_with(True)
        setter.assert_called_once_with(True)
        self.assertIn("Enabled personal cloud memory", result)

    def test_failed_server_consent_never_enables_local_capture(self):
        getter = Mock(return_value=False)
        setter = Mock()
        with patch.dict(jarvis_settings._BOOL_SETTINGS, {
            "personal_cloud_memory": (
                getter, setter, "Personal profile memory."
            )
        }), patch.object(
            jarvis_settings.confirm_gate,
            "request",
            side_effect=lambda **kwargs: kwargs["run"](),
        ), patch(
            "core.personal_cloud_memory.set_cloud_personal_memory_consent",
            side_effect=RuntimeError("connection unavailable"),
        ):
            result = jarvis_settings._set_setting("personal_cloud_memory", "on")

        setter.assert_not_called()
        self.assertIn("was not enabled", result)
        self.assertIn("No profile facts were uploaded", result)

    def test_local_capture_stays_disabled_if_cloud_cannot_be_reached_during_disable(self):
        getter = Mock(return_value=True)
        setter = Mock()
        with patch.dict(jarvis_settings._BOOL_SETTINGS, {
            "personal_cloud_memory": (
                getter, setter, "Personal profile memory."
            )
        }), patch(
            "core.personal_cloud_memory.set_cloud_personal_memory_consent",
            side_effect=RuntimeError("offline"),
        ):
            result = jarvis_settings._set_setting("personal_cloud_memory", "off")

        setter.assert_called_once_with(False)
        self.assertIn("Disabled personal cloud memory on this device", result)
        self.assertIn("may remain stored", result)

    def test_deletion_requires_confirmation_while_reading_is_sensitive(self):
        self.assertEqual(tier_for("personal_memory", {"operation": "list"}), TIER_SENSITIVE)
        self.assertEqual(tier_for("personal_memory", {"operation": "forget"}), TIER_DANGEROUS)
        self.assertEqual(tier_for("personal_memory", {"operation": "clear"}), TIER_DANGEROUS)


if __name__ == "__main__":
    unittest.main()
