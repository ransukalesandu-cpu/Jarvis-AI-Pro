"""Tests for the explicit voice UI command parser."""
from __future__ import annotations

import unittest

from core.voice_ui_control import (
    is_high_impact_ui_label,
    normalize_label,
    parse_voice_ui_command,
)


class VoiceUICommandParserTests(unittest.TestCase):
    def test_click_and_open_commands(self):
        for text, target in (
            ("click settings", "settings"),
            ("Please click the settings button", "settings"),
            ("open AI provider settings", "ai provider settings"),
            ("Hey Jarvis, show controls", "controls"),
            ("go to response personality", "response personality"),
            ("tap microphone", "microphone"),
            ("settings eka open karanna", "settings"),
            ("settings button eka click karanna", "settings"),
            ("open karanna settings", "settings"),
        ):
            with self.subTest(text=text):
                command = parse_voice_ui_command(text)
                self.assertIsNotNone(command)
                self.assertEqual(command.action, "click")
                self.assertEqual(command.target, target)

    def test_state_commands_preserve_the_requested_state(self):
        cases = {
            "turn on microphone": ("microphone", "on"),
            "turn off microphone": ("microphone", "off"),
            "switch on the microphone": ("microphone", "on"),
            "mute the microphone": ("microphone", "off"),
            "unmute microphone": ("microphone", "on"),
            "enable microphone": ("microphone", "on"),
            "disable microphone": ("microphone", "off"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                command = parse_voice_ui_command(text)
                self.assertIsNotNone(command)
                self.assertEqual(command.action, "set_state")
                self.assertEqual((command.target, command.desired_state), expected)

    def test_scroll_focus_and_tab_commands(self):
        cases = {
            "scroll down": ("scroll", "down"),
            "scroll top": ("scroll", "top"),
            "focus next": ("focus_next", ""),
            "focus previous": ("focus_previous", ""),
            "next tab": ("next_tab", ""),
            "previous tab": ("previous_tab", ""),
            "close dialog": ("close_active", ""),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                command = parse_voice_ui_command(text)
                self.assertIsNotNone(command)
                self.assertEqual((command.action, command.target), expected)

    def test_confirmation_phrases_are_not_generic_button_commands(self):
        for text in (
            "confirm action", "confirm", "approve access", "cancel action",
            "deny request", "yes", "no", "okay",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_voice_ui_command(text))

    def test_conversation_is_not_guessed_as_a_click(self):
        for text in (
            "", "what is the weather today", "please help me with my settings",
            "I think we should open settings later", "click",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_voice_ui_command(text))

    def test_high_impact_labels_are_flagged(self):
        for text in ("Delete item", "PUBLISH NOW", "Memory Export", "Dev Agent"):
            with self.subTest(text=text):
                self.assertTrue(is_high_impact_ui_label(text))
        self.assertFalse(is_high_impact_ui_label("Response Personality"))
        self.assertFalse(is_high_impact_ui_label("Open Console"))

    def test_label_normalization(self):
        self.assertEqual(normalize_label("  AI Provider / Keys  "), "ai provider keys")


if __name__ == "__main__":
    unittest.main()
