"""Regression tests for spoken voice, tone, and original-song commands."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from actions.change_voice import change_voice
from actions.change_voice_style import change_voice_style
from actions.sing_song import sing_song


class VoiceFeatureActionTests(unittest.TestCase):
    def test_female_voice_alias_saves_aoede_and_reconnects(self):
        reconnect = Mock()
        with patch("actions.change_voice.get_assistant_mode", return_value="jarvis"), \
             patch("actions.change_voice.save_voice") as save_voice:
            result = change_voice({"voice": "female"}, apply_voice_change=reconnect)

        save_voice.assert_called_once_with("Aoede")
        reconnect.assert_called_once_with()
        self.assertIn("Aoede", result)

    def test_bihansa_voice_stays_on_supported_female_preset(self):
        reconnect = Mock()
        with patch("actions.change_voice.get_assistant_mode", return_value="bihansa"), \
             patch("actions.change_voice.save_bihansa_voice") as save_voice:
            result = change_voice({"voice": "Charon"}, apply_voice_change=reconnect)

        save_voice.assert_called_once_with("Aoede")
        reconnect.assert_called_once_with()
        self.assertIn("Aoede", result)

    def test_unknown_voice_does_not_change_saved_voice(self):
        reconnect = Mock()
        with patch("actions.change_voice.get_assistant_mode", return_value="jarvis"), \
             patch("actions.change_voice.save_voice") as save_voice:
            result = change_voice({"voice": "imaginary"}, apply_voice_change=reconnect)

        save_voice.assert_not_called()
        reconnect.assert_not_called()
        self.assertIn("not available", result)

    def test_soft_voice_style_persists_and_reconnects(self):
        current = {
            "mode": "auto",
            "custom_name": "My profile",
            "custom_instructions": "",
            "tuning": {},
            "vocal": {"enabled": True, "tone": "natural", "profile": "professional"},
        }
        save = Mock(return_value=current)
        reconnect = Mock()
        with patch("actions.change_voice_style.get_voice_personality", return_value=current), \
             patch("actions.change_voice_style.save_voice_personality", save):
            result = change_voice_style({"style": "soft"}, apply_personality=reconnect)

        saved = save.call_args.args[0]
        self.assertEqual(saved["vocal"]["tone"], "soft")
        self.assertEqual(saved["vocal"]["profile"], "natural")
        self.assertEqual(saved["vocal"]["pause_naturalness"], 60)
        reconnect.assert_called_once_with()
        self.assertIn("soft", result)

    def test_unknown_style_is_not_persisted(self):
        with patch("actions.change_voice_style.save_voice_personality") as save:
            result = change_voice_style({"style": "made-up"})

        save.assert_not_called()
        self.assertIn("couldn't identify", result)

    def test_singing_action_requests_original_audio_performance(self):
        result = sing_song({
            "topic": "studying for exams",
            "mood": "motivational",
            "language": "singlish",
        })
        self.assertIn("short original song", result)
        self.assertIn("melodic vocal performance", result)
        self.assertIn("Sing naturally in Sinhala-English Singlish", result)
        self.assertIn("Do not reproduce lyrics from a copyrighted song", result)

    def test_singing_action_sanitizes_invalid_mood_and_language(self):
        result = sing_song({"mood": "unknown", "language": "unknown"})
        self.assertIn("Mood: happy", result)
        self.assertIn("Use the language the user is currently speaking", result)


if __name__ == "__main__":
    unittest.main()
