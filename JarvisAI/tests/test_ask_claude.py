"""ask_claude tool, shared Claude model names and the per-session usage counter.

No network: the Anthropic client is replaced by a fake everywhere.
"""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import actions.ask_claude as ask_claude_mod
from core import claude_usage, provider_settings
from core.provider_settings import ANTHROPIC_FAST_MODEL, ANTHROPIC_REASONING_MODEL

SECRET = "sk-ant-test-secret-value"


def _response(text, *, stop_reason="end_turn", input_tokens=11, output_tokens=7):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakePlayer:
    def __init__(self):
        self.shown = []

    def show_content(self, title, text):
        self.shown.append((title, text))


class AskClaudeTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = patch.dict(os.environ, {"JARVIS_DATA_DIR": self._tmp.name})
        env.start()
        self.addCleanup(env.stop)
        settings = patch.object(provider_settings, "_read", return_value={})
        settings.start()
        self.addCleanup(settings.stop)
        key = patch.object(ask_claude_mod, "get_provider_api_key", return_value=SECRET)
        key.start()
        self.addCleanup(key.stop)
        claude_usage.reset_usage()

    def run_tool(self, client, parameters, player=None):
        factory_calls = []

        def factory(api_key, timeout):
            factory_calls.append((api_key, timeout))
            return client

        with patch.object(ask_claude_mod, "_client_factory", factory):
            out = io.StringIO()
            with redirect_stdout(out):
                result = ask_claude_mod.ask_claude(parameters, player=player)
        return result, factory_calls, out.getvalue()


class AskClaudeToolTests(AskClaudeTestBase):
    def test_declaration_shape(self):
        tool = ask_claude_mod.TOOL
        self.assertEqual(tool["name"], "ask_claude")
        props = tool["parameters"]["properties"]
        self.assertEqual(tool["parameters"]["required"], ["task"])
        self.assertEqual(props["depth"]["enum"], ["quick", "deep"])
        for word in ("coding", "planning", "NOT", "small talk", "vision"):
            self.assertIn(word, tool["description"])

    def test_available_only_with_anthropic_key(self):
        with patch.object(ask_claude_mod, "get_provider_api_key", return_value=""):
            self.assertFalse(ask_claude_mod._has_anthropic_key())
        with patch.object(ask_claude_mod, "get_provider_api_key", return_value=SECRET):
            self.assertTrue(ask_claude_mod._has_anthropic_key())
        with patch.object(ask_claude_mod, "get_provider_api_key", side_effect=OSError):
            self.assertFalse(ask_claude_mod._has_anthropic_key())

    def test_quick_uses_fast_model_by_default(self):
        client = FakeClient(_response("Use a dictionary for that."))
        result, factory_calls, _ = self.run_tool(client, {"task": "How do I count words?"})
        self.assertEqual(client.calls[0]["model"], ANTHROPIC_FAST_MODEL)
        self.assertEqual(client.calls[0]["max_tokens"], 4096)
        self.assertEqual(factory_calls, [(SECRET, 60.0)])
        self.assertIn("Use a dictionary for that.", result)

    def test_deep_uses_strong_model(self):
        client = FakeClient(_response("Split it into three services."))
        self.run_tool(client, {"task": "Design the architecture", "depth": "deep"})
        self.assertEqual(client.calls[0]["model"], ANTHROPIC_REASONING_MODEL)
        self.assertEqual(client.calls[0]["max_tokens"], 16000)

    def test_unknown_depth_falls_back_to_quick(self):
        client = FakeClient(_response("ok"))
        self.run_tool(client, {"task": "x", "depth": "extreme"})
        self.assertEqual(client.calls[0]["model"], ANTHROPIC_FAST_MODEL)

    def test_settings_override_model_names(self):
        client = FakeClient(_response("ok"))
        with patch.object(provider_settings, "_read", return_value={
            "anthropic_model_fast": "claude-custom-fast",
            "anthropic_model_reasoning": "claude-custom-strong",
        }):
            self.run_tool(client, {"task": "x"})
            self.run_tool(client, {"task": "x", "depth": "deep"})
        self.assertEqual([c["model"] for c in client.calls],
                         ["claude-custom-fast", "claude-custom-strong"])

    def test_short_answer_is_not_saved(self):
        client = FakeClient(_response("Paris."))
        player = FakePlayer()
        result, _, _ = self.run_tool(client, {"task": "Capital of France?"}, player)
        self.assertIn("Paris.", result)
        self.assertEqual(player.shown, [])
        self.assertFalse((Path(self._tmp.name) / "claude_answers").exists())

    def test_long_answer_is_summarised_shown_and_saved(self):
        body = "def f():\n    return 1\n" * 80
        text = "Here is a small helper that returns one.\n\n```python\n" + body + "```"
        client = FakeClient(_response(text))
        player = FakePlayer()
        result, _, _ = self.run_tool(client, {"task": "Write a helper"}, player)
        self.assertIn("Here is a small helper that returns one.", result)
        self.assertNotIn("def f()", result)
        self.assertIn("on screen", result)
        files = list((Path(self._tmp.name) / "claude_answers").glob("claude-*.md"))
        self.assertEqual(len(files), 1)
        self.assertIn(str(files[0]), result)
        self.assertIn(body, files[0].read_text(encoding="utf-8"))
        self.assertEqual(player.shown, [("JARVIS — Claude", text)])

    def test_spoken_summary_is_bounded(self):
        text = ("This sentence is fairly long and keeps going. " * 40).strip()
        summary = ask_claude_mod._spoken_summary(text)
        self.assertLessEqual(len(summary), ask_claude_mod.SPOKEN_MAX_CHARS + 3)
        self.assertTrue(summary.endswith("."))

    def test_errors_return_short_message_and_never_raise(self):
        client = FakeClient(error=RuntimeError(f"boom {SECRET}"))
        result, _, out = self.run_tool(client, {"task": "x"})
        self.assertEqual(result, "Claude is unavailable right now.")
        self.assertNotIn(SECRET, out)
        with patch.object(ask_claude_mod, "_client_factory", side_effect=ImportError):
            self.assertEqual(ask_claude_mod.ask_claude({"task": "x"}),
                             "Claude is unavailable right now.")

    def test_typed_sdk_errors_get_specific_messages(self):
        import anthropic
        try:                       # anthropic 1.x
            import httpx2 as httpx
        except ImportError:        # anthropic 0.x
            import httpx
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        error = anthropic.APIConnectionError(request=request)
        result, _, _ = self.run_tool(FakeClient(error=error), {"task": "x"})
        self.assertIn("couldn't reach Claude", result)

    def test_refusal_and_empty_answers(self):
        result, _, _ = self.run_tool(FakeClient(_response("", stop_reason="refusal")),
                                     {"task": "x"})
        self.assertEqual(result, "Claude declined that request.")
        result, _, _ = self.run_tool(FakeClient(_response("   ")), {"task": "x"})
        self.assertEqual(result, "Claude returned an empty answer.")

    def test_truncated_answer_says_so(self):
        result, _, _ = self.run_tool(
            FakeClient(_response("Partial.", stop_reason="max_tokens")), {"task": "x"})
        self.assertIn("cut off", result)

    def test_missing_task_or_key(self):
        client = FakeClient(_response("ok"))
        result, _, _ = self.run_tool(client, {"task": "  "})
        self.assertIn("Tell me the task", result)
        with patch.object(ask_claude_mod, "get_provider_api_key", return_value=""):
            result, _, _ = self.run_tool(client, {"task": "x"})
        self.assertIn("AI PROVIDER / KEYS", result)
        self.assertEqual(client.calls, [])

    def test_oversized_task_is_rejected_before_any_call(self):
        client = FakeClient(_response("ok"))
        result, _, _ = self.run_tool(
            client, {"task": "x" * (ask_claude_mod.MAX_TASK_CHARS + 1)})
        self.assertIn("too long", result)
        self.assertEqual(client.calls, [])

    def test_usage_line_has_tokens_but_no_content_or_key(self):
        client = FakeClient(_response("The secret plan is ready.", input_tokens=120,
                                      output_tokens=45))
        _, _, out = self.run_tool(client, {"task": "my private task text"})
        self.assertIn("[Claude usage] call #1 source=ask_claude:quick", out)
        self.assertIn("input_tokens=120", out)
        self.assertIn("output_tokens=45", out)
        for leaked in (SECRET, "private task", "secret plan"):
            self.assertNotIn(leaked, out)
        self.assertEqual(claude_usage.usage_snapshot(),
                         {"calls": 1, "input_tokens": 120, "output_tokens": 45})


class ClaudeUsageTests(unittest.TestCase):
    def setUp(self):
        claude_usage.reset_usage()

    def test_counts_accumulate_and_bad_usage_is_tolerated(self):
        with redirect_stdout(io.StringIO()):
            claude_usage.record_claude_usage(_response("a", input_tokens=3, output_tokens=4),
                                             source="t", model="m")
            claude_usage.record_claude_usage({"usage": {"input_tokens": 2}},
                                             source="t", model="m")
            claude_usage.record_claude_usage(object(), source="t", model="m")
        self.assertEqual(claude_usage.usage_snapshot(),
                         {"calls": 3, "input_tokens": 5, "output_tokens": 4})


class SharedModelNameTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(ANTHROPIC_REASONING_MODEL, "claude-sonnet-5-5")
        self.assertEqual(ANTHROPIC_FAST_MODEL, "claude-haiku-5-5")
        with patch.object(provider_settings, "_read", return_value={}):
            self.assertEqual(provider_settings.anthropic_model("fast"), ANTHROPIC_FAST_MODEL)
            self.assertEqual(provider_settings.anthropic_model("quick"), ANTHROPIC_FAST_MODEL)
            self.assertEqual(provider_settings.anthropic_model("reasoning"),
                             ANTHROPIC_REASONING_MODEL)
            settings = provider_settings.get_provider_settings()
        self.assertEqual(settings["anthropic_model_fast"], ANTHROPIC_FAST_MODEL)
        self.assertEqual(settings["anthropic_model_reasoning"], ANTHROPIC_REASONING_MODEL)

    def test_one_shot_tiers_use_shared_names_and_overrides(self):
        from core import ai_providers
        with patch.object(provider_settings, "_read", return_value={}):
            self.assertEqual(ai_providers._model("anthropic", ai_providers.FAST),
                             ANTHROPIC_FAST_MODEL)
            self.assertEqual(ai_providers._model("anthropic", "deep"),
                             ANTHROPIC_REASONING_MODEL)
        with patch.object(provider_settings, "_read",
                          return_value={"anthropic_model_fast": "claude-x"}):
            self.assertEqual(ai_providers._model("anthropic", ai_providers.FAST), "claude-x")

    def test_hybrid_router_claude_uses_shared_name(self):
        from core.hybrid_llm_router import HybridLLMRouter
        client = FakeClient(_response("router answer"))
        with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_ANON_KEY": ""}), \
                patch.object(provider_settings, "_read", return_value={}), \
                patch("anthropic.Anthropic", return_value=client), \
                redirect_stdout(io.StringIO()):
            router = HybridLLMRouter("claude", api_keys={"claude": SECRET}, online_check=False)
            result = router.query("hello")
        self.assertEqual(result["model"], ANTHROPIC_REASONING_MODEL)
        self.assertEqual(client.calls[0]["model"], ANTHROPIC_REASONING_MODEL)
        self.assertEqual(result["provider"], "claude")


class AskClaudeRegistrationTests(unittest.TestCase):
    def test_discovered_and_hidden_without_key(self):
        from core.action_loader import discover_actions
        actions_dir = Path(ask_claude_mod.__file__).resolve().parent
        registry = discover_actions(actions_dir, logger=lambda _msg: None)
        self.assertTrue(registry.has("ask_claude"))
        self.assertEqual(registry.meta("ask_claude").risk, "read")
        with patch.object(ask_claude_mod, "get_provider_api_key", return_value=""):
            names = {d["name"] for d in registry.get_tool_declarations()}
        self.assertNotIn("ask_claude", names)
        with patch.object(ask_claude_mod, "get_provider_api_key", return_value=SECRET):
            names = {d["name"] for d in registry.get_tool_declarations()}
        self.assertIn("ask_claude", names)

    def test_security_tier_and_cost_limit(self):
        from core import security
        from core.dispatcher import ActionDispatcher, TIER_2_PRIVILEGED
        self.assertEqual(security.tier_for("ask_claude", {"task": "x"}), security.TIER_SAFE)
        self.assertIn("ask_claude", security._COSTLY_SAFE_LIMITS)
        # Spends the owner's API credit: not available to a restricted speaker.
        self.assertEqual(ActionDispatcher.get_action_tier("ask_claude"), TIER_2_PRIVILEGED)


if __name__ == "__main__":
    unittest.main()
