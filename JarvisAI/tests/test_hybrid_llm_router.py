import unittest
from unittest.mock import patch

from core.hybrid_llm_router import HybridLLMRouter, resolve_preferred_provider


class HybridLLMRouterTests(unittest.TestCase):
    def test_explicit_llm_provider_takes_precedence(self):
        self.assertEqual(
            resolve_preferred_provider({"llm_provider": "groq", "ai_provider": "openai"}),
            "groq",
        )

    def test_one_shot_anthropic_setting_maps_to_claude_for_hybrid_fallback(self):
        self.assertEqual(resolve_preferred_provider({"ai_provider": "anthropic"}), "claude")

    def test_invalid_provider_falls_back_to_gemini(self):
        self.assertEqual(resolve_preferred_provider({"ai_provider": "unknown"}), "gemini")
    def test_key_status_reports_presence_without_returning_key_values(self):
        router = HybridLLMRouter(
            api_keys={"gemini": "secret-test-value", "groq": ""},
            online_check=False,
        )
        status = router.configured_key_status()
        self.assertEqual(status["gemini"], True)
        self.assertEqual(status["groq"], False)
        self.assertNotIn("secret-test-value", repr(status))

    def test_empty_prompt_is_rejected_before_provider_calls(self):
        router = HybridLLMRouter(online_check=False)
        with self.assertRaisesRegex(ValueError, "non-empty prompt"):
            router.query("   ")

    def test_provider_failure_falls_back_to_next_configured_provider(self):
        router = HybridLLMRouter(
            api_keys={"gemini": "test-gemini", "groq": "test-groq", "openai": "test-openai"},
            online_check=False,
        )
        router.is_online = lambda: True
        router.providers["gemini"] = lambda *a, **k: (_ for _ in ()).throw(TimeoutError())
        router.providers["groq"] = lambda *a, **k: {"text": "answer", "model": "test-model"}
        result = router.query("hello")
        self.assertEqual(result["text"], "answer")
        self.assertEqual(result["provider"], "groq")
        self.assertEqual(result["mode"], "cloud")
        self.assertGreaterEqual(result["latency_ms"], 0)

    def test_empty_provider_response_is_treated_as_failure(self):
        router = HybridLLMRouter(
            api_keys={"gemini": "test-gemini", "groq": "test-groq", "openai": "test-openai"},
            online_check=False,
        )
        router.is_online = lambda: True
        router.providers["gemini"] = lambda *a, **k: {"text": "  "}
        router.providers["groq"] = lambda *a, **k: {"text": "recovered"}
        self.assertEqual(router.query("hello")["text"], "recovered")

    def test_offline_prefers_local_provider_when_it_succeeds(self):
        router = HybridLLMRouter(api_keys={"gemini": "configured"}, online_check=True)
        router.is_online = lambda: False
        calls = []
        router.providers["gemini"] = lambda *a, **k: calls.append("gemini")
        router.providers["ollama"] = lambda *a, **k: {"text": "local answer", "model": "local"}
        result = router.query("hello")
        self.assertEqual(calls, [])
        self.assertEqual(result["provider"], "ollama")
        self.assertEqual(result["mode"], "local-offline")

    def test_false_offline_probe_falls_back_to_cloud_if_local_fails(self):
        router = HybridLLMRouter(
            api_keys={"gemini": "configured"}, online_check=True
        )
        router.is_online = lambda: False
        calls = []
        router.providers["ollama"] = lambda *a, **k: (
            (_ for _ in ()).throw(ConnectionError("local Ollama unavailable"))
        )
        router.providers["gemini"] = lambda *a, **k: (
            calls.append("gemini") or {"text": "cloud recovered", "model": "test-model"}
        )
        result = router.query("hello")
        self.assertEqual(calls, ["gemini"])
        self.assertEqual(result["text"], "cloud recovered")
        self.assertEqual(result["provider"], "gemini")
        self.assertEqual(result["mode"], "cloud")

    def test_missing_cloud_keys_are_skipped_without_calling_provider(self):
        router = HybridLLMRouter(online_check=False)
        router.is_online = lambda: True
        calls = []
        router.providers["gemini"] = lambda *a, **k: calls.append("gemini")
        router.providers["ollama"] = lambda *a, **k: {"text": "local answer"}
        result = router.query("hello")
        self.assertEqual(calls, [])
        self.assertEqual(result["provider"], "ollama")

    def test_connectivity_check_does_not_change_global_socket_timeout(self):
        with patch("core.hybrid_llm_router.socket.create_connection", side_effect=OSError) as connect:
            self.assertFalse(HybridLLMRouter.is_online(timeout=0.2))
        connect.assert_called_once_with(("1.1.1.1", 443), timeout=0.2)


if __name__ == "__main__":
    unittest.main()
