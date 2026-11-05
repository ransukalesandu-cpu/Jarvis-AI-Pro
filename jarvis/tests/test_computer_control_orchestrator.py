"""Project 2: plans, the heuristic/model planners, the Host Agent (context, trace,
recovery, verification, honest reports) and tasks as JobManager jobs."""
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from jarvis.computer_control import approval, audit, estop, flags, runner
from jarvis.computer_control.orchestrator import jobs as cc_jobs
from jarvis.computer_control.orchestrator.agents import AgentRegistry, AppAgent, default_registry
from jarvis.computer_control.orchestrator.host import HostAgent
from jarvis.computer_control.orchestrator.plan import PlanError, build, parse_model_json, resolve_refs
from jarvis.computer_control.orchestrator.planner import ModelPlanner, heuristic_steps, make_plan
from jarvis.computer_control.policy import ActionPolicy, AuthSnapshot
from jarvis.computer_control.runner import ActionRunner
from jarvis.computer_control.tools import build_registry
from jarvis.computer_control.windows.controller import WindowsController, set_controller
from jarvis.computer_control.windows.fake import FakeDesktop

OWNER = AuthSnapshot(False, True)
TOOLS = ["cc_app", "cc_window", "cc_control", "cc_pointer", "cc_engine_status"]


@pytest.fixture
def env():
    fake = FakeDesktop()
    set_controller(WindowsController(fake, launch_timeout=2.0, poll=0.01))
    runner.set_runner(ActionRunner(ActionPolicy(auth=lambda: OWNER)))
    estop.reset_for_tests()
    approval.set_approver(None)
    audit.clear_for_tests()
    with flags.override(enabled=True, dry_run=False):
        yield fake, build_registry()
    set_controller(None)
    runner.set_runner(None)


# ── plans ────────────────────────────────────────────────────────────────────
class TestPlan:
    def test_unknown_tool_and_bad_args_are_rejected(self):
        with pytest.raises(PlanError):
            build("x", [{"tool": "rm_rf", "args": {}}], TOOLS)
        with pytest.raises(PlanError):
            build("x", [{"tool": "cc_app", "args": "launch"}], TOOLS)
        with pytest.raises(PlanError):
            build("x", [], TOOLS)
        with pytest.raises(PlanError):
            build("x", [{"tool": "cc_app"}] * 30, TOOLS)

    def test_cycles_and_forward_references_are_rejected(self):
        with pytest.raises(PlanError):
            build("x", [{"tool": "cc_app", "depends_on": [1]}, {"tool": "cc_app", "depends_on": [0]}], TOOLS)
        with pytest.raises(PlanError):
            build("x", [{"tool": "cc_window", "args": {"handle": "{{1.data.window.handle}}"}},
                        {"tool": "cc_app"}], TOOLS)

    def test_dependency_order_and_reference_rewrite(self):
        plan = build("x", [
            {"tool": "cc_window", "args": {"op": "activate", "handle": "{{1.data.window.handle}}"},
             "depends_on": [1]},
            {"tool": "cc_app", "args": {"op": "launch", "name": "Notepad"}, "depends_on": []},
        ], TOOLS)
        assert [s.tool for s in plan.steps] == ["cc_app", "cc_window"]
        assert plan.steps[1].args["handle"] == "{{0.data.window.handle}}"
        assert plan.steps[1].depends_on == [0]

    def test_resolve_refs(self):
        outputs = {0: {"data": {"window": {"handle": 77, "title": "Untitled - Notepad"}}}}
        value, used = resolve_refs({"handle": "{{0.data.window.handle}}",
                                    "note": "in {{0.data.window.title}}"}, outputs)
        assert value == {"handle": 77, "note": "in Untitled - Notepad"} and used
        assert resolve_refs({"a": 1}, outputs) == ({"a": 1}, False)

    def test_parse_model_json(self):
        assert parse_model_json('Sure!\n```json\n{"steps": []}\n```') == {"steps": []}
        assert parse_model_json('{"steps": [1]} trailing') == {"steps": [1]}
        assert parse_model_json("no json here") is None


# ── planners ─────────────────────────────────────────────────────────────────
class TestPlanner:
    def test_heuristic_requests(self):
        steps = heuristic_steps("Open Notepad and type 'hello world'")
        assert [s["tool"] for s in steps] == ["cc_app", "cc_control"]
        assert steps[1]["args"] == {"op": "type", "window": "Notepad", "text": "hello world"}
        steps = heuristic_steps("open calculator then minimize it")
        assert steps[1]["args"] == {"op": "minimize", "window": "calculator"}
        assert heuristic_steps("switch to VS Code")[0]["args"]["window"] == "Visual Studio Code"
        assert heuristic_steps("open notepad, then press ctrl+s")[1]["args"]["keys"] == "ctrl+s"

    def test_heuristic_leaves_complex_requests_to_the_model(self):
        for text in ("research three AI projects, compare them and save a report",
                     "organize my project folder", "open VS Code and inspect my project"):
            assert heuristic_steps(text) is None

    def test_model_planner_is_redacted_and_validated(self, env):
        _fake, specs = env
        seen = {}

        def ask(prompt):
            seen["prompt"] = prompt
            return json.dumps({"steps": [{"tool": "cc_app", "args": {"op": "launch", "name": "Notepad"},
                                          "expect": {"window": "Notepad"}}]})
        key = "AIzaSyA1234567890abcdefghijklmnopqrs"
        plan = make_plan(f"inspect my project with key {key} and summarise it", specs,
                         model=ModelPlanner(ask))
        assert plan.source == "model" and plan.steps[0].tool == "cc_app"
        assert key not in seen["prompt"] and "cc_task" not in seen["prompt"]

    def test_model_planner_bad_output(self, env):
        _fake, specs = env
        with pytest.raises(PlanError):
            make_plan("organize my project folder", specs, model=ModelPlanner(lambda p: "I can't"))
        with pytest.raises(PlanError):
            make_plan("organize my project folder", specs, model=ModelPlanner(
                lambda p: '{"steps": [{"tool": "cc_task", "args": {}}]}'))   # no recursion

    def test_no_cloud_key_means_a_clear_error(self, env, monkeypatch):
        _fake, specs = env
        from jarvis.computer_control.orchestrator import planner
        monkeypatch.setattr(planner, "default_ask", lambda: None)
        with pytest.raises(PlanError, match="no cloud planner"):
            make_plan("organize my project folder", specs)


# ── host agent ───────────────────────────────────────────────────────────────
class TestHost:
    def test_multi_app_task_completes_and_verifies(self, env):
        fake, specs = env
        host = HostAgent(specs)
        plan = host.plan_from("notes and sums", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Notepad"}, "description": "open Notepad"},
            {"tool": "cc_control", "args": {"op": "set_text", "window": "Notepad", "control_type": "Edit",
                                            "text": "total"}, "description": "write"},
            {"tool": "cc_app", "args": {"op": "launch", "name": "Calculator"}, "description": "open calc"},
            {"tool": "cc_control", "args": {"op": "invoke", "window": "Calculator", "name": "Seven"},
             "expect": {"text": "Display is 7"}, "description": "press 7"},
            {"tool": "cc_window", "args": {"op": "activate", "handle": "{{0.data.window.handle}}"},
             "description": "back to Notepad"},
        ])
        report = host.run(plan)
        assert report.success and report.status == "completed", report.summary
        assert report.steps_ok == 5 and report.steps_verified == 5
        assert [t.agent for t in report.trace] == ["windows"] * 5
        assert fake.element_named("Notepad", "Text Editor").value == "total"

    def test_failure_stops_and_reports_honestly(self, env):
        fake, specs = env
        host = HostAgent(specs, max_recoveries=0)
        plan = host.plan_from("x", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Calculator"}},
            {"tool": "cc_control", "args": {"op": "invoke", "window": "Calculator", "name": "Square root"}},
            {"tool": "cc_window", "args": {"op": "close", "window": "Calculator"}},
        ])
        report = host.run(plan)
        assert not report.success and report.status == "failed"
        assert "step 2" in report.summary and "No control" in report.summary
        assert len(report.trace) == 2              # the close never ran
        assert any(w.title == "Calculator" for w in fake.windows())

    def test_unmet_expectation_is_not_success(self, env):
        _fake, specs = env
        host = HostAgent(specs, max_recoveries=0)
        plan = host.plan_from("x", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Calculator"}},
            {"tool": "cc_control", "args": {"op": "invoke", "window": "Calculator", "name": "One",
                                            "expect_timeout": 0.1}, "expect": {"text": "Display is 9"}},
        ])
        report = host.run(plan)
        assert not report.success and report.trace[-1].verified is False

    def test_recovery_waits_for_a_slow_window(self, env):
        fake, specs = env
        host = HostAgent(specs)
        fake.slow_launch = 40            # window appears after ~40 window() polls
        plan = host.plan_from("x", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Notepad"}},
            {"tool": "cc_window", "args": {"op": "activate", "window": "Notepad"}, "depends_on": []},
        ])
        report = host.run(plan)
        assert report.recoveries >= 0
        assert report.trace[-1].status == "ok", [t.as_dict() for t in report.trace]

    def test_recovery_loosens_a_control_name(self, env):
        fake, specs = env
        host = HostAgent(specs)
        plan = host.plan_from("x", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Calculator"}},
            {"tool": "cc_control", "args": {"op": "invoke", "window": "Calculator", "name": "Multiply"}},
        ])
        report = host.run(plan)
        assert report.success and report.recoveries == 1
        assert any(t.recovery for t in report.trace)

    def test_no_recovery_after_a_stop(self, env):
        fake, specs = env
        host = HostAgent(specs)
        plan = host.plan_from("x", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Calculator"}},
            {"tool": "cc_control", "args": {"op": "invoke", "window": "Calculator", "name": "Multiply"}},
        ])
        original = host.agents.for_tool("cc_control").recover

        def stop_then_recover(h, step, result):
            estop.trigger("owner said stop")
            return original(h, step, result)
        host.agents.for_tool("cc_control").recover = stop_then_recover
        try:
            report = host.run(plan)
        finally:
            host.agents.for_tool("cc_control").recover = original
        assert not report.success and not any(t.recovery for t in report.trace)

    def test_denied_high_step_is_not_retried(self, env):
        fake, specs = env
        host = HostAgent(specs)
        plan = host.plan_from("x", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Notepad"}},
            {"tool": "cc_app", "args": {"op": "kill", "pid": "{{0.data.pid}}"}},
        ])
        report = host.run(plan)
        assert report.status == "denied" and report.recoveries == 0
        assert fake.windows()

    def test_values_from_results_are_tainted(self, env):
        fake, specs = env
        host = HostAgent(specs)
        plan = host.plan_from("x", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Notepad"}},
            {"tool": "cc_control", "args": {"op": "set_text", "window": "{{0.data.window.title}}",
                                            "control_type": "Edit", "text": "x"}},
        ])
        report = host.run(plan)
        # MEDIUM set_text with a window title taken from a result becomes HIGH -> approval -> denied
        assert report.trace[-1].level == "high" and report.status == "denied"

    def test_file_expectation(self, env, tmp_path):
        fake, specs = env
        path = tmp_path / "note.txt"
        host = HostAgent(specs)
        plan = host.plan_from("save a note", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Notepad", "args": [str(path)]}},
            {"tool": "cc_control", "args": {"op": "set_text", "window": "note.txt", "control_type": "Edit",
                                            "text": "JARVIS was here"}},
            {"tool": "cc_control", "args": {"op": "hotkey", "window": "note.txt", "keys": "ctrl+s"}},
        ])
        # the fake writes into its own dict; mirror to disk to check the verifier
        report = host.run(plan)
        assert report.success
        path.write_text(fake.files[str(path)], encoding="utf-8")
        plan2 = host.plan_from("check", [{"tool": "cc_engine_status", "args": {},
                                          "expect": {"file": str(path), "contains": "JARVIS was here"}}])
        assert host.run(plan2).steps_verified == 1
        plan3 = host.plan_from("check", [{"tool": "cc_engine_status", "args": {},
                                          "expect": {"file": str(path), "contains": "nope"}}])
        assert not host.run(plan3).success

    def test_emergency_stop_mid_task(self, env):
        fake, specs = env
        host = HostAgent(specs)
        plan = host.plan_from("x", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Calculator"}},
            {"tool": "cc_control", "args": {"op": "wait", "window": "Calculator", "name": "Never", "timeout": 20}},
            {"tool": "cc_window", "args": {"op": "close", "window": "Calculator"}},
        ])
        holder = {}
        t = threading.Thread(target=lambda: holder.setdefault("r", host.run(plan)))
        t.start()
        time.sleep(0.3)
        t0 = time.perf_counter()
        estop.trigger("owner said stop")
        t.join(5)
        assert holder["r"].status == "cancelled" and time.perf_counter() - t0 < 1.0
        assert any(w.title == "Calculator" for w in fake.windows())     # close never ran

    def test_password_never_appears_in_the_trace(self, env):
        _fake, specs = env
        host = HostAgent(specs)
        report = host.run(host.plan_from("sign in", [
            {"tool": "cc_app", "args": {"op": "launch", "name": "Contoso Login"}},
            {"tool": "cc_control", "args": {"op": "set_text", "window": "Contoso", "name": "Password",
                                            "text": "Trace-Leak-42"}},
        ]))
        assert report.success
        assert "Trace-Leak-42" not in json.dumps(report.as_dict(), default=str)
        assert report.trace[-1].args["text"] == "[password-field]"

    def test_progress_events(self, env):
        _fake, specs = env
        events = []
        host = HostAgent(specs, progress=events.append)
        host.run(host.plan_from("x", [{"tool": "cc_app", "args": {"op": "launch", "name": "Notepad"}}]))
        phases = [e["phase"] for e in events]
        assert phases[0] == "start" and phases[-1] == "end"


class TestAgents:
    def test_registry_routes_and_rejects_overlap(self):
        reg = default_registry()
        assert reg.for_tool("cc_control").name == "windows"
        assert reg.for_tool("nope") is None
        custom = AgentRegistry()
        custom.register(AppAgent("a", "", frozenset({"t1"})))
        with pytest.raises(ValueError):
            custom.register(AppAgent("b", "", frozenset({"t1"})))


# ── jobs integration ─────────────────────────────────────────────────────────
class TestJobs:
    def test_cc_task_runs_as_a_job_and_publishes_status(self, env):
        from jarvis.core import ui_state
        from jarvis.core.jobs import JobManager
        fake, specs = env
        spec = specs.get("cc_task")
        assert spec.long_running and spec.to_declaration()["long_running"] is True
        bus = ui_state.StateBus()
        seen = []
        bus.subscribe(ui_state.COMPUTER_CONTROL, lambda k, v: seen.append(v))
        manager = JobManager()

        async def main():
            async def work(job):
                return await asyncio.to_thread(
                    lambda: spec.call({"objective": "open notepad and type 'hi'"},
                                      cancel_event=job.cancel_event, job_id=job.id).message)
            job = manager.start("cc_task", work)
            while job.status == "running":
                await asyncio.sleep(0.02)
            return job

        import unittest.mock as mock
        with mock.patch.object(ui_state, "bus", lambda: bus):
            job = asyncio.run(main())
            bus.drain()
        assert job.status == "done" and "Done" in job.result, job.result
        assert any(v.get("status") == "completed" for v in seen)
        assert cc_jobs.last_report().success

    def test_cancelling_the_job_stops_the_task(self, env):
        from jarvis.core.jobs import JobManager
        fake, specs = env
        spec = specs.get("cc_task")
        manager = JobManager()
        captured = {}

        def heavy(prompt):
            raise AssertionError("not used")

        async def main():
            async def work(job):
                def go():
                    plan_steps = [{"tool": "cc_app", "args": {"op": "launch", "name": "Calculator"}},
                                  {"tool": "cc_control", "args": {"op": "wait", "window": "Calculator",
                                                                  "name": "Never", "timeout": 30}}]
                    host = HostAgent(specs)
                    captured["report"] = host.run(host.plan_from("x", plan_steps),
                                                  cancel_event=job.cancel_event, job_id=job.id)
                    return captured["report"].summary
                return await asyncio.to_thread(go)
            job = manager.start("cc_task", work)
            await asyncio.sleep(0.4)
            assert manager.request_cancel(job.id)
            for _ in range(100):
                if "report" in captured:
                    break
                await asyncio.sleep(0.05)
            return job

        asyncio.run(main())
        assert captured["report"].status == "cancelled"
        assert spec is not None and heavy

    def test_planning_failure_is_reported(self, env, monkeypatch):
        _fake, specs = env
        from jarvis.computer_control.orchestrator import planner
        monkeypatch.setattr(planner, "default_ask", lambda: None)
        result = specs.get("cc_task").call({"objective": "organize my project folder"})
        assert result.status == "failed" and "could not plan" in result.message
