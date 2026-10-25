import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.adaptive_memory import MemoryStore
from core.behavior_extraction import BehaviorExtractionEngine
from core.dynamic_prompt import DynamicPromptBuilder


class AdaptiveMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tmp.name) / "memory.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_memory_off_by_default_and_requires_explicit_enable(self):
        self.assertFalse(self.store.enabled)
        with self.assertRaises(PermissionError):
            self.store.confirm_memory("preference", "Sinhala answers")

    def test_confirm_list_delete_and_clear(self):
        self.store.set_enabled(True)
        memory_id = self.store.confirm_memory("preference", "Prefers concise Sinhala answers", 0.9)
        items = self.store.list_memories()
        self.assertEqual(items[0]["id"], memory_id)
        self.assertEqual(items[0]["category"], "preference")
        self.assertTrue(self.store.delete_memory(memory_id))
        self.store.confirm_memory("habit", "Studies in the morning", 0.8)
        self.store.clear()
        self.assertEqual(self.store.list_memories(), [])

    def test_unsupported_category_rejected(self):
        self.store.set_enabled(True)
        with self.assertRaises(ValueError):
            self.store.confirm_memory("medical_diagnosis", "example")

    def test_prompt_uses_only_confirmed_memory_and_ephemeral_tone(self):
        self.store.set_enabled(True)
        self.store.confirm_memory("tone", "Prefers concise answers")
        prompt = DynamicPromptBuilder(self.store).build("Base prompt", "calm")
        self.assertIn("Prefers concise answers", prompt)
        self.assertIn("calm, reassuring", prompt)
        self.store.set_enabled(False)
        prompt_off = DynamicPromptBuilder(self.store).build("Base prompt", "neutral")
        self.assertNotIn("Prefers concise answers", prompt_off)

    def test_extractor_requires_memory_opt_in_and_filters_categories(self):
        router_factory = Mock()
        engine = BehaviorExtractionEngine(self.store, router_factory=router_factory)
        result = engine.extract_candidates("I like short answers")
        self.assertEqual(result["candidates"], [])
        router_factory.assert_not_called()

    def test_extractor_validates_candidate_output(self):
        self.store.set_enabled(True)
        router = Mock()
        router.query.return_value = {"text": json.dumps({
            "candidates": [
                {"category": "preference", "value": "Prefers Sinhala", "confidence": 0.9},
                {"category": "medical_diagnosis", "value": "diagnosis", "confidence": 1.0},
                {"category": "habit", "value": "x" * 501, "confidence": 0.99},
            ],
            "tone_hint": "sad"
        })}
        engine = BehaviorExtractionEngine(self.store, router_factory=Mock(return_value=router))
        result = engine.extract_candidates("I prefer Sinhala")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["tone_hint"], "sad")
        self.assertEqual(self.store.list_memories(), [])  # extraction never auto-saves

    def test_quoted_secrets_are_redacted_before_extraction(self):
        self.store.set_enabled(True)
        router = Mock()
        router.query.return_value = {"text": '{"candidates":[],"tone_hint":"neutral"}'}
        engine = BehaviorExtractionEngine(self.store, router_factory=Mock(return_value=router))
        engine.extract_candidates('I prefer short answers. {"api_key": "synthetic credential"}')
        prompt = router.query.call_args.args[0]
        self.assertNotIn("synthetic credential", prompt)
        self.assertIn("[REDACTED]", prompt)
        self.assertEqual(self.store.list_memories(), [])


if __name__ == "__main__":
    unittest.main()
