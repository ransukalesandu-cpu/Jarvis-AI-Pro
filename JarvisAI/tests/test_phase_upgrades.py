"""Focused unit tests for desktop automation safety, TTS fallback, model configuration, and search timeouts."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from actions.desktop_automation import launch_app, desktop_automation
from voice.speech_engine import SafeSpeechManager
import main


class TestPhaseUpgrades(unittest.TestCase):
    def test_launch_app_adversarial_input_rejection(self):
        """Verify that launch_app rejects adversarial command injection strings."""
        unsafe_inputs = [
            "calc & whoami",
            "notepad; calc",
            "app | dir",
            "app`id`",
            "app$PATH",
            "app\ncalc",
            "app\r\ncalc",
        ]
        for inp in unsafe_inputs:
            res = launch_app(inp)
            self.assertIn("Refused to launch application", res)
            self.assertIn("unsafe command characters", res)

    @patch("actions.desktop_automation.subprocess.Popen")
    def test_launch_app_safe_execution(self, mock_popen):
        """Verify that a safe application name is passed to launch_app without shell injection."""
        res = launch_app("calc")
        self.assertIn("Launched application: calc", res)

    def test_speech_engine_fallback_handling(self):
        """Verify that SafeSpeechManager handles _play_audio_stream gracefully."""
        manager = SafeSpeechManager()
        # Ensure _play_audio_stream executes without throwing unhandled exceptions
        try:
            manager.speak("Testing fallback TTS")
        finally:
            manager.interrupt()

    def test_live_model_configuration(self):
        """Verify that LIVE_MODEL and LIVE_FALLBACK_MODELS are correctly configured."""
        self.assertEqual(main.LIVE_MODEL, "models/gemini-3.1-flash-live-preview")
        self.assertIn("models/gemini-2.0-flash-exp", main.LIVE_FALLBACK_MODELS)
        self.assertIn("models/gemini-2.5-flash-native-audio-preview-12-2025", main.LIVE_FALLBACK_MODELS)

    @patch("actions.web_search._run_bounded")
    def test_search_timeout_configuration(self, mock_run_bounded):
        """Verify search timeouts use realistic values."""
        from actions.web_search import _news
        mock_run_bounded.return_value = "No Sri Lankan headlines"
        _news("sri lanka news")

        # Verify call timeouts passed to _run_bounded
        timeouts = [call.kwargs.get("timeout") for call in mock_run_bounded.call_args_list]
        self.assertIn(5.0, timeouts)
        self.assertIn(9.0, timeouts)


if __name__ == "__main__":
    unittest.main()
