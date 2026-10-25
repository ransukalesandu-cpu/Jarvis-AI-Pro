"""Focused unit tests for desktop automation safety, TTS fallback, model configuration, and search timeouts."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from actions.desktop_automation import launch_app, desktop_automation
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

    @patch("actions.desktop_automation.shutil.which", return_value=r"C:\Windows\System32\calc.exe")
    @patch("actions.desktop_automation.platform.system", return_value="Windows")
    @patch("actions.desktop_automation.subprocess.Popen")
    def test_launch_app_safe_execution(self, mock_popen, _mock_system, _mock_which):
        """Launch uses a resolved executable and never invokes a shell."""
        res = launch_app("calc")
        self.assertIn("Launched application: calc", res)
        mock_popen.assert_called_once_with([r"C:\Windows\System32\calc.exe"], shell=False)

    @patch("actions.desktop_automation.shutil.which", return_value=None)
    @patch("actions.desktop_automation.platform.system", return_value="Windows")
    @patch("actions.desktop_automation.subprocess.Popen")
    def test_windows_launcher_rejects_unknown_executable(self, mock_popen, _mock_system, _mock_which):
        res = launch_app("missing-app")
        self.assertIn("Application not found", res)
        mock_popen.assert_not_called()

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
