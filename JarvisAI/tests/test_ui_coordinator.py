"""Unit tests for the headless UI adapter contract."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.ui_coordinator import HeadlessJarvisUI


class HeadlessUICoordinatorTests(unittest.TestCase):
    def test_initialization_and_state_updates(self):
        ui = HeadlessJarvisUI()
        self.assertEqual(ui.state, "INITIALIZING")
        ui.set_state("LISTENING")
        self.assertEqual(ui.state, "LISTENING")

    def test_ui_only_methods_are_safe_noops_without_graphics(self):
        ui = HeadlessJarvisUI()
        ui.set_audio_level(0.4)
        ui.react_avatar_text("hello")
        ui.push_visemes([], 0.02, 0.0)
        ui.hide_confirm()
        ui.start_camera_stream()
        ui.stop_camera_stream()
        ui.set_voice_id_enabled(True)
        ui.prompt_reconfig()
        ui.request_close()
        self.assertFalse(ui.hud_video_is_active())
        self.assertEqual(ui.prompt_pin(), None)
        self.assertTrue(ui.wait_for_api_key())

    def test_headless_confirmation_always_denies(self):
        ui = HeadlessJarvisUI()
        approval = []
        ui.show_confirm("shutdown", "Confirm shutdown", approval.append)
        self.assertEqual(approval, [False])

    def test_log_content_and_speech_are_written_to_stdout(self):
        ui = HeadlessJarvisUI()
        with patch("builtins.print") as print_mock:
            ui.write_log("test log")
            ui.show_content("test title", "test body")
            ui.request_say("hello")
            ui.notify_phone_connected()
        calls = [str(call.args[0]) for call in print_mock.call_args_list]
        self.assertIn("[CoreLog] test log", calls)
        self.assertIn("[CoreContent] test title\ntest body", calls)
        self.assertIn("[CoreSay] hello", calls)
        self.assertIn("[CoreStatus] Phone connected", calls)


if __name__ == "__main__":
    unittest.main()
