"""Registry-aware planning, PR C: the plan -> selection -> results trace."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
for p in (str(ROOT_DIR), str(ROOT_DIR / "jarvis")):
    if p not in sys.path:
        sys.path.insert(0, p)

from jarvis.agent.executor import StepResult  # noqa: E402
from jarvis.agent.models import StepKind, StepState, TaskState, TaskStep  # noqa: E402
from jarvis.agent.planner import Plan  # noqa: E402
from jarvis.core import plan_trace  # noqa: E402
from jarvis.tests.test_agent_runner import StubPlanner, make_runner  # noqa: E402


class TraceModuleTests(unittest.TestCase):
    def setUp(self):
        plan_trace.clear()
        self.addCleanup(plan_trace.clear)

    def test_empty(self):
        self.assertIsNone(plan_trace.last())
        self.assertEqual(plan_trace.describe_last(), "")

    def test_record_and_describe(self):
        steps = [TaskStep(title="Weather", kind=StepKind.REGISTRY_CALL, tool="weather_report"),
                 TaskStep(title="Note", kind=StepKind.NOTE, depends_on=[0])]
        plan_trace.record_plan("t1", "tell me the weather", source="model",
                               offered=["weather_report", "open_app"], steps=steps,
                               warnings=["Dropped step #3: unknown or unavailable tool 'x'."])
        plan_trace.record_result("t1", 0, state="completed", result="31C and sunny")
        plan_trace.record_result("t1", 1, state="failed", result="boom")
        plan_trace.record_result("t1", 9, state="completed")          # out of range: ignored
        plan_trace.record_result("nope", 0, state="completed")        # unknown task: ignored
        text = plan_trace.describe_last()
        self.assertIn("offered to the planner: 2; chosen: weather_report", text)
        self.assertIn("[completed] Weather (registry_call:weather_report) - 31C and sunny", text)
        self.assertIn("[failed] Note (note) - boom", text)
        self.assertIn("dropped or changed 1 item", text)

    def test_ring_keeps_newest_ten(self):
        for i in range(15):
            plan_trace.record_plan(f"t{i}", f"obj {i}")
        self.assertEqual(plan_trace.last()[0], "t14")
        with plan_trace._lock:
            self.assertEqual(len(plan_trace._traces), plan_trace.MAX_TASKS)
            self.assertNotIn("t0", plan_trace._traces)

    def test_long_text_is_clipped(self):
        plan_trace.record_plan("t", "x" * 1000)
        self.assertLessEqual(len(plan_trace.last()[1]["objective"]), 140)


class RunnerTraceTests(unittest.TestCase):
    def setUp(self):
        plan_trace.clear()
        self.addCleanup(plan_trace.clear)

    def test_runner_records_selection_and_results(self):
        steps = [
            TaskStep(title="Weather", kind=StepKind.REGISTRY_CALL, tool="weather_report",
                     args={"city": "Colombo"}, tool_risk="read"),
            TaskStep(title="Check", kind=StepKind.NOTE, depends_on=[0]),
        ]

        class OfferingPlanner(StubPlanner):
            def plan(self, objective, criteria=None):
                plan = super().plan(objective, criteria)
                plan.offered = ["weather_report", "open_app"]
                return plan

        runner, executor, _ = make_runner(
            self, steps=steps, planner=OfferingPlanner(steps),
            outcomes=[StepResult.success("31C and sunny"), StepResult.success("noted")])
        task = runner.submit("tell me the weather")
        runner.run_task(task)
        self.assertIs(task.state, TaskState.COMPLETED)

        task_id, trace = plan_trace.last()
        self.assertEqual(task_id, task.id)
        self.assertEqual(trace["offered"], ["weather_report", "open_app"])
        self.assertEqual([s["tool"] for s in trace["steps"]], ["weather_report", ""])
        self.assertEqual([s["state"] for s in trace["steps"]], ["completed", "completed"])
        self.assertIn("31C and sunny", trace["steps"][0]["result"])
        events = runner.store.read_events(task.id)
        planned = [e for e in events if e.get("kind") == "planned"]
        self.assertTrue(planned)
        self.assertEqual(planned[0].get("offered"), ["weather_report", "open_app"])
        self.assertEqual(planned[0]["steps"][0].get("tool"), "weather_report")
        results = [e for e in events if e.get("kind") == "step_result"]
        self.assertEqual(results[0].get("tool"), "weather_report")

    def test_failed_step_is_traced(self):
        steps = [TaskStep(title="Boom", kind=StepKind.REGISTRY_CALL, tool="x",
                          tool_risk="read", max_retries=0)]
        runner, _, _ = make_runner(
            self, steps=steps,
            outcomes=[StepResult.failure("Tool 'x' failed: boom")] * 3)
        task = runner.submit("do x")
        runner.run_task(task)
        _, trace = plan_trace.last()
        self.assertEqual(trace["steps"][0]["state"], StepState.FAILED.value)
        self.assertIn("boom", trace["steps"][0]["result"])


class SelfCheckTests(unittest.TestCase):
    def test_self_check_includes_last_trace(self):
        from jarvis.actions import self_check as sc
        plan_trace.clear()
        self.addCleanup(plan_trace.clear)
        plan_trace.record_plan("t1", "demo objective", source="model", offered=["a"],
                               steps=[TaskStep(title="S", kind=StepKind.REGISTRY_CALL, tool="a")])
        self.assertIn("demo objective", sc.self_check({}))


if __name__ == "__main__":
    unittest.main()
