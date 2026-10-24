"""
Unit tests for JARVIS AI Talking and Thinking Upgrades.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from core.tts import clean_text_for_speech
from core.vocal_behavior import (
    VOCAL_PROFILES,
    VocalBehaviorEngine,
    delivery_guidance,
    normalize_settings,
)
from plugins import deep_reasoning


class TestTalkingThinkingUpgrade(unittest.TestCase):

    def test_clean_text_for_speech_strips_code_blocks(self):
        raw = "Here is code:\n```python\nprint('hello')\n```\nAnd `inline_var`."
        cleaned = clean_text_for_speech(raw)
        self.assertNotIn("print('hello')", cleaned)
        self.assertIn("And inline_var.", cleaned)

    def test_clean_text_for_speech_strips_markdown_and_urls(self):
        raw = "Check [website](https://example.com) for **important** details with *emphasis*."
        cleaned = clean_text_for_speech(raw)
        self.assertNotIn("https://example.com", cleaned)
        self.assertIn("Check website for important details with emphasis.", cleaned)

    def test_clean_text_for_speech_expands_symbols_and_units(self):
        raw = "Memory: 16 GB, CPU: 3.5 GHz, Latency: 50 ms, Speed: 100 km/h, Progress: 80%."
        cleaned = clean_text_for_speech(raw)
        self.assertIn("16 gigabytes", cleaned)
        self.assertIn("3.5 gigahertz", cleaned)
        self.assertIn("50 milliseconds", cleaned)
        self.assertIn("100 kilometers per hour", cleaned)
        self.assertIn("80 percent", cleaned)

    def test_clean_text_for_speech_expands_math_operators(self):
        raw = "Value x = 10 + 5 > 12."
        cleaned = clean_text_for_speech(raw)
        self.assertIn("equals", cleaned)
        self.assertIn("plus", cleaned)
        self.assertIn("is greater than", cleaned)

    def test_vocal_profiles_extended(self):
        for profile in ("tactical", "analytical", "empathetic", "authoritative"):
            self.assertIn(profile, VOCAL_PROFILES)
            settings = normalize_settings({"profile": profile})
            self.assertEqual(settings["profile"], profile)
            guidance = delivery_guidance(settings)
            self.assertTrue(len(guidance) > 10)

    def test_vocal_engine_accepts_new_profiles(self):
        engine = VocalBehaviorEngine(clock=lambda: 100.0)
        settings = normalize_settings({"profile": "analytical", "expressiveness": 80})
        plan = engine.plan_response(
            "This is a long analytical response with multiple technical considerations. " * 4,
            settings,
        )
        self.assertIsNotNone(plan)

    def test_deep_reasoning_plugin_system_instruction(self):
        # Verify that deep_reasoning defines the multi-stage system instruction
        self.assertEqual(deep_reasoning.PLUGIN["name"], "deep_reasoning")
        res = deep_reasoning.run({"question": ""})
        self.assertIn("Give me the question", res)

    def test_prompt_file_contains_cognitive_and_talking_protocols(self):
        prompt_path = Path(__file__).resolve().parent.parent / "core" / "prompt.txt"
        content = prompt_path.read_text(encoding="utf-8")
        self.assertIn("[COGNITIVE FRAMEWORK & THINKING]", content)
        self.assertIn("[VOICE & TALKING PROTOCOL]", content)
        self.assertIn("Speak naturally for oral delivery", content)


if __name__ == "__main__":
    unittest.main()
