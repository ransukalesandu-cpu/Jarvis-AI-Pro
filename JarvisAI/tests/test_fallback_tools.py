"""Read-only Claude tool use for the text fallback (core/fallback_tools.py).

Fake Anthropic clients only; no network.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from core import provider_settings, security
from core.fallback_tools import (
    SAFE_FALLBACK_TOOLS, build_tool_specs, execute_allowed_tool, gemini_schema_to_json,
    run_claude_tool_fallback,
)
from core.provider_settings import ANTHROPIC_FAST_MODEL, ANTHROPIC_REASONING_MODEL

KEY = "sk-ant-fallback-test"

DECLARATIONS = [
    {"name": "battery_status", "description": "Battery level.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "weather_report", "description": "Weather.",
     "parameters": {"type": "OBJECT", "properties": {
         "city": {"type": "STRING", "description": "City"},
         "device": {"type": "STRING"}},
         "required": ["city"]}},
    {"name": "open_app", "description": "Opens an app.",
     "parameters": {"type": "OBJECT", "properties": {"app_name": {"type": "STRING"}}}},
    {"name": "file_controller", "description": "Files.",
     "parameters": {"type": "OBJECT", "properties": {}}},
]


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(name, args, block_id="toolu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=block_id)


def response(blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=5, output_tokens=3))


class ScriptedClient:
    """Returns the scripted responses in order and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        # Snapshot the messages: the caller keeps appending to the same list.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def run(client, *, execute=None, task=None, **kwargs):
    execute = execute or Mock(return_value="Battery at 80 percent, sir.")
    with patch.object(provider_settings, "_read", return_value={}), \
            redirect_stdout(io.StringIO()):
        result = run_claude_tool_fallback(
            "How is my battery?", system_prompt="BASE", api_key=KEY,
            declarations=DECLARATIONS, execute=execute, task=task,
            client_factory=lambda _key, _timeout: client, **kwargs)
    return result, execute


class AllowListTests(unittest.TestCase):
    def test_allow_list_is_read_only(self):
        self.assertEqual(SAFE_FALLBACK_TOOLS, {
            "system_status", "battery_status", "weather_report", "web_search", "recall_memory"})
        for name in SAFE_FALLBACK_TOOLS:
            with self.subTest(name=name):
                self.assertEqual(security.tier_for(name, {}), security.TIER_SAFE)
                self.assertNotIn(name, security._DANGEROUS_ACTIONS)

    def test_schema_conversion(self):
        converted = gemini_schema_to_json({
            "type": "OBJECT",
            "properties": {
                "focus": {"type": "STRING", "enum": ["cpu", "ram"], "description": "d"},
                "items": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["focus"],
        })
        self.assertEqual(converted, {
            "type": "object",
            "properties": {
                "focus": {"type": "string", "enum": ["cpu", "ram"], "description": "d"},
                "items": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["focus"],
        })

    def test_specs_contain_only_allowed_tools_without_device(self):
        specs = build_tool_specs(DECLARATIONS + [DECLARATIONS[0], "junk"])
        self.assertEqual([spec["name"] for spec in specs], ["battery_status", "weather_report"])
        weather = specs[1]["input_schema"]
        self.assertEqual(weather["type"], "object")
        self.assertNotIn("device", weather["properties"])
        self.assertEqual(weather["required"], ["city"])

    def test_spec_is_dropped_if_security_no_longer_rates_it_safe(self):
        with patch.object(security, "tier_for", return_value=security.TIER_SENSITIVE):
            self.assertEqual(build_tool_specs(DECLARATIONS), [])

    def test_disallowed_tool_never_reaches_the_executor(self):
        execute = Mock()
        for name in ("open_app", "file_controller", "shutdown_jarvis", ""):
            text, is_error = execute_allowed_tool(name, {}, execute)
            self.assertTrue(is_error)
            self.assertIn("nothing was done", text)
        execute.assert_not_called()

    def test_executor_errors_are_reported_not_raised(self):
        text, is_error = execute_allowed_tool(
            "battery_status", {}, Mock(side_effect=RuntimeError("secret detail")))
        self.assertTrue(is_error)
        self.assertNotIn("secret detail", text)
        text, is_error = execute_allowed_tool("battery_status", "not-a-dict", Mock())
        self.assertTrue(is_error)
        text, is_error = execute_allowed_tool(
            "battery_status", {}, Mock(return_value="The battery status tool failed: x"))
        self.assertTrue(is_error)


class ToolLoopTests(unittest.TestCase):
    def test_tool_call_runs_through_executor_then_answers(self):
        client = ScriptedClient([
            response([text_block("Checking."), tool_block("battery_status", {})], "tool_use"),
            response([text_block("Your battery is at 80 percent.")]),
        ])
        result, execute = run(client)
        execute.assert_called_once_with("battery_status", {})
        self.assertEqual(result["text"], "Your battery is at 80 percent.")
        self.assertEqual(result["provider"], "claude")
        self.assertEqual(result["mode"], "cloud-tools")
        self.assertEqual(result["tools_run"], [{"tool": "battery_status", "status": "ok"}])
        second = client.requests[1]["messages"]
        self.assertEqual(second[1]["role"], "assistant")
        self.assertEqual(second[2], {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": "toolu_1",
            "content": "Battery at 80 percent, sir.", "is_error": False}]})

    def test_system_prompt_keeps_the_honesty_rule_and_lists_tools(self):
        client = ScriptedClient([response([text_block("Hello.")])])
        run(client)
        system = client.requests[0]["system"]
        self.assertTrue(system.startswith("BASE"))
        self.assertIn("Never claim", system)
        self.assertIn("battery_status, weather_report", system)
        self.assertEqual([t["name"] for t in client.requests[0]["tools"]],
                         ["battery_status", "weather_report"])

    def test_model_asking_for_a_write_tool_gets_an_error_result(self):
        client = ScriptedClient([
            response([tool_block("open_app", {"app_name": "notepad"})], "tool_use"),
            response([text_block("I can't open apps while Live is offline.")]),
        ])
        result, execute = run(client)
        execute.assert_not_called()
        tool_result = client.requests[1]["messages"][2]["content"][0]
        self.assertTrue(tool_result["is_error"])
        self.assertEqual(result["tools_run"], [{"tool": "open_app", "status": "error"}])

    def test_parallel_tool_calls_share_one_result_message(self):
        client = ScriptedClient([
            response([tool_block("battery_status", {}, "a"),
                      tool_block("weather_report", {"city": "Colombo"}, "b")], "tool_use"),
            response([text_block("Done checking.")]),
        ])
        run(client)
        results = client.requests[1]["messages"][2]["content"]
        self.assertEqual([r["tool_use_id"] for r in results], ["a", "b"])

    def test_tool_rounds_are_bounded(self):
        looping = [response([tool_block("battery_status", {})], "tool_use") for _ in range(3)]
        client = ScriptedClient(looping + [response([text_block("Final answer.")])])
        result, execute = run(client, max_rounds=3)
        self.assertEqual(execute.call_count, 3)
        self.assertEqual(len(client.requests), 4)
        self.assertEqual(client.requests[-1]["tool_choice"], {"type": "none"})
        self.assertNotIn("tool_choice", client.requests[0])
        self.assertEqual(result["text"], "Final answer.")

    def test_model_tier_follows_the_task_category(self):
        for task, model in ((None, ANTHROPIC_FAST_MODEL), ("simple", ANTHROPIC_FAST_MODEL),
                            ("coding", ANTHROPIC_REASONING_MODEL),
                            ("writing", ANTHROPIC_REASONING_MODEL)):
            client = ScriptedClient([response([text_block("ok")])])
            result, _ = run(client, task=task)
            self.assertEqual(client.requests[0]["model"], model)
            self.assertEqual(result["model"], model)

    def test_empty_answer_or_missing_setup_raises_for_caller_fallback(self):
        with self.assertRaises(RuntimeError):
            run(ScriptedClient([response([])]))
        with self.assertRaises(RuntimeError):
            run_claude_tool_fallback("x", system_prompt="", api_key="", declarations=DECLARATIONS,
                                     execute=Mock())
        with self.assertRaises(RuntimeError):
            run_claude_tool_fallback("x", system_prompt="", api_key=KEY,
                                     declarations=DECLARATIONS[2:], execute=Mock())

    def test_refusal_is_reported_honestly(self):
        result, _ = run(ScriptedClient([response([], "refusal")]))
        self.assertEqual(result["text"], "Claude declined that request.")


class QueryTextFallbackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def config(self, data):
        path = self.dir / "api_keys.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def router_factory(self):
        router = MagicMock()
        router.configured_key_status.return_value = {"claude": True}
        router.query.return_value = {"text": "text-only answer", "provider": "gemini"}
        return Mock(return_value=router), router

    def call(self, path, **kwargs):
        from core.provider_fallback import query_text_fallback
        factory, router = self.router_factory()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}), \
                patch.object(provider_settings, "_read", return_value={}), \
                redirect_stdout(io.StringIO()):
            result, configured = query_text_fallback(
                "How is my battery?", config_path=path, base_system_prompt="BASE",
                router_factory=factory, **kwargs)
        return result, router

    def test_uses_claude_tools_when_key_and_executor_exist(self):
        client = ScriptedClient([
            response([tool_block("battery_status", {})], "tool_use"),
            response([text_block("80 percent.")]),
        ])
        execute = Mock(return_value="Battery at 80 percent.")
        result, router = self.call(
            self.config({"anthropic_api_key": KEY}), tool_executor=execute,
            tool_declarations=DECLARATIONS,
            claude_client_factory=lambda _key, _timeout: client)
        self.assertEqual(result["text"], "80 percent.")
        router.query.assert_not_called()
        execute.assert_called_once()

    def test_without_a_claude_key_the_text_only_route_is_unchanged(self):
        factory = Mock()
        execute = Mock()
        result, router = self.call(self.config({"gemini_api_key": "g"}), tool_executor=execute,
                                   tool_declarations=DECLARATIONS,
                                   claude_client_factory=factory)
        self.assertEqual(result["text"], "text-only answer")
        factory.assert_not_called()
        execute.assert_not_called()
        self.assertIn("HYBRID TEXT FALLBACK RULES", router.query.call_args.kwargs["system_prompt"])

    def test_without_an_executor_the_text_only_route_is_unchanged(self):
        factory = Mock()
        result, _ = self.call(self.config({"anthropic_api_key": KEY}),
                              claude_client_factory=factory)
        self.assertEqual(result["text"], "text-only answer")
        factory.assert_not_called()

    def test_claude_failure_falls_back_to_text_only(self):
        broken = Mock(side_effect=RuntimeError("network down"))
        result, router = self.call(self.config({"anthropic_api_key": KEY}),
                                   tool_executor=Mock(), tool_declarations=DECLARATIONS,
                                   claude_client_factory=broken)
        self.assertEqual(result["text"], "text-only answer")
        router.query.assert_called_once()


class BrainEngineToolPassThroughTests(unittest.TestCase):
    def test_tool_arguments_are_forwarded_only_when_given(self):
        from core.brain_engine import BrainEngine
        query = Mock(return_value=({"text": "a", "provider": "claude",
                                    "tools_run": [{"tool": "battery_status", "status": "ok"}]},
                                   "claude"))
        result = BrainEngine(query_fn=query).respond("hi")
        self.assertNotIn("tool_executor", query.call_args.kwargs)
        executor = Mock()
        result = BrainEngine(query_fn=query, tool_executor=executor,
                             tool_declarations=DECLARATIONS).respond("hi")
        self.assertIs(query.call_args.kwargs["tool_executor"], executor)
        self.assertEqual(query.call_args.kwargs["tool_declarations"], DECLARATIONS)
        self.assertEqual(result["tools_run"], [{"tool": "battery_status", "status": "ok"}])


class LiveExecutorTests(unittest.TestCase):
    """The executor main.py hands to the fallback uses the normal dispatch path."""

    def make_live(self):
        import main

        class FakeRegistry:
            def __init__(self):
                self.runs = []

            def has(self, name):
                return name == "battery_status"

            def run(self, name, args, ctx):
                self.runs.append((name, args))
                return "Battery at 55 percent, sir."

            def meta(self, _name):
                return None

            def scheduling(self, _name):
                return None

            def get_tool_declarations(self):
                return [DECLARATIONS[0], DECLARATIONS[2]]

        live = main.JarvisLive.__new__(main.JarvisLive)
        live.ui = MagicMock()
        live.ui.muted = False
        live._action_registry = FakeRegistry()
        live._plugin_registry = FakeRegistry()
        live._plugin_registry.has = lambda _name: False
        return live

    def test_runs_through_security_guard_and_action_log(self):
        live = self.make_live()
        guarded = []

        def fake_guard(name, args, run_fn):
            guarded.append(name)
            return run_fn()

        with patch("core.runtime.live_tools.security.guard", side_effect=fake_guard), \
                patch("core.runtime.live_tools.action_log.record") as record, \
                redirect_stdout(io.StringIO()):
            result = live._run_fallback_tool("battery_status", {})
        self.assertEqual(result, "Battery at 55 percent, sir.")
        self.assertEqual(guarded, ["battery_status"])
        self.assertEqual(record.call_args.args[0], "battery_status")
        self.assertEqual(live._action_registry.runs, [("battery_status", {})])

    def test_refuses_names_outside_the_allow_list(self):
        live = self.make_live()
        with patch("core.runtime.live_tools.security.guard") as guard:
            result = live._run_fallback_tool("open_app", {"app_name": "x"})
        self.assertIn("not available", result)
        guard.assert_not_called()

    def test_declarations_are_filtered_to_the_allow_list(self):
        live = self.make_live()
        names = {d["name"] for d in live._fallback_tool_declarations()}
        self.assertTrue(names <= SAFE_FALLBACK_TOOLS)
        self.assertIn("battery_status", names)
        self.assertIn("system_status", names)
        self.assertNotIn("open_app", names)


if __name__ == "__main__":
    unittest.main()
