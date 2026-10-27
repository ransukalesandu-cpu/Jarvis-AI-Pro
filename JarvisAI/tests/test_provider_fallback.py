"""Unit tests for provider selection in the text-only Live fallback."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.provider_fallback import (
    _load_provider_config,
    _provider_keys,
    build_fallback_system_prompt,
    query_text_fallback,
)


class FakeRouter:
    def __init__(self, *, preferred_provider, api_keys):
        self.preferred_provider = preferred_provider
        self.api_keys = api_keys
        self.queried = None

    def configured_key_status(self):
        return {name: bool(value) for name, value in self.api_keys.items()}

    def query(self, text, *, system_prompt):
        self.queried = (text, system_prompt)
        return {"text": "test answer", "provider": self.preferred_provider, "model": "test-model"}


class ProviderFallbackTests(unittest.TestCase):
    def test_reads_only_dictionary_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "api_keys.json"
            path.write_text(json.dumps({"ai_provider": "openai"}), encoding="utf-8")
            self.assertEqual(_load_provider_config(path), {"ai_provider": "openai"})

            path.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")
            self.assertEqual(_load_provider_config(path), {})

    def test_missing_or_invalid_configuration_returns_empty_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "api_keys.json"
            self.assertEqual(_load_provider_config(path), {})
            path.write_text("{invalid", encoding="utf-8")
            self.assertEqual(_load_provider_config(path), {})

    def test_provider_keys_are_normalized_and_secret_values_not_logged(self):
        config = {
            "gemini_api_key": " gemini-test ",
            "groq_api_key": "groq-test",
            "openai_api_key": "",
            "anthropic_api_key": "anthropic-test",
            "claude_api_key": "fallback-claude-test",
        }
        keys = _provider_keys(config)
        self.assertEqual(keys, {
            "gemini": "gemini-test",
            "groq": "groq-test",
            "openai": "",
            "claude": "anthropic-test",
        })
        self.assertNotIn("gemini-test", repr({name: bool(value) for name, value in keys.items()}))

    def test_builds_text_only_fallback_instructions(self):
        prompt = build_fallback_system_prompt("base prompt")
        self.assertTrue(prompt.startswith("base prompt"))
        self.assertIn("text-only fallback", prompt)
        self.assertIn("Never claim you", prompt)

    def test_query_delegates_to_router_without_exposing_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "api_keys.json"
            path.write_text(json.dumps({
                "ai_provider": "openai",
                "hybrid_provider": "groq",
                "gemini_api_key": "secret-gemini-test",
                "groq_api_key": "secret-groq-test",
            }), encoding="utf-8")
            instances = []

            def factory(**kwargs):
                router = FakeRouter(**kwargs)
                instances.append(router)
                return router

            result, configured = query_text_fallback(
                "hello",
                config_path=path,
                base_system_prompt="system prompt",
                router_factory=factory,
            )
            self.assertEqual(result["text"], "test answer")
            self.assertEqual(configured, "gemini,groq")
            self.assertEqual(instances[0].preferred_provider, "groq")
            self.assertEqual(instances[0].queried[0], "hello")
            self.assertIn("text-only fallback", instances[0].queried[1])
            self.assertNotIn("secret-groq-test", configured)

    def test_empty_prompts_are_rejected_without_provider_construction(self):
        with patch("core.provider_fallback.HybridLLMRouter") as factory:
            with self.assertRaisesRegex(ValueError, "non-empty prompt"):
                query_text_fallback(
                    "   ",
                    config_path="/does/not/matter",
                    base_system_prompt="prompt",
                )
            factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
