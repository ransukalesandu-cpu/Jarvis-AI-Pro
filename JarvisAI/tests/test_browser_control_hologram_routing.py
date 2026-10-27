"""Tests that default browser navigation uses hologram task cards."""

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for path in (str(ROOT_DIR), str(JARVIS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from actions import browser_control


class FakeHUD:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.pages = []
        self.logs = []
        self.compact_events = []

    def enter_compact_overlay(self):
        self.compact_events.append("enter")

    def exit_compact_overlay(self):
        self.compact_events.append("exit")

    def show_webpage(self, url, title="WEB TASK"):
        self.pages.append((url, title))
        return self.accepted

    def write_log(self, text):
        self.logs.append(text)


class TestBrowserControlHologramRouting(unittest.TestCase):
    def test_default_go_to_uses_hologram_task_card(self):
        hud = FakeHUD()
        url = "https://example.com/docs"
        with patch.object(browser_control._registry, "has", return_value=False), \
             patch.object(browser_control, "_open_native") as native:
            result = browser_control.browser_control(
                {"action": "go_to", "url": url}, player=hud
            )
        self.assertIn("hologram task card", result)
        self.assertEqual(hud.pages, [(url, "EXAMPLE.COM")])
        native.assert_not_called()

    def test_default_search_uses_hologram_task_card(self):
        hud = FakeHUD()
        with patch.object(browser_control._registry, "has", return_value=False), \
             patch.object(browser_control, "_open_native") as native:
            result = browser_control.browser_control(
                {"action": "search", "query": "neural hologram", "engine": "google"},
                player=hud,
            )
        self.assertIn("hologram task card", result)
        self.assertEqual(len(hud.pages), 1)
        self.assertIn("google.com/search", hud.pages[0][0])
        native.assert_not_called()

    def test_explicit_browser_keeps_existing_native_browser_path(self):
        hud = FakeHUD()
        with patch.object(browser_control._registry, "has", return_value=False), \
             patch.object(browser_control, "_open_native", return_value="Opened in Chrome") as native:
            result = browser_control.browser_control(
                {"action": "go_to", "url": "https://example.com", "browser": "chrome"},
                player=hud,
            )
        self.assertEqual(result, "Opened in Chrome")
        self.assertEqual(hud.pages, [])
        native.assert_called_once_with("https://example.com", "chrome")

        self.assertEqual(hud.compact_events, ["enter"])

    def test_failed_external_browser_launch_exits_compact_mode(self):
        hud = FakeHUD()
        with patch.object(browser_control._registry, "has", return_value=False), \
             patch.object(browser_control, "_open_native", return_value="Could not open browser"):
            result = browser_control.browser_control(
                {"action": "go_to", "url": "https://example.com", "browser": "chrome"},
                player=hud,
            )
        self.assertEqual(result, "Could not open browser")
        self.assertEqual(hud.compact_events, ["enter", "exit"])


if __name__ == "__main__":
    unittest.main()
