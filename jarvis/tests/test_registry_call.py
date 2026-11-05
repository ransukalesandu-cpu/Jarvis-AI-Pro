"""Registry-aware planning, PR B: the ``registry_call`` plan step (local tools only)."""
from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path

JARVIS_DIR = Path(__file__).resolve().parents[1]
for p in (JARVIS_DIR, JARVIS_DIR.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from jarvis.agent.executor import (  # noqa: E402
    ExecutionContext, StepExecutor, StepRefError, resolve_step_refs,
)
from jarvis.agent.models import StepKind, StepState, Task, TaskStep  # noqa: E402
from jarvis.agent.planner import TaskPlanner, registry_planning_enabled  # noqa: E402
from jarvis.agent.policy import ExecutionPolicy, PolicyEngine, Risk, classify_step  # noqa: E402
from jarvis.core.tool_catalog import build_catalog, schema_errors  # noqa: E402
from jarvis.core.tool_runtime import ToolMeta  # noqa: E402


class FakeReg:
    def __init__(self, decls, metas=None):
        self._d, self._m = decls, metas or {}

    def get_tool_declarations(self):
        return list(self._d)

    def meta(self, name):
        return self._m.get(name)


def tool(name, desc, props=None, required=None):
    params = {"type": "OBJECT", "properties": props or {}}
    if required:
        params["required"] = required
    return {"name": name, "description": desc, "parameters": params}


def make_catalog():
    decls = [
        tool("weather_report", "Get the weather forecast for a city.",
             {"city": {"type": "STRING"}}, ["city"]),
        tool("send_message", "Send a text message to a contact.",
             {"to": {"type": "STRING"}, "text": {"type": "STRING"}}, ["to", "text"]),
        tool("calendar_tool", "Read or add calendar events.",
             {"action": {"type": "STRING", "enum": ["read", "add"]}}, ["action"]),
        tool("autonomous_task", "Start a long autonomous task.", {"action": {"type": "STRING"}}),
        tool("big_job", "Render a huge video in the background.", {}),
        tool("open_app", "Open an application by name.", {"app": {"type": "STRING"}}, ["app"]),
        tool("count", "Count things.", {"n": {"type": "INTEGER"}}),
    ]
    metas = {
        "weather_report": ToolMeta(risk="read"),
        "send_message": ToolMeta(risk="write"),
        "calendar_tool": ToolMeta(risk="destructive"),
        "big_job": ToolMeta(risk="write", long_running=True),
    }
    return build_catalog(registries=[FakeReg(decls, metas)])


def planner(ask=None, enabled=True, catalog=None, workspace=None, **kw):
    cat = catalog if catalog is not None else make_catalog()
    return TaskPlanner(ask=ask, workspace=workspace or Path.cwd(),
                       catalog_provider=lambda: cat,
                       registry_enabled=lambda: enabled, **kw)


def plan_json(steps):
    return json.dumps({"criteria": ["done"], "steps": steps})


class SearchTests(unittest.TestCase):
    def test_ranks_by_name_and_description_and_caps_k(self):
        cat = make_catalog()
        top = [e.name for e in cat.search("what is the weather forecast in Colombo", 2)]
        self.assertEqual(top[0], "weather_report")
        self.assertEqual(len(top), 2)

    def test_excludes_recursion_and_long_running(self):
        names = [e.name for e in make_catalog().search("start a task and render video", 20)]
        self.assertNotIn("autonomous_task", names)
        self.assertNotIn("big_job", names)

    def test_pads_when_nothing_matches(self):
        names = [e.name for e in make_catalog().search("සිංහල ඉල්ලීමක්", 3)]
        self.assertEqual(len(names), 3)

    def test_schema_errors(self):
        e = make_catalog().get("calendar_tool")
        self.assertEqual(schema_errors(e, {"action": "read"}), [])
        self.assertTrue(schema_errors(e, {}))                       # missing required
        self.assertTrue(schema_errors(e, {"action": "nuke"}))       # enum
        self.assertTrue(schema_errors(e, {"action": "read", "x": 1}))   # unknown
        c = make_catalog().get("count")
        self.assertTrue(schema_errors(c, {"n": True}))              # bool is not an int
        self.assertTrue(schema_errors(c, {"n": "3"}))


class PlannerTests(unittest.TestCase):
    def test_flag_default_is_off(self):
        import os
        old = os.environ.pop("JARVIS_REGISTRY_PLANNING", None)
        try:
            self.assertFalse(registry_planning_enabled())
            os.environ["JARVIS_REGISTRY_PLANNING"] = "1"
            self.assertTrue(registry_planning_enabled())
        finally:
            os.environ.pop("JARVIS_REGISTRY_PLANNING", None)
            if old is not None:
                os.environ["JARVIS_REGISTRY_PLANNING"] = old

    def test_prompt_lists_tools_only_when_enabled(self):
        seen = {}
        planner(ask=lambda p: seen.setdefault("on", p) and plan_json(
            [{"title": "n", "kind": "note"}]), enabled=True).plan("check the weather")
        planner(ask=lambda p: seen.setdefault("off", p) and plan_json(
            [{"title": "n", "kind": "note"}]), enabled=False).plan("check the weather")
        self.assertIn("registry_call", seen["on"])
        self.assertIn("weather_report(city*)", seen["on"])
        self.assertNotIn("registry_call", seen["off"])

    def test_valid_step_is_parsed(self):
        raw = plan_json([{"title": "Weather", "kind": "registry_call", "tool": "weather_report",
                          "args": {"city": "Colombo", "device": "laptop"}}])
        plan = planner().parse(raw, "x", catalog=make_catalog())
        step = plan.steps[0]
        self.assertIs(step.kind, StepKind.REGISTRY_CALL)
        self.assertEqual((step.tool, step.args, step.tool_risk),
                         ("weather_report", {"city": "Colombo"}, "read"))
        self.assertFalse(step.consequential)

    def test_rejections(self):
        cat = make_catalog()

        def only(step):
            return planner().parse(plan_json([step, {"title": "n", "kind": "note"}]),
                                   "x", catalog=cat)

        bad = [
            {"kind": "registry_call", "tool": "nope", "args": {}},
            {"kind": "registry_call", "tool": "autonomous_task", "args": {}},
            {"kind": "registry_call", "tool": "big_job", "args": {}},
            {"kind": "registry_call", "tool": "weather_report", "args": {}},
            {"kind": "registry_call", "tool": "weather_report", "args": {"city": 5}},
            {"kind": "registry_call", "tool": "weather_report", "args": {"city": "x", "evil": 1}},
            {"kind": "registry_call", "tool": "weather_report", "args": "city=x"},
            {"kind": "registry_call", "tool": "weather_report",
             "args": {"city": "x", "device": "phone"}},
        ]
        for step in bad:
            step.setdefault("title", "t")
            plan = only(step)
            self.assertEqual([s.kind for s in plan.steps], [StepKind.NOTE], step)
            self.assertTrue(plan.warnings, step)

    def test_dropped_when_catalog_missing(self):
        raw = plan_json([{"title": "a", "kind": "registry_call", "tool": "weather_report",
                          "args": {"city": "x"}}, {"title": "n", "kind": "note"}])
        plan = planner().parse(raw, "x")          # no catalog -> flag off / no provider
        self.assertEqual([s.kind for s in plan.steps], [StepKind.NOTE])

    def test_step_ref_adds_dependency_and_is_rewritten_to_ids(self):
        raw = plan_json([
            {"title": "B", "kind": "registry_call", "tool": "send_message",
             "args": {"to": "Ann", "text": "Forecast: {{step:1}}"}},
            {"title": "A", "kind": "registry_call", "tool": "weather_report",
             "args": {"city": "Colombo"}},
        ])
        plan = planner().parse(raw, "x", catalog=make_catalog())
        titles = [s.title for s in plan.steps]
        self.assertEqual(titles, ["A", "B"])                 # sorted so A runs first
        a, b = plan.steps
        self.assertEqual(b.depends_on, [0])
        self.assertEqual(b.args["text"], "Forecast: {{step:%s}}" % a.id)
        self.assertTrue(b.consequential)                     # earlier output flows into a write tool

    def test_bad_refs_drop_the_step(self):
        cat = make_catalog()
        for ref in ("{{step:9}}", "{{step:0}}", "{{step:abc}}"):
            raw = plan_json([{"title": "S", "kind": "registry_call", "tool": "send_message",
                              "args": {"to": "a", "text": ref}},
                             {"title": "n", "kind": "note"}])
            plan = planner().parse(raw, "x", catalog=cat)
            self.assertEqual([s.title for s in plan.steps], ["n"], ref)

    def test_ref_to_dropped_step_drops_dependent(self):
        raw = plan_json([
            {"title": "bad", "kind": "registry_call", "tool": "nope", "args": {}},
            {"title": "S", "kind": "registry_call", "tool": "send_message",
             "args": {"to": "a", "text": "{{step:0}}"}},
            {"title": "n", "kind": "note"},
        ])
        plan = planner().parse(raw, "x", catalog=make_catalog())
        self.assertEqual([s.title for s in plan.steps], ["n"])

    def test_model_failure_falls_back_to_deterministic_plan(self):
        def boom(_p):
            raise RuntimeError("provider down")
        plan = planner(ask=boom).plan("run the tests")
        self.assertTrue(plan.steps)
        self.assertTrue(any("deterministic" in w for w in plan.warnings))

    def test_cache_key_changes_with_offered_tools(self):
        calls = []
        p = planner(ask=lambda pr: calls.append(pr) or plan_json([{"title": "n", "kind": "note"}]))
        p.plan("weather in Colombo")
        p._registry_enabled = lambda: False
        p.plan("weather in Colombo")
        self.assertEqual(len(calls), 2)                     # not served from the other cache entry


class PolicyTests(unittest.TestCase):
    def _step(self, risk):
        return TaskStep(title="t", kind=StepKind.REGISTRY_CALL, tool="x", tool_risk=risk)

    def test_classification_fails_closed(self):
        self.assertIs(classify_step(self._step("read"))[0], Risk.READ)
        self.assertIs(classify_step(self._step("write"))[0], Risk.WRITE)
        self.assertIs(classify_step(self._step("destructive"))[0], Risk.CONSEQUENTIAL)
        self.assertIs(classify_step(self._step(""))[0], Risk.CONSEQUENTIAL)

    def test_consequential_needs_owner(self):
        eng = PolicyEngine(ExecutionPolicy(allowed_risk=Risk.CONSEQUENTIAL), owner_check=lambda: False)
        self.assertFalse(eng.check(self._step("")).allowed)
        self.assertTrue(eng.check(self._step("read")).allowed)
        eng_ok = PolicyEngine(ExecutionPolicy(allowed_risk=Risk.CONSEQUENTIAL), owner_check=lambda: True)
        decision = eng_ok.check(self._step("destructive"))
        self.assertTrue(decision.allowed and decision.requires_approval)

    def test_default_policy_refuses_consequential(self):
        eng = PolicyEngine(ExecutionPolicy(allowed_risk=Risk.WRITE), owner_check=lambda: True)
        self.assertFalse(eng.check(self._step("destructive")).allowed)


class ExecutorTests(unittest.TestCase):
    def _ctx(self, task, runner, approve=True):
        return ExecutionContext(task=task, workspace=Path.cwd(), cancel=threading.Event(),
                                pause=threading.Event(), tool_runner=runner,
                                request_approval=lambda s, d: approve,
                                policy=ExecutionPolicy(allowed_risk=Risk.CONSEQUENTIAL))

    def _executor(self):
        return StepExecutor(engine=PolicyEngine(
            ExecutionPolicy(allowed_risk=Risk.CONSEQUENTIAL), owner_check=lambda: True))

    def test_end_to_end_two_steps_with_substitution(self):
        raw = plan_json([
            {"title": "Weather", "kind": "registry_call", "tool": "weather_report",
             "args": {"city": "Colombo"}},
            {"title": "Tell Ann", "kind": "registry_call", "tool": "send_message",
             "args": {"to": "Ann", "text": "It is: {{step:0}}"}},
        ])
        plan = planner().parse(raw, "x", catalog=make_catalog())
        task = Task(objective="x")
        task.set_plan(plan.steps)
        calls = []

        def runner(name, args, timeout):
            calls.append((name, dict(args), timeout))
            return "31C and sunny" if name == "weather_report" else "Message sent."

        ex, ctx = self._executor(), self._ctx(task, runner)
        for step in task.steps:
            result = ex.execute(step, ctx)
            self.assertTrue(result.ok, result.error)
            step.mark(StepState.COMPLETED, output=result.output)
        self.assertEqual(calls[0][:2], ("weather_report", {"city": "Colombo"}))
        self.assertEqual(calls[1][:2], ("send_message", {"to": "Ann", "text": "It is: 31C and sunny"}))

    def test_unapproved_consequential_step_does_not_run(self):
        step = TaskStep(title="t", kind=StepKind.REGISTRY_CALL, tool="calendar_tool",
                        args={"action": "add"}, tool_risk="destructive")
        task = Task(objective="x", steps=[step])
        ran = []
        result = self._executor().execute(step, self._ctx(task, lambda *a: ran.append(a), approve=False))
        self.assertTrue(result.blocked)
        self.assertEqual(ran, [])

    def test_no_runner_is_blocked(self):
        step = TaskStep(title="t", kind=StepKind.REGISTRY_CALL, tool="weather_report",
                        args={"city": "x"}, tool_risk="read")
        result = self._executor().execute(step, self._ctx(Task(objective="x", steps=[step]), None))
        self.assertTrue(result.blocked)

    def test_tool_failure_text_is_a_failure(self):
        step = TaskStep(title="t", kind=StepKind.REGISTRY_CALL, tool="weather_report",
                        args={"city": "x"}, tool_risk="read")
        ctx = self._ctx(Task(objective="x", steps=[step]),
                        lambda *a: "Tool 'weather_report' failed: boom")
        result = self._executor().execute(step, ctx)
        self.assertFalse(result.ok)
        self.assertFalse(result.blocked)

    def test_resolve_refs_errors(self):
        done = TaskStep(title="d", output="hello")
        pending = TaskStep(title="p")
        task = Task(objective="x", steps=[done, pending])
        done.state = StepState.COMPLETED
        self.assertEqual(resolve_step_refs({"a": ["x {{step:%s}}" % done.id]}, task),
                         {"a": ["x hello"]})
        with self.assertRaises(StepRefError):
            resolve_step_refs("{{step:%s}}" % pending.id, task)
        with self.assertRaises(StepRefError):
            resolve_step_refs("{{step:nope}}", task)

    def test_ref_output_is_capped(self):
        done = TaskStep(title="d", output="z" * 5000)
        done.state = StepState.COMPLETED
        out = resolve_step_refs("{{step:%s}}" % done.id, Task(objective="x", steps=[done]))
        self.assertEqual(len(out), 2000)


class ModelTests(unittest.TestCase):
    def test_step_roundtrip_keeps_tool_fields(self):
        s = TaskStep(title="t", kind=StepKind.REGISTRY_CALL, tool="a", args={"k": "v"}, tool_risk="read")
        back = TaskStep.from_dict(s.to_dict())
        self.assertEqual((back.kind, back.tool, back.args, back.tool_risk),
                         (StepKind.REGISTRY_CALL, "a", {"k": "v"}, "read"))

    def test_old_checkpoints_without_new_fields_still_load(self):
        data = TaskStep(title="t").to_dict()
        for key in ("tool", "args", "tool_risk"):
            data.pop(key)
        back = TaskStep.from_dict(data)
        self.assertEqual((back.tool, back.args, back.tool_risk), ("", {}, ""))


if __name__ == "__main__":
    unittest.main()
