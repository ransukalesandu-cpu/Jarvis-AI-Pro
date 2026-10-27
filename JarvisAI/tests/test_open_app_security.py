"""Regression tests for safe Windows executable and URI launching."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[2]
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for directory in (ROOT_DIR, JARVIS_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from actions.open_app import _launch_windows


class WindowsAppLaunchSecurityTests(unittest.TestCase):
    def test_resolved_executable_is_started_without_a_shell(self):
        with patch("actions.open_app.shutil.which", return_value=r"C:\\Windows\\System32\\calc.exe"), \
             patch("actions.open_app.subprocess.Popen") as popen, \
             patch("actions.open_app.time.sleep"):
            self.assertTrue(_launch_windows("calc.exe"))

        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [r"C:\\Windows\\System32\\calc.exe"])
        self.assertIs(kwargs["shell"], False)

    def test_command_wrapper_uses_registered_handler(self):
        wrapper = r"C:\\Program Files\\Editor\\editor.cmd"
        with patch("actions.open_app.shutil.which", return_value=wrapper), \
             patch("actions.open_app.os.startfile", create=True) as startfile, \
             patch("actions.open_app.subprocess.Popen") as popen, \
             patch("actions.open_app.time.sleep"):
            self.assertTrue(_launch_windows("editor"))

        startfile.assert_called_once_with(wrapper)
        popen.assert_not_called()

    def test_uri_with_shell_metacharacters_uses_shell_execute_not_cmd(self):
        uri = "https://example.test/path?a=1&b=2"
        with patch("actions.open_app.shutil.which", return_value=None), \
             patch("actions.open_app.os.startfile", create=True) as startfile, \
             patch("actions.open_app.subprocess.Popen") as popen, \
             patch("actions.open_app.time.sleep"):
            self.assertTrue(_launch_windows(uri))

        startfile.assert_called_once_with(uri)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
