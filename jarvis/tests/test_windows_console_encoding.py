"""The installer must survive a legacy Windows code page (cp1252) console."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.tools import windows_setup

ROOT = Path(__file__).resolve().parents[2]


class ConsoleEncodingTests(unittest.TestCase):
    def test_setup_banner_does_not_crash_on_cp1252(self):
        code = ("import sys; sys.path.insert(0, %r);"
                "from jarvis import setup; setup._make_console_safe();"
                "print('\\u2699  JARVIS AI setup \\u26a0')" % str(ROOT))
        env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        self.assertIn(b"JARVIS AI setup", done.stdout)

    def test_installer_child_is_forced_to_utf8(self):
        seen = {}

        def fake_run(args, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(args, 0, "", "")

        with patch.object(windows_setup.subprocess, "run", fake_run):
            windows_setup._run(["python", "setup.py"])
        self.assertEqual(seen["env"]["PYTHONUTF8"], "1")
        self.assertEqual(seen["encoding"], "utf-8")
        self.assertEqual(seen["errors"], "replace")


if __name__ == "__main__":
    unittest.main()
