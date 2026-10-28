"""Tests for the system media-key transport behind the music task panel.

The whole point of this module is the *negative* case: on a machine where media
keys cannot be delivered the panel must show no transport buttons at all, and a
failed press must not flip the play/pause glyph. Those two rules are what stop
the HUD from advertising an action it cannot perform.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import unittest

from core import media_transport
from core.media_transport import COMMANDS, TransportController, command_for_action, send


class RecordingPress:
    """Stand-in for ``pyautogui.press`` that remembers what it was asked to do."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, key):
        self.calls.append(key)
        if self.fail:
            raise RuntimeError("keyboard backend refused the key")


class TestCommands(unittest.TestCase):
    def test_every_command_maps_to_a_real_media_key(self):
        self.assertEqual(
            COMMANDS,
            {
                "play_pause": "playpause",
                "next": "nexttrack",
                "previous": "prevtrack",
                "stop": "stop",
            },
        )

    def test_send_presses_the_mapped_key(self):
        press = RecordingPress()
        ok, detail = send("next", press=press)
        self.assertTrue(ok)
        self.assertEqual(press.calls, ["nexttrack"])
        self.assertIn("next", detail.lower())

    def test_send_reports_an_unknown_command_without_touching_the_keyboard(self):
        press = RecordingPress()
        ok, detail = send("rewind", press=press)
        self.assertFalse(ok)
        self.assertEqual(press.calls, [])
        self.assertIn("unknown", detail.lower())

    def test_send_reports_a_backend_rejection(self):
        ok, detail = send("play_pause", press=RecordingPress(fail=True))
        self.assertFalse(ok)
        self.assertIn("rejected", detail.lower())

    def test_send_without_a_presser_reports_unavailable(self):
        """No pyautogui ⇒ the caller is told, it is not silently ignored."""
        original = media_transport._presser
        media_transport._presser = lambda: None
        try:
            ok, detail = send("next")
        finally:
            media_transport._presser = original
        self.assertFalse(ok)
        self.assertIn("unavailable", detail.lower())

    def test_action_name_mapping(self):
        self.assertEqual(command_for_action("pause_music"), "play_pause")
        self.assertEqual(command_for_action("next_track"), "next")
        self.assertEqual(command_for_action("previous_track"), "previous")
        # Opening a player is not a transport command.
        self.assertIsNone(command_for_action("play_music"))
        self.assertIsNone(command_for_action("spotify_control"))
        self.assertIsNone(command_for_action(""))


class TestTransportController(unittest.TestCase):
    def test_callbacks_are_empty_when_no_key_can_be_sent(self):
        original = media_transport._presser
        media_transport._presser = lambda: None
        try:
            controller = TransportController()
            self.assertFalse(controller.available())
            self.assertEqual(controller.callbacks(), {})
        finally:
            media_transport._presser = original

    def test_callbacks_exist_for_every_control_when_available(self):
        controller = TransportController(press=RecordingPress())
        callbacks = controller.callbacks()
        self.assertEqual(
            set(callbacks), {"on_play_pause", "on_next", "on_previous"}
        )

    def test_play_pause_flips_state_only_after_a_successful_press(self):
        changes = []
        press = RecordingPress()
        controller = TransportController(on_change=changes.append, press=press)
        self.assertFalse(controller.playing)

        self.assertTrue(controller.play_pause())
        self.assertTrue(controller.playing)
        self.assertEqual(changes, [True])
        self.assertEqual(press.calls, ["playpause"])

        self.assertTrue(controller.play_pause())
        self.assertFalse(controller.playing)
        self.assertEqual(changes, [True, False])

    def test_a_rejected_press_does_not_change_state(self):
        changes = []
        controller = TransportController(
            on_change=changes.append, press=RecordingPress(fail=True)
        )
        self.assertFalse(controller.play_pause())
        self.assertFalse(controller.playing)
        self.assertEqual(changes, [])
        self.assertIn("rejected", controller.last_detail.lower())

    def test_a_broken_state_callback_does_not_raise(self):
        def explode(_playing):
            raise RuntimeError("the HUD went away")

        controller = TransportController(on_change=explode, press=RecordingPress())
        self.assertTrue(controller.play_pause())
        self.assertTrue(controller.playing)


if __name__ == "__main__":
    unittest.main()
