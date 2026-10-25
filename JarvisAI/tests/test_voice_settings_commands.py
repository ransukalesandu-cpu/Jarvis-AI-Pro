"""
Tests for voice-controlled settings and language alias routing in Jarvis AI Pro.
"""

import unittest
from unittest.mock import MagicMock

from actions.jarvis_settings import jarvis_settings
from actions.change_personality import change_personality


class VoiceSettingsCommandsTest(unittest.TestCase):

    def test_settings_drawer_voice_control(self):
        player = MagicMock()

        # Test opening settings drawer with English / Singlish / Sinhala values
        res_open_eng = jarvis_settings({"operation": "set", "setting": "settings_drawer", "value": "open"}, player=player)
        self.assertIn("Opening settings", res_open_eng)
        player.open_settings_drawer.assert_called_once()

        player.reset_mock()
        res_open_sin = jarvis_settings({"operation": "set", "setting": "settings_drawer", "value": "arinna"}, player=player)
        self.assertIn("Opening settings", res_open_sin)
        player.open_settings_drawer.assert_called_once()

        # Test closing settings drawer
        player.reset_mock()
        res_close_eng = jarvis_settings({"operation": "set", "setting": "settings_drawer", "value": "close"}, player=player)
        self.assertIn("Closing settings", res_close_eng)
        player.close_settings_drawer.assert_called_once()

        player.reset_mock()
        res_close_sin = jarvis_settings({"operation": "set", "setting": "settings_drawer", "value": "vahanna"}, player=player)
        self.assertIn("Closing settings", res_close_sin)
        player.close_settings_drawer.assert_called_once()

    def test_ui_color_voice_control(self):
        player = MagicMock()

        # Blue / Cyan / Nil / නිල්
        res_blue = jarvis_settings({"operation": "set", "setting": "ui_color", "value": "blue"}, player=player)
        self.assertIn("#00e5ff", res_blue)
        player.set_ui_color.assert_called_with("#00e5ff")

        player.reset_mock()
        res_nil = jarvis_settings({"operation": "set", "setting": "ui_color", "value": "nil"}, player=player)
        self.assertIn("#00e5ff", res_nil)
        player.set_ui_color.assert_called_with("#00e5ff")

        # Violet / Purple / Dammunu / දම්
        player.reset_mock()
        res_violet = jarvis_settings({"operation": "set", "setting": "ui_color", "value": "violet"}, player=player)
        self.assertIn("#7c4dff", res_violet)
        player.set_ui_color.assert_called_with("#7c4dff")

    def test_side_panels_voice_control(self):
        player = MagicMock()

        res_hide = jarvis_settings({"operation": "set", "setting": "side_panels", "value": "hide"}, player=player)
        self.assertIn("Hiding side panels", res_hide)
        player.toggle_side_panels.assert_called_with(False)

        player.reset_mock()
        res_show = jarvis_settings({"operation": "set", "setting": "side_panels", "value": "show"}, player=player)
        self.assertIn("Showing side panels", res_show)
        player.toggle_side_panels.assert_called_with(True)

    def test_bihansa_mode_switch_and_restore(self):
        # Switch to Bihansa mode
        res_bihansa = change_personality({"mode": "bihansa"})
        self.assertIn("Bihansa mode is on", res_bihansa)

        # Switch back to Jarvis mode
        res_jarvis = change_personality({"mode": "jarvis"})
        self.assertIn("Switched back to JARVIS mode", res_jarvis)


if __name__ == "__main__":
    unittest.main()
