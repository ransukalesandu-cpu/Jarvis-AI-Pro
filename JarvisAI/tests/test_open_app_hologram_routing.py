"""Tests for routing browser-capable destinations into hologram task cards."""

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for path in (str(ROOT_DIR), str(JARVIS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from actions import open_app as open_app_module
from actions.open_app import _open_hologram_web_task


class FakeHUD:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.opened = []
        self.logs = []
        self.compact_events = []

    def enter_compact_overlay(self):
        self.compact_events.append("enter")

    def exit_compact_overlay(self):
        self.compact_events.append("exit")

    def open_task_tab(self, title, url):
        self.opened.append((title, url))
        return self.accepted

    def write_log(self, text):
        self.logs.append(text)


class TestHologramTaskRouting(unittest.TestCase):
    def test_named_youtube_site_opens_in_task_card(self):
        hud = FakeHUD()
        result = _open_hologram_web_task("YouTube", hud)
        self.assertIn("hologram task card", result)
        self.assertEqual(hud.opened, [("YouTube", "https://www.youtube.com")])

    def test_explicit_https_url_opens_in_task_card(self):
        hud = FakeHUD()
        url = "https://www.youtube.com/watch?v=example"
        result = _open_hologram_web_task(url, hud)
        self.assertIsNotNone(result)
        self.assertEqual(hud.opened, [("www.youtube.com", url)])

    def test_native_app_is_not_routed_to_browser_card(self):
        hud = FakeHUD()
        self.assertIsNone(_open_hologram_web_task("Chrome", hud))
        self.assertEqual(hud.opened, [])

    def test_unsupported_scheme_is_not_opened(self):
        hud = FakeHUD()
        self.assertIsNone(_open_hologram_web_task("javascript:alert(1)", hud))
        self.assertEqual(hud.opened, [])

    def test_missing_ui_falls_back_to_existing_launcher(self):
        self.assertIsNone(_open_hologram_web_task("YouTube", None))

    def test_refused_task_card_does_not_claim_success(self):
        hud = FakeHUD(accepted=False)
        self.assertIsNone(_open_hologram_web_task("YouTube", hud))


    def test_native_app_requests_compact_hologram_before_launch(self):
        hud = FakeHUD()
        with patch.object(open_app_module, "_SYSTEM", "Windows"), \
             patch.object(open_app_module, "_open_hologram_web_task", return_value=None), \
             patch.dict(open_app_module._OS_LAUNCHERS, {"Windows": lambda _name: True}):
            result = open_app_module.open_app({"app_name": "Visual Studio Code"}, player=hud)
        self.assertEqual(result, "Opened Visual Studio Code.")
        self.assertEqual(hud.compact_events, ["enter"])

    def test_failed_native_app_launch_restores_full_hud(self):
        hud = FakeHUD()
        with patch.object(open_app_module, "_SYSTEM", "Windows"), \
             patch.object(open_app_module, "_open_hologram_web_task", return_value=None), \
             patch.dict(open_app_module._OS_LAUNCHERS, {"Windows": lambda _name: False}):
            result = open_app_module.open_app({"app_name": "UnlistedDesktopProgram"}, player=hud)
        self.assertIn("Could not confirm", result)
        self.assertEqual(hud.compact_events, ["enter", "exit"])


if __name__ == "__main__":
    unittest.main()
