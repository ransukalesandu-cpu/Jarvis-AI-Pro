"""Hybrid Phase 3: read-only tools for the text fallback. No network: fakes."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import claude_usage
from core.fallback_tools import (SAFE_FALLBACK_TOOLS, TOOL_RULES, FallbackToolbox,
                                 answer_with_tools, gemini_to_json_schema)


class FakeRegistry:
    def __init__(self, names=("battery_status", "weather_report", "web_search", "open_app")):
        self.names = set(names)
        self.ran = []

    def has(self, name):
        return name in self.names

    def get_tool_declarations(self):
        return [{"name": n, "description": f"{n} tool",
                 "parameters": {"type": "OBJECT", "properties": {
                     "city": {"type": "STRING"}, "device": {"type": "STRING"}}}}
                for n in sorted(self.names)]

    def run(self, name, args, ctx):
        self.ran.append((name, dict(args)))
        return f"{name} result"


def _block(kind, **kw):
    return SimpleNamespace(type=kind, **kw)


def _resp(content, stop):
    return SimpleNamespace(content=content, stop_reason=stop, model="claude-haiku-5-5",
                           usage=SimpleNamespace(input_tokens=5, output_tokens=7))


class FakeClaude:
    """Replays a script of responses and records every request."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.requests.append(kw)
        return self.script.pop(0)


def _toolbox(**kw):
    guard_calls, log_calls = [], []

    def guard(name, args, run):
        guard_calls.append(name)
        return run()

    def log(name, args, result, **k):
        log_calls.append((name, k.get("risk"), k.get("status")))
    box = FallbackToolbox(kw.pop("registry", FakeRegistry()), guard=guard, log=log, **kw)
    return box, guard_calls, log_calls


class ToolboxTests(unittest.TestCase):
    def test_only_read_only_tools_are_offered(self):
        box, _, _ = _toolbox(system_status=lambda: "cpu 5%")
        names = [t["name"] for t in box.tools()]
        self.assertEqual(set(names), {"system_status", "battery_status", "weather_report", "web_search"})
        self.assertNotIn("open_app", names)                       # in the registry, not allowed
        for t in box.tools():
            self.assertNotIn("device", t["input_schema"]["properties"])
        self.assertTrue(set(names) <= set(SAFE_FALLBACK_TOOLS))

    def test_recall_memory_needs_memory_access(self):
        box, _, _ = _toolbox(recall=lambda q: "fact")
        self.assertNotIn("recall_memory", box.available())
        box, _, _ = _toolbox(recall=lambda q: f"fact about {q}", memory_enabled=True)
        self.assertIn("recall_memory", box.available())
        self.assertEqual(box.run("recall_memory", {"query": "car"}), "fact about car")

    def test_runs_go_through_guard_and_action_log(self):
        reg = FakeRegistry()
        box, guards, logs = _toolbox(registry=reg)
        self.assertEqual(box.run("weather_report", {"city": "Colombo", "device": "phone"}),
                         "weather_report result")
        self.assertEqual(reg.ran, [("weather_report", {"city": "Colombo"})])
        self.assertEqual(guards, ["weather_report"])
        self.assertEqual(logs, [("weather_report", "read", "ok")])

    def test_disallowed_tool_never_runs(self):
        reg = FakeRegistry()
        box, guards, logs = _toolbox(registry=reg)
        out = box.run("open_app", {"app": "notepad"})
        self.assertIn("not available", out)
        self.assertEqual(reg.ran, [])
        self.assertEqual(guards, [])
        self.assertEqual(logs[0][2], "error")

    def test_guard_denial_is_returned(self):
        reg = FakeRegistry()
        box = FallbackToolbox(reg, guard=lambda n, a, run: "JARVIS Privacy Lock is active.",
                              log=lambda *a, **k: None)
        self.assertIn("Privacy Lock", box.run("battery_status", {}))
        self.assertEqual(reg.ran, [])

    def test_schema_conversion(self):
        out = gemini_to_json_schema({"type": "OBJECT", "properties": {
            "q": {"type": "STRING", "description": "d"},
            "items": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["q"]})
        self.assertEqual(out["type"], "object")
        self.assertEqual(out["properties"]["q"], {"type": "string", "description": "d"})
        self.assertEqual(out["properties"]["items"]["items"], {"type": "string"})
        self.assertEqual(out["required"], ["q"])


class LoopTests(unittest.TestCase):
    def setUp(self):
        claude_usage.reset()
        p = mock.patch("core.fallback_tools.get_provider_api_key", return_value="sk-x")
        p.start()
        self.addCleanup(p.stop)

    def test_tool_loop_runs_a_tool_and_answers(self):
        box, guards, _ = _toolbox()
        fake = FakeClaude([
            _resp([_block("tool_use", id="t1", name="battery_status", input={})], "tool_use"),
            _resp([_block("text", text="Battery is at 80 percent.")], "end_turn"),
        ])
        out = answer_with_tools("how's my battery", "BASE", box, client_factory=lambda t: fake)
        self.assertEqual(out["text"], "Battery is at 80 percent.")
        self.assertEqual(out["tools_ran"], ["battery_status"])
        self.assertEqual(guards, ["battery_status"])
        first = fake.requests[0]
        self.assertTrue(first["system"].startswith("BASE"))
        self.assertIn("Never say you did something unless a tool call", first["system"])
        self.assertEqual(first["model"], "claude-haiku-5-5")       # simple question: fast model
        result_msg = fake.requests[1]["messages"][-1]["content"][0]
        self.assertEqual((result_msg["type"], result_msg["tool_use_id"]), ("tool_result", "t1"))
        self.assertEqual(claude_usage.session_usage()["calls"], 2)

    def test_model_asks_for_a_forbidden_tool(self):
        reg = FakeRegistry()
        box, _, _ = _toolbox(registry=reg)
        fake = FakeClaude([
            _resp([_block("tool_use", id="t1", name="open_app", input={"app": "x"})], "tool_use"),
            _resp([_block("text", text="I can't open apps while voice is offline.")], "end_turn"),
        ])
        out = answer_with_tools("open notepad", "", box, client_factory=lambda t: fake)
        self.assertEqual(reg.ran, [])
        self.assertIn("not available", fake.requests[1]["messages"][-1]["content"][0]["content"])
        self.assertIn("can't open apps", out["text"])

    def test_heavy_tasks_use_the_strong_model_and_steps_are_bounded(self):
        box, _, _ = _toolbox()
        loop = [_resp([_block("tool_use", id=f"t{i}", name="web_search", input={})], "tool_use")
                for i in range(3)]
        fake = FakeClaude(loop)
        out = answer_with_tools("write a python function to parse csv", "", box,
                                client_factory=lambda t: fake, max_steps=3)
        self.assertEqual(fake.requests[0]["model"], "claude-sonnet-5-5")
        self.assertIn("couldn't finish", out["text"])
        self.assertEqual(len(fake.requests), 3)

    def test_rules_text(self):
        for phrase in ("read-only", "cannot open apps", "Never say you did something"):
            self.assertIn(phrase, TOOL_RULES)


class FallbackIntegrationTests(unittest.TestCase):
    def _config(self, data):
        path = Path(tempfile.mkdtemp()) / "api_keys.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    class Router:
        made = []

        def __init__(self, **kw):
            pass

        def configured_key_status(self):
            return {"gemini": True}

        def query(self, text, **kw):
            FallbackIntegrationTests.Router.made.append(kw["system_prompt"])
            return {"text": "text-only answer", "provider": "gemini"}

    def test_uses_tools_with_a_claude_key(self):
        from core.provider_fallback import query_text_fallback
        box, _, _ = _toolbox()
        fake = FakeClaude([_resp([_block("text", text="Hello from Claude.")], "end_turn")])
        with mock.patch("core.fallback_tools.get_provider_api_key", return_value="sk-x"):
            result, configured = query_text_fallback(
                "hi", config_path=self._config({"anthropic_api_key": "sk-x"}),
                base_system_prompt="s", router_factory=self.Router, toolbox=box,
                tool_client_factory=lambda t: fake)
        self.assertEqual((result["text"], result["provider"]), ("Hello from Claude.", "claude"))
        self.assertNotIn("sk-x", configured)

    def test_falls_back_to_text_only_when_claude_fails(self):
        from core.provider_fallback import query_text_fallback
        box, _, _ = _toolbox()

        def broken(t):
            raise ConnectionError("down")
        self.Router.made.clear()
        with mock.patch("core.fallback_tools.get_provider_api_key", return_value="sk-x"):
            result, _ = query_text_fallback(
                "hi", config_path=self._config({"anthropic_api_key": "sk-x"}),
                base_system_prompt="s", router_factory=self.Router, toolbox=box,
                tool_client_factory=broken)
        self.assertEqual(result["text"], "text-only answer")
        self.assertIn("no live tools", self.Router.made[0])          # the old honesty rule

    def test_without_toolbox_or_key_nothing_changes(self):
        from core.provider_fallback import query_text_fallback
        box, _, _ = _toolbox()
        with mock.patch("core.provider_fallback._env_claude_key", return_value=False):
            result, _ = query_text_fallback("hi", config_path=self._config({}),
                                            base_system_prompt="s", router_factory=self.Router,
                                            toolbox=box)
        self.assertEqual(result["text"], "text-only answer")
        result, _ = query_text_fallback("hi", config_path=self._config({"anthropic_api_key": "k"}),
                                        base_system_prompt="s", router_factory=self.Router)
        self.assertEqual(result["text"], "text-only answer")


if __name__ == "__main__":
    unittest.main()


class BrainEngineContractTests(unittest.TestCase):
    def test_toolbox_reaches_the_provider_through_query_fn_only(self):
        import functools

        from core.brain_engine import BrainEngine
        seen = {}

        def query_fn(prompt, **kw):
            seen.update(kw)
            return {"text": "ok", "provider": "claude", "tools_ran": ["battery_status"]}, "claude"
        box, _, _ = _toolbox()
        brain = BrainEngine(query_fn=functools.partial(query_fn, toolbox=box))
        out = brain.respond("how's the battery")
        self.assertIs(seen["toolbox"], box)
        self.assertEqual(out["tools_ran"], ["battery_status"])
        self.assertFalse(hasattr(brain, "run"))           # still answers only
