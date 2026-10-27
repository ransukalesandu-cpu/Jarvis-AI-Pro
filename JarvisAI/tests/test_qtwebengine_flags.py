"""Tests for safe Qt WebEngine flag configuration."""

from __future__ import annotations

import unittest

from core.qtwebengine_flags import qtwebengine_chromium_flags


class QtWebEngineFlagsTests(unittest.TestCase):
    def test_linux_keeps_chromium_sandbox_default_enabled(self):
        flags = qtwebengine_chromium_flags("Linux", "--enable-features=UseSkiaRenderer")
        self.assertNotIn("--no-sandbox", flags.split())
        self.assertIn("--enable-features=UseSkiaRenderer", flags)

    def test_explicit_user_flags_are_preserved(self):
        flags = qtwebengine_chromium_flags("Linux", "--no-sandbox --disable-gpu")
        self.assertEqual(flags, "--no-sandbox --disable-gpu")

    def test_windows_adds_gpu_flags_without_duplicates(self):
        flags = qtwebengine_chromium_flags("Windows", "--enable-zero-copy --custom-flag")
        self.assertEqual(flags.split().count("--enable-zero-copy"), 1)
        self.assertIn("--enable-gpu-rasterization", flags.split())
        self.assertIn("--custom-flag", flags.split())


if __name__ == "__main__":
    unittest.main()
