"""Tests for persistent, explicitly selected JARVIS personality modes."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from memory.voice_personality import (
    MODE_DEFINITIONS,
    voice_personality_prompt,
)
from actions.change_personality import change_personality


class PersistentPersonalityModeTests(unittest.TestCase):
    def test_angry_and_crazy_modes_are_available(self):
        self.assertIn("angry", MODE_DEFINITIONS)
        self.assertIn("crazy", MODE_DEFINITIONS)
        self.assertIn("funny", MODE_DEFINITIONS)
        self.assertIn("motivational", MODE_DEFINITIONS)
        self.assertIn("storyteller", MODE_DEFINITIONS)

    def test_manual_mode_prompt_says_stay_until_explicit_switch(self):
        with patch("memory.voice_personality.load_memory", return_value={
            "voice_personality": {"mode": {"value": "angry"}}
        }):
            prompt = voice_personality_prompt()

        self.assertIn("STICKY MODE RULE", prompt)
        self.assertIn("until the user explicitly switches to another mode", prompt)
        self.assertIn("'normal mode' means Conversational", prompt)
        self.assertNotIn("Auto Adaptive is selected", prompt)

    def test_auto_mode_is_the_only_mode_with_per_turn_adaptation(self):
        with patch("memory.voice_personality.load_memory", return_value={
            "voice_personality": {"mode": {"value": "auto"}}
        }):
            prompt = voice_personality_prompt()

        self.assertIn("Auto Adaptive is selected", prompt)
        self.assertNotIn("STICKY MODE RULE", prompt)

    def test_angry_alias_saves_mode_and_applies_persistent_profile(self):
        current = {
            "mode": "conversational",
            "custom_name": "My profile",
            "custom_instructions": "",
            "tuning": {},
            "vocal": {},
        }
        save = Mock(return_value={**current, "mode": "angry"})
        reconnect = Mock()
        with patch("actions.change_personality.get_voice_personality", return_value=current), \
             patch("actions.change_personality.save_voice_personality", save):
            result = change_personality({"mode": "angry mode"}, apply_personality=reconnect)

        self.assertEqual(save.call_args.args[0]["mode"], "angry")
        reconnect.assert_called_once_with()
        self.assertIn("stay in this mode", result)

    def test_crazy_alias_resolves_to_crazy_mode(self):
        current = {
            "mode": "conversational",
            "custom_name": "My profile",
            "custom_instructions": "",
            "tuning": {},
            "vocal": {},
        }
        save = Mock(return_value={**current, "mode": "crazy"})
        with patch("actions.change_personality.get_voice_personality", return_value=current), \
             patch("actions.change_personality.save_voice_personality", save):
            result = change_personality({"mode": "chaotic"})

        self.assertEqual(save.call_args.args[0]["mode"], "crazy")
        self.assertIn("Crazy", result)

    def test_normal_mode_switches_back_to_conversational(self):
        current = {
            "mode": "angry",
            "custom_name": "My profile",
            "custom_instructions": "",
            "tuning": {},
            "vocal": {},
        }
        save = Mock(return_value={**current, "mode": "conversational"})
        reconnect = Mock()
        with patch("actions.change_personality.get_voice_personality", return_value=current), \
             patch("actions.change_personality.save_voice_personality", save):
            result = change_personality({"mode": "normal mode"}, apply_personality=reconnect)

        self.assertEqual(save.call_args.args[0]["mode"], "conversational")
        reconnect.assert_called_once_with()
        self.assertIn("Conversational", result)
        self.assertIn("stay in this mode", result)

    def test_selected_mode_preserves_current_voice_tuning(self):
        current = {
            "mode": "conversational",
            "custom_name": "My profile",
            "custom_instructions": "",
            "tuning": {"angry": "extra theatrical"},
            "vocal": {"tone": "dramatic", "profile": "expressive"},
        }
        save = Mock(return_value={**current, "mode": "angry"})
        with patch("actions.change_personality.get_voice_personality", return_value=current), \
             patch("actions.change_personality.save_voice_personality", save):
            change_personality({"mode": "angry"})

        saved = save.call_args.args[0]
        self.assertEqual(saved["tuning"], current["tuning"])
        self.assertEqual(saved["vocal"], current["vocal"])


if __name__ == "__main__":
    unittest.main()
