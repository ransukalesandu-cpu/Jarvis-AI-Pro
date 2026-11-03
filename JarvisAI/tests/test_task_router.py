"""Task-based provider routing (core/task_router.py) and where it is wired in."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core import task_router
from core.hybrid_llm_router import HybridLLMRouter, resolve_preferred_provider
from core.task_router import (
    DEFAULT_TASK_ROUTING, TASK_CATEGORIES, category_for_request, provider_for_task,
    task_routing_enabled, task_routing_table,
)

_NO_KEY_ENV = {name: "" for name in (
    "GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "SUPABASE_URL", "SUPABASE_ANON_KEY",
)}


class TaskRoutingTableTests(unittest.TestCase):
    def test_every_category_has_the_documented_default(self):
        expected = {
            "voice": "gemini", "vision": "gemini", "screen": "gemini", "camera": "gemini",
            "coding": "claude", "planning": "claude", "reasoning": "claude",
            "writing": "claude", "image_generation": "openai", "simple": "gemini",
        }
        self.assertEqual(DEFAULT_TASK_ROUTING, expected)
        self.assertEqual(set(TASK_CATEGORIES), set(expected))
        config = {"task_routing": True}
        for category, provider in expected.items():
            with self.subTest(category=category):
                self.assertEqual(
                    provider_for_task(category, config, has_key=lambda _p: True), provider)

    def test_enabled_only_by_true_or_a_mapping(self):
        self.assertFalse(task_routing_enabled({}))
        self.assertFalse(task_routing_enabled(None))
        self.assertFalse(task_routing_enabled({"task_routing": False}))
        self.assertFalse(task_routing_enabled({"task_routing": "yes"}))
        self.assertTrue(task_routing_enabled({"task_routing": True}))
        self.assertTrue(task_routing_enabled({"task_routing": {}}))

    def test_overrides_apply_and_invalid_entries_are_ignored(self):
        table = task_routing_table({"task_routing": {
            "writing": "OpenAI", "coding": "anthropic", "simple": "not-a-provider",
            "unknown_category": "groq", "reasoning": None,
        }})
        self.assertEqual(table["writing"], "openai")
        self.assertEqual(table["coding"], "claude")
        self.assertEqual(table["simple"], "gemini")
        self.assertEqual(table["reasoning"], "claude")
        self.assertNotIn("unknown_category", table)

    def test_unknown_category_counts_as_simple(self):
        config = {"task_routing": {"simple": "groq"}}
        self.assertEqual(provider_for_task("mystery", config), "groq")
        self.assertEqual(provider_for_task("", config), "groq")

    def test_image_generation_uses_openai_only_with_a_key(self):
        config = {"task_routing": True}
        self.assertEqual(provider_for_task("image_generation", config,
                                           has_key=lambda p: p == "openai"), "openai")
        self.assertEqual(provider_for_task("image_generation", config,
                                           has_key=lambda _p: False), "gemini")
        self.assertEqual(provider_for_task("image_generation", config,
                                           has_key=Mock(side_effect=OSError)), "gemini")

    def test_request_categories(self):
        cases = {
            "Fix this python exception in my function": "coding",
            "Give me a step-by-step roadmap for launching the app": "planning",
            "What's the weather today?": "simple",
            "Draft an email to my landlord about the leak": "writing",
            "Evaluate the trade-off between these two databases": "reasoning",
            "hello there": "simple",
        }
        for text, category in cases.items():
            with self.subTest(text=text):
                self.assertEqual(category_for_request(text), category)


class ResolvePreferredProviderTests(unittest.TestCase):
    LEGACY_CONFIGS = (
        {},
        {"ai_provider": "openai"},
        {"ai_provider": "anthropic"},
        {"hybrid_provider": "groq", "ai_provider": "openai"},
        {"ai_provider": "unknown"},
        {"task_routing": False, "ai_provider": "openai"},
    )

    def test_legacy_behaviour_is_unchanged_without_task_routing(self):
        for config in self.LEGACY_CONFIGS:
            legacy = resolve_preferred_provider(config)
            for category in (*TASK_CATEGORIES, None, "", "nonsense"):
                with self.subTest(config=config, category=category):
                    self.assertEqual(resolve_preferred_provider(config, task=category), legacy)

    def test_task_routing_overrides_the_single_provider_choice(self):
        config = {"ai_provider": "openai", "task_routing": True}
        self.assertEqual(resolve_preferred_provider(config), "openai")
        self.assertEqual(resolve_preferred_provider(config, task="coding"), "claude")
        self.assertEqual(resolve_preferred_provider(config, task="simple"), "gemini")

    def test_image_generation_key_check_reads_settings_and_env(self):
        config = {"task_routing": True}
        with patch.dict(os.environ, _NO_KEY_ENV):
            self.assertEqual(resolve_preferred_provider(config, task="image_generation"),
                             "gemini")
            self.assertEqual(resolve_preferred_provider(
                {**config, "openai_api_key": "sk-test"}, task="image_generation"), "openai")
        with patch.dict(os.environ, {**_NO_KEY_ENV, "OPENAI_API_KEY": "sk-env"}):
            self.assertEqual(resolve_preferred_provider(config, task="image_generation"),
                             "openai")


class MissingKeyFallbackTests(unittest.TestCase):
    def test_router_ladder_skips_preferred_provider_without_key(self):
        preferred = resolve_preferred_provider({"task_routing": True}, task="coding")
        self.assertEqual(preferred, "claude")
        with patch.dict(os.environ, _NO_KEY_ENV):
            router = HybridLLMRouter(preferred, api_keys={"gemini": "g-test"},
                                     online_check=False)
            calls = []

            def fake(name):
                def call(prompt, system_prompt, **_kw):
                    calls.append(name)
                    return {"text": f"{name} answer", "model": name}
                return call

            router.providers = {name: fake(name) for name in router.providers}
            result = router.query("write a parser")
        self.assertEqual(result["provider"], "gemini")
        self.assertNotIn("claude", calls)


class WiringTests(unittest.TestCase):
    def _config_file(self, data):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "api_keys.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_query_text_fallback_passes_task_to_provider_choice(self):
        from core.provider_fallback import query_text_fallback
        seen = []

        class FakeRouter:
            def __init__(self, *, preferred_provider, api_keys):
                seen.append(preferred_provider)

            def configured_key_status(self):
                return {}

            def query(self, text, *, system_prompt):
                return {"text": "ok"}

        routed = self._config_file({"ai_provider": "openai", "task_routing": True})
        legacy = self._config_file({"ai_provider": "openai"})
        for path in (routed, legacy):
            query_text_fallback("x", config_path=path, base_system_prompt="",
                                router_factory=FakeRouter, task="coding")
            query_text_fallback("x", config_path=path, base_system_prompt="",
                                router_factory=FakeRouter)
        self.assertEqual(seen, ["claude", "openai", "openai", "openai"])

    def test_brain_engine_sends_the_request_category(self):
        from core.brain_engine import BrainEngine
        query = Mock(return_value=({"text": "answer", "provider": "gemini"}, "gemini"))
        BrainEngine(query_fn=query).respond("Fix this python exception in my function")
        self.assertEqual(query.call_args.kwargs["task"], "coding")
        BrainEngine(query_fn=query).respond("hello")
        self.assertEqual(query.call_args.kwargs["task"], "simple")

    def test_intent_classifier_uses_simple_category_only_when_configured(self):
        from core import smart_intent_router
        router = Mock()
        router.query.return_value = {"text": '{"intent":"CHAT","reason":"x"}'}
        factory = Mock(return_value=router)
        for data, expected in (
            ({"ai_provider": "openai"}, "openai"),
            ({"ai_provider": "openai", "task_routing": {"simple": "groq"}}, "groq"),
        ):
            with self.subTest(data=data), \
                    patch.object(smart_intent_router, "API_CONFIG_PATH", self._config_file(data)):
                smart_intent_router.SmartIntentRouter(router_factory=factory).route("hi")
                self.assertEqual(factory.call_args.kwargs["preferred_provider"], expected)

    def test_task_router_is_pure(self):
        source = Path(task_router.__file__).read_text(encoding="utf-8")
        for forbidden in ("open(", "import urllib", "import requests", "import socket",
                          "read_text(", "import os"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
