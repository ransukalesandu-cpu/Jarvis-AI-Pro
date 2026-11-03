"""Hybrid Phase 1: the ask_claude tool, shared Claude model names, usage log.

No network: the Anthropic client is a fake that records the request.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import anthropic
import httpx2

import actions.ask_claude as ac
from core import claude_usage, provider_settings


def _response(text, *, stop="end_turn", model="m", tin=11, tout=22):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=tin, output_tokens=tout),
                           stop_reason=stop, model=model)


class FakeClient:
    def __init__(self, response=None, error=None):
        self.calls = []
        self._response, self._error = response, error
        self.messages = SimpleNamespace(create=self._create("messages"))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create("beta")))

    def _create(self, path):
        def create(**kwargs):
            self.calls.append((path, kwargs))
            if self._error is not None:
                raise self._error
            return self._response
        return create


def _api_error(cls, status):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("x", response=httpx2.Response(status, request=req), body=None)


class ModelNameTests(unittest.TestCase):
    def test_defaults_live_in_one_place(self):
        with mock.patch.object(provider_settings, "_read", return_value={}):
            self.assertEqual(provider_settings.claude_model("strong"), "claude-sonnet-5-5")
            self.assertEqual(provider_settings.claude_model("fast"), "claude-haiku-5-5")
            self.assertEqual(provider_settings.get_provider_settings()["anthropic_model_fast"],
                             "claude-haiku-5-5")
            from core.ai_providers import _model
            self.assertEqual(_model("anthropic", "fast"), "claude-haiku-5-5")
            self.assertEqual(_model("anthropic", "search"), "claude-sonnet-5-5")

    def test_settings_override_the_defaults(self):
        cfg = {"anthropic_model_fast": "my-fast", "anthropic_model_reasoning": "my-strong"}
        with mock.patch.object(provider_settings, "_read", return_value=cfg):
            self.assertEqual(provider_settings.claude_model("fast"), "my-fast")
            self.assertEqual(provider_settings.claude_model("strong"), "my-strong")

    def test_text_fallback_router_uses_the_shared_default(self):
        from core.hybrid_llm_router import HybridLLMRouter
        fake = FakeClient(_response("hello"))
        router = HybridLLMRouter("claude", api_keys={"claude": "k"}, online_check=False)
        router._supabase_enabled = False
        with mock.patch.object(provider_settings, "_read", return_value={}), \
                mock.patch.object(anthropic, "Anthropic", return_value=fake):
            out = router._call_claude("hi", "sys")
        self.assertEqual(out["model"], "claude-sonnet-5-5")
        self.assertEqual(fake.calls[0][1]["model"], "claude-sonnet-5-5")


class AskClaudeTests(unittest.TestCase):
    def setUp(self):
        claude_usage.reset()
        self.tmp = tempfile.TemporaryDirectory()
        patches = [
            mock.patch.object(ac, "get_provider_api_key", return_value="sk-test"),
            mock.patch.object(provider_settings, "_read", return_value={}),
            mock.patch.object(ac, "_documents_dir", return_value=Path(self.tmp.name)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_tool(self, params, client):
        return ac.ask_claude(params, client_factory=lambda timeout: client)

    def test_hidden_without_a_key(self):
        with mock.patch.object(ac, "get_provider_api_key", return_value=""):
            self.assertFalse(ac.TOOL["available"]())
            self.assertIn("isn't set up", ac.ask_claude({"task": "x"}))
        self.assertTrue(ac.TOOL["available"]())

    def test_declaration(self):
        props = ac.TOOL["parameters"]["properties"]
        self.assertEqual(props["depth"]["enum"], ["quick", "deep"])
        self.assertEqual(ac.TOOL["parameters"]["required"], ["task"])
        desc = ac.TOOL["description"].lower()
        for word in ("coding", "planning", "not use it for simple commands", "camera"):
            self.assertIn(word, desc)

    def test_quick_uses_the_fast_model_and_returns_the_spoken_part(self):
        fake = FakeClient(_response("SPOKEN: Use a set for fast lookups.\nDETAILS:"))
        out = self.run_tool({"task": "how do I dedupe a list"}, fake)
        self.assertEqual(out, "Use a set for fast lookups.")
        path, kw = fake.calls[0]
        self.assertEqual(path, "messages")
        self.assertEqual(kw["model"], "claude-haiku-5-5")
        self.assertEqual(kw["output_config"], {"effort": "low"})
        self.assertLessEqual(kw["max_tokens"], 4096)
        self.assertEqual(list(Path(self.tmp.name).rglob("*.md")), [])     # nothing to save

    def test_deep_uses_the_strong_model_with_fallback_and_saves_long_text(self):
        details = "```python\nprint('x')\n```\n" * 50
        fake = FakeClient(_response(f"SPOKEN: I wrote the script.\nDETAILS:\n{details}"))
        out = self.run_tool({"task": "write a backup script", "depth": "deep"}, fake)
        path, kw = fake.calls[0]
        self.assertEqual(path, "beta")
        self.assertEqual(kw["model"], "claude-sonnet-5-5")
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["betas"], ["server-side-fallback-2026-07-01"])
        self.assertTrue(out.startswith("I wrote the script."))
        saved = list(Path(self.tmp.name).rglob("*.md"))
        self.assertEqual(len(saved), 1)
        self.assertIn(str(saved[0]), out)
        self.assertIn("print('x')", saved[0].read_text(encoding="utf-8"))

    def test_unstructured_long_answer_is_cut_and_saved(self):
        fake = FakeClient(_response("word " * 400))
        out = self.run_tool({"task": "essay"}, fake)
        self.assertLess(len(out), 900)
        self.assertIn("saved in", out)

    def test_errors_are_short_and_honest(self):
        cases = [
            (_api_error(anthropic.AuthenticationError, 401), "rejected the API key"),
            (_api_error(anthropic.RateLimitError, 429), "rate-limited"),
            (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), "couldn't reach"),
            (ValueError("boom"), "unavailable right now"),
        ]
        for err, phrase in cases:
            out = self.run_tool({"task": "x"}, FakeClient(error=err))
            self.assertIn(phrase, out)
            self.assertNotIn("sk-test", out)

    def test_refusal_and_empty_and_truncated(self):
        self.assertIn("declined", self.run_tool({"task": "x"}, FakeClient(_response("", stop="refusal"))))
        self.assertIn("empty", self.run_tool({"task": "x"}, FakeClient(_response(""))))
        out = self.run_tool({"task": "x"}, FakeClient(_response("SPOKEN: partial", stop="max_tokens")))
        self.assertIn("cut off", out)

    def test_usage_is_counted_and_logged_without_content(self):
        fake = FakeClient(_response("SPOKEN: secret answer text", tin=100, tout=50, model="claude-haiku-5-5"))
        with mock.patch("builtins.print") as printed:
            self.run_tool({"task": "a private question"}, fake)
        usage = claude_usage.session_usage()
        self.assertEqual((usage["calls"], usage["input_tokens"], usage["output_tokens"]), (1, 100, 50))
        line = " ".join(str(a) for c in printed.call_args_list for a in c.args)
        self.assertIn("model=claude-haiku-5-5", line)
        self.assertIn("input_tokens=100", line)
        self.assertNotIn("secret answer", line)
        self.assertNotIn("private question", line)
        self.assertNotIn("sk-test", line)

    def test_loader_discovers_the_tool(self):
        from core.action_loader import discover_actions
        actions_dir = Path(ac.__file__).resolve().parent
        registry = discover_actions(actions_dir, logger=lambda *_: None)
        self.assertTrue(registry.has("ask_claude"))


if __name__ == "__main__":
    unittest.main()
