"""Behavioural tests for the autonomous runner and step executor.

The runner is driven with an injected executor, clock and sleep, so retries,
budgets, cancellation, pause/resume and crash recovery are all verified
deterministically — no real desktop, no network, no waiting on wall-clock time.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from collections import deque
from unittest import mock
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent import policy as policy_module
from agent.events import EventBus
from agent.executor import (
    ExecutionContext,
    StepExecutor,
    StepResult,
    _clip_output,
    child_environment,
    default_test_command,
    parse_test_summary,
)
from agent.models import StepKind, StepState, Task, TaskState, TaskStep
from agent.planner import Plan
from agent.runner import RunnerConfig, TaskRunner
from agent.store import TaskStore


class ScriptedExecutor:
    """Return pre-scripted results (or callables) in order, recording calls."""

    def __init__(self, *outcomes):
        self.outcomes = deque(outcomes)
        self.calls: list[TaskStep] = []

    def execute(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        self.calls.append(step)
        if not self.outcomes:
            return StepResult.success("ok")
        outcome = self.outcomes.popleft()
        if callable(outcome):
            return outcome(step, ctx)
        return outcome


class StubPlanner:
    def __init__(self, steps, criteria=None):
        self.steps = steps
        self.criteria = criteria or []
        self.calls = 0

    def plan(self, objective, criteria=None):
        self.calls += 1
        for index, step in enumerate(self.steps):
            step.index = index
        return Plan(steps=list(self.steps), criteria=self.criteria or ["done"],
                    source="stub")


def make_runner(testcase, *, steps, outcomes=(), config=None, workspace=None,
                planner=None) -> tuple[TaskRunner, ScriptedExecutor, EventBus]:
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    store = TaskStore(Path(tmp.name))
    executor = ScriptedExecutor(*outcomes)
    bus = EventBus()
    sleeps: list[float] = []
    runner = TaskRunner(
        store=store,
        planner=planner or StubPlanner(steps),
        executor=executor,
        bus=bus,
        config=config or RunnerConfig(retry_backoff_s=1.0, max_retry_backoff_s=4.0),
        workspace=workspace or ROOT_DIR,
        sleep=sleeps.append,
        wait_cancel=lambda delay: (sleeps.append(delay), False)[1],
        logger=lambda message: None,
        monotonic=time.monotonic,
        clock=time.time,
    )
    runner.test_sleeps = sleeps  # type: ignore[attr-defined]
    return runner, executor, bus


class RunnerExecutionTests(unittest.TestCase):
    def test_successful_run_completes_and_persists(self):
        steps = [
            TaskStep(title="inspect", kind=StepKind.INSPECT, command="git status"),
            TaskStep(title="test", kind=StepKind.RUN_TESTS, command="pytest"),
            TaskStep(title="verify", kind=StepKind.VERIFY),
        ]
        runner, executor, bus = make_runner(self, steps=steps)
        task = runner.runner_submit_for_test("do it") if False else runner.submit("do it")
        runner.run_task(task)

        self.assertIs(task.state, TaskState.COMPLETED)
        self.assertEqual(len(executor.calls), 3)
        self.assertEqual(task.progress(), 1.0)
        assert task.report is not None
        self.assertEqual(len(task.report.completed), 3)
        self.assertEqual(task.report.blockers, [])
        reloaded = runner.store.load(task.id)
        assert reloaded is not None
        self.assertIs(reloaded.state, TaskState.COMPLETED)
        kinds = [event.kind for event in bus.history()]
        self.assertIn("started", kinds)
        self.assertIn("finished", kinds)
        self.assertTrue(runner.store.read_events(task.id))

    def test_retry_then_success_uses_backoff(self):
        steps = [TaskStep(title="flaky", kind=StepKind.RUN_COMMAND,
                          command="python -m pytest", max_retries=2)]
        runner, executor, _ = make_runner(
            self, steps=steps,
            outcomes=[
                StepResult.failure("temporary", retryable=True),
                StepResult.failure("temporary", retryable=True),
                StepResult.success("passed"),
            ],
        )
        task = runner.submit("retry please")
        runner.run_task(task)
        self.assertIs(task.state, TaskState.COMPLETED)
        self.assertEqual(task.steps[0].attempts, 3)
        self.assertEqual(task.retries_used, 2)
        self.assertEqual(runner.test_sleeps, [1.0, 2.0])

    def test_retry_budget_exhaustion_blocks_instead_of_looping(self):
        steps = [TaskStep(title="hang", kind=StepKind.RUN_COMMAND, command="x",
                          max_retries=5)]
        cfg = RunnerConfig(retry_budget=1, retry_backoff_s=0.0)
        runner, executor, _ = make_runner(
            self, steps=steps, config=cfg,
            outcomes=[StepResult.failure("again", retryable=True)] * 6,
        )
        task = runner.submit("budget")
        runner.run_task(task)
        self.assertIs(task.state, TaskState.WAITING)
        self.assertEqual(task.retries_used, 1)
        self.assertTrue(any("retry budget" in reason.casefold()
                            for reason in task.blockers))

    def test_non_retryable_failure_fails_the_task(self):
        steps = [TaskStep(title="broken", kind=StepKind.RUN_COMMAND, command="false")]
        runner, _, _ = make_runner(
            self, steps=steps,
            outcomes=[StepResult.failure("exited with code 1", retryable=False)],
        )
        task = runner.submit("fail")
        runner.run_task(task)
        self.assertIs(task.state, TaskState.FAILED)
        assert task.report is not None
        self.assertTrue(task.report.failed)
        self.assertEqual(task.steps[0].attempts, 1)

    def test_blocked_step_is_reported_and_independent_work_continues(self):
        steps = [
            TaskStep(title="needs key", kind=StepKind.SCREEN_ACTION, target="Save"),
            TaskStep(title="read-only", kind=StepKind.INSPECT, command="git status"),
        ]
        runner, executor, _ = make_runner(
            self, steps=steps,
            outcomes=[
                StepResult.blocked_result("No vision provider is configured."),
                StepResult.success("clean"),
            ],
        )
        task = runner.submit("blocked")
        runner.run_task(task)
        self.assertIs(task.steps[0].state, StepState.BLOCKED)
        self.assertIs(task.steps[1].state, StepState.COMPLETED)
        self.assertIs(task.state, TaskState.WAITING)
        assert task.report is not None
        self.assertIn("No vision provider", task.report.blocked[0][1])

    def test_repeated_identical_failure_is_detected_as_a_loop(self):
        steps = [TaskStep(title=f"retry {i}", kind=StepKind.RUN_COMMAND, command="x")
                 for i in range(4)]
        runner, executor, _ = make_runner(
            self, steps=steps,
            outcomes=[StepResult.failure("same error", retryable=False)] * 4,
        )
        task = runner.submit("loop")
        runner.run_task(task)
        self.assertIs(task.state, TaskState.FAILED)
        self.assertTrue(any("Loop detected" in reason for reason in task.blockers))
        self.assertLessEqual(len(executor.calls), 4)

    def test_cancellation_before_first_step(self):
        steps = [TaskStep(title="a", kind=StepKind.INSPECT, command="x")]
        runner, executor, _ = make_runner(self, steps=steps)
        task = runner.submit("cancel me")
        runner.cancel("stop")
        runner.run_task(task)
        self.assertIs(task.state, TaskState.CANCELLED)
        self.assertEqual(executor.calls, [])
        assert task.report is not None
        self.assertIs(task.report.state, TaskState.CANCELLED)

    def test_cancel_does_not_poison_the_next_task(self):
        steps = [TaskStep(title="a", kind=StepKind.INSPECT, command="x")]
        runner, executor, _ = make_runner(self, steps=steps)
        first = runner.submit("first")
        runner.cancel("stop")
        runner.run_task(first)
        self.assertIs(first.state, TaskState.CANCELLED)

        second = runner.submit("second")
        runner.run_task(second)
        self.assertIs(second.state, TaskState.COMPLETED)

    def test_cancellation_during_a_step(self):
        steps = [TaskStep(title="long", kind=StepKind.RUN_COMMAND, command="x"),
                 TaskStep(title="after", kind=StepKind.INSPECT, command="y")]

        def stop_it(step, ctx):
            runner_ref.cancel("stop now")
            return StepResult.stopped()

        runner, executor, _ = make_runner(self, steps=steps, outcomes=[stop_it])
        runner_ref = runner
        task = runner.submit("cancel during")
        runner.run_task(task)
        self.assertIs(task.state, TaskState.CANCELLED)
        self.assertEqual(len(executor.calls), 1)

    def test_stopped_task_marks_the_remaining_steps_skipped_not_failed(self):
        steps = [TaskStep(title="long", kind=StepKind.RUN_COMMAND, command="x"),
                 TaskStep(title="after", kind=StepKind.INSPECT, command="y"),
                 TaskStep(title="last", kind=StepKind.NOTE, detail="z")]

        def stop_it(step, ctx):
            runner_ref.cancel("stop now")
            return StepResult.stopped()

        runner, executor, _ = make_runner(self, steps=steps, outcomes=[stop_it])
        runner_ref = runner
        task = runner.submit("cancel during")
        runner.run_task(task)
        self.assertIs(task.state, TaskState.CANCELLED)
        self.assertEqual([step.state for step in task.steps],
                         [StepState.SKIPPED] * 3)
        self.assertIn("Stopped by the owner", task.steps[0].last_error)
        assert task.report is not None
        self.assertEqual(task.report.failed, [])
        self.assertEqual(len(task.report.skipped), 3)

    def test_pause_and_resume(self):
        steps = [TaskStep(title=f"step {i}", kind=StepKind.INSPECT, command="x")
                 for i in range(3)]
        holder = {}

        def pausing(step, ctx):
            holder["runner"].pause()
            return StepResult.success("done")

        runner, executor, _ = make_runner(self, steps=steps, outcomes=[pausing])
        holder["runner"] = runner
        task = runner.submit("pause me")
        worker = threading.Thread(target=runner.run_task, args=(task,), daemon=True)
        worker.start()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if task.state is TaskState.PAUSED:
                break
            time.sleep(0.01)
        self.assertIs(task.state, TaskState.PAUSED)
        time.sleep(0.05)
        self.assertEqual(len(executor.calls), 1)  # nothing runs while paused
        runner.resume()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertIs(task.state, TaskState.COMPLETED)
        self.assertEqual(len(executor.calls), 3)

    def test_deadline_stops_the_task(self):
        steps = [TaskStep(title="slow", kind=StepKind.INSPECT, command="x")]

        def slow(step, ctx):
            time.sleep(0.05)
            return StepResult.success("ok")

        runner, executor, _ = make_runner(self, steps=steps, outcomes=[slow] * 3)
        task = runner.submit("deadline")
        task.max_runtime_s = 0.001
        runner.run_task(task)
        self.assertIs(task.state, TaskState.FAILED)
        self.assertTrue(any("deadline" in reason.casefold() for reason in task.blockers))

    def test_crash_mid_task_is_resumable_without_repeating_completed_steps(self):
        steps = [
            TaskStep(title="one", kind=StepKind.INSPECT, command="a"),
            TaskStep(title="two", kind=StepKind.INSPECT, command="b"),
            TaskStep(title="three", kind=StepKind.INSPECT, command="c"),
        ]

        def crash(step, ctx):
            raise RuntimeError("simulated crash")

        runner, executor, _ = make_runner(
            self, steps=steps,
            outcomes=[StepResult.success("one done"), crash],
        )
        task = runner.submit("crash")
        with self.assertRaises(RuntimeError):
            runner.run_task(task)  # run_task propagates; the worker would catch it
        self.assertIs(task.steps[0].state, StepState.COMPLETED)

        # A fresh process would build a new runner over the same store.
        second_executor = ScriptedExecutor(StepResult.success("two"),
                                           StepResult.success("three"))
        resumed_runner = TaskRunner(
            store=runner.store,
            planner=StubPlanner(steps),
            executor=second_executor,
            workspace=ROOT_DIR,
            bus=EventBus(),
            sleep=lambda _seconds: None,
            logger=lambda message: None,
        )
        resumed = resumed_runner.resume_task(task.id, background=False)
        resumed_runner.run_task(resumed)
        self.assertIs(resumed.state, TaskState.COMPLETED)
        self.assertEqual([step.title for step in second_executor.calls], ["two", "three"])
        self.assertEqual(resumed.resume_count, 1)

    def test_background_start_completes_and_reports_status(self):
        steps = [TaskStep(title="quick", kind=StepKind.INSPECT, command="x")]
        runner, executor, _ = make_runner(self, steps=steps)
        task = runner.start("background job")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not task.state.terminal:
            time.sleep(0.01)
        self.assertIs(task.state, TaskState.COMPLETED)
        status = runner.status()
        self.assertIsNone(status["active"])
        self.assertEqual(status["queued"], [])
        self.assertFalse(status["paused"])

    def test_planner_failure_fails_cleanly(self):
        class BrokenPlanner:
            def plan(self, objective, criteria=None):
                raise RuntimeError("model offline")

        runner, executor, _ = make_runner(self, steps=[], planner=BrokenPlanner())
        task = runner.submit("x")
        runner.run_task(task)
        self.assertIs(task.state, TaskState.FAILED)
        self.assertTrue(any("Planning failed" in reason for reason in task.blockers))


class ExecutorTests(unittest.TestCase):
    def _context(self, task=None, **kwargs) -> ExecutionContext:
        task = task or Task(objective="t")
        return ExecutionContext(
            task=task,
            workspace=ROOT_DIR,
            cancel=kwargs.pop("cancel", threading.Event()),
            pause=kwargs.pop("pause", threading.Event()),
            **kwargs,
        )

    def test_inspect_runs_the_injected_command(self):
        calls = []

        def fake_runner(command, ctx, timeout):
            calls.append((command, timeout))
            return {"returncode": 0, "output": "clean", "duration_s": 0.1,
                    "timed_out": False}

        executor = StepExecutor(
            engine=policy_module.PolicyEngine(owner_check=lambda: True),
            command_runner=fake_runner,
        )
        step = TaskStep(title="status", kind=StepKind.INSPECT, command="git status")
        result = executor.execute(step, self._context())
        self.assertTrue(result.ok)
        self.assertEqual(calls[0][0], "git status")

    def test_test_failures_are_extracted_and_fail_the_step(self):
        def fake_runner(command, ctx, timeout):
            return {"returncode": 1, "output": "2 failed, 10 passed in 0.4s",
                    "duration_s": 0.2, "timed_out": False}

        executor = StepExecutor(command_runner=fake_runner)
        result = executor.execute(
            TaskStep(title="tests", kind=StepKind.RUN_TESTS, command="pytest"),
            self._context(),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.evidence.get("failed"), 2)
        self.assertEqual(result.evidence.get("passed"), 10)

    def test_timeout_is_retryable(self):
        def fake_runner(command, ctx, timeout):
            return {"returncode": None, "output": "", "duration_s": 5.0,
                    "timed_out": True}

        executor = StepExecutor(command_runner=fake_runner)
        result = executor.execute(
            TaskStep(title="slow", kind=StepKind.RUN_COMMAND, command="sleep 999"),
            self._context(),
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.retryable)

    def test_write_inside_workspace_and_outside_is_refused(self):
        executor = StepExecutor(
            engine=policy_module.PolicyEngine(
                policy_module.ExecutionPolicy(workspace_root=str(ROOT_DIR)),
                owner_check=lambda: True,
            )
        )
        with tempfile.TemporaryDirectory(dir=ROOT_DIR) as tmp:
            target = Path(tmp) / "note.txt"
            inside = TaskStep(title="write", kind=StepKind.WRITE_FILE,
                              path=str(target.relative_to(ROOT_DIR)), content="hello")
            result = executor.execute(inside, self._context())
            self.assertTrue(result.ok)
            self.assertEqual(target.read_text(encoding="utf-8"), "hello")

        outside = TaskStep(title="escape", kind=StepKind.WRITE_FILE,
                           path="/tmp/jarvis-should-not-write.txt", content="x")
        blocked = executor.execute(outside, self._context())
        self.assertTrue(blocked.blocked)
        self.assertFalse(Path("/tmp/jarvis-should-not-write.txt").exists())

    def test_verify_checks_previous_step_evidence(self):
        task = Task(objective="t")
        task.set_plan([
            TaskStep(title="tests", kind=StepKind.RUN_TESTS, command="pytest"),
            TaskStep(title="verify", kind=StepKind.VERIFY, expect={"test_failures": 0}),
        ])
        task.steps[0].state = StepState.COMPLETED
        task.steps[0].evidence = {"failed": 0, "passed": 3}
        executor = StepExecutor()
        result = executor.execute(task.steps[1], self._context(task))
        self.assertTrue(result.ok)

        task.steps[0].evidence = {"failed": 2}
        failed = executor.execute(task.steps[1], self._context(task))
        self.assertFalse(failed.ok)

    def test_verify_without_known_criteria_is_blocked(self):
        executor = StepExecutor()
        task = Task(objective="t")
        task.set_plan([TaskStep(title="verify", kind=StepKind.VERIFY)])
        result = executor.execute(task.steps[0], self._context(task))
        self.assertTrue(result.blocked)

    def test_consequential_step_requires_approval_callback(self):
        policy = policy_module.ExecutionPolicy(
            allowed_risk=policy_module.Risk.CONSEQUENTIAL,
            workspace_root=str(ROOT_DIR),
        )
        engine = policy_module.PolicyEngine(policy, owner_check=lambda: True)
        executor = StepExecutor(engine=engine,
                                command_runner=lambda c, ctx, t: {
                                    "returncode": 0, "output": "ok",
                                    "duration_s": 0.0, "timed_out": False})
        step = TaskStep(title="delete", kind=StepKind.RUN_COMMAND, command="rm -rf build")

        denied = executor.execute(step, self._context(request_approval=None))
        self.assertTrue(denied.blocked)

        refused = executor.execute(step, self._context(
            request_approval=lambda task_step, decision: False))
        self.assertTrue(refused.blocked)

        allowed = executor.execute(step, self._context(
            request_approval=lambda task_step, decision: True))
        self.assertTrue(allowed.ok)

    def test_cancelled_step_returns_stopped(self):
        cancel = threading.Event()
        cancel.set()
        executor = StepExecutor()
        result = executor.execute(
            TaskStep(title="x", kind=StepKind.INSPECT, command="git status"),
            self._context(cancel=cancel),
        )
        self.assertTrue(result.cancelled)

    def test_test_summary_parser_and_default_command(self):
        counts = parse_test_summary("3 passed, 1 failed, 2 skipped in 1.2s")
        self.assertEqual(counts["passed"], 3)
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["skipped"], 2)
        self.assertFalse(counts["ok"])
        command = default_test_command(ROOT_DIR)
        self.assertIn("pytest", command)
        self.assertIn("JarvisAI", command)

    def test_long_output_keeps_the_tail_so_the_summary_survives(self):
        noise = "\n".join(f"test_{index} ok" for index in range(4000))
        clipped = _clip_output(noise + "\n499 passed, 3 skipped in 12.4s\n")
        self.assertLessEqual(len(clipped), 6000)
        self.assertIn("test_0 ok", clipped)             # the head survives
        self.assertIn("499 passed, 3 skipped", clipped)  # so does the summary
        self.assertEqual(parse_test_summary(clipped)["passed"], 499)

    def test_child_environment_does_not_inherit_agent_configuration(self):
        with mock.patch.dict("os.environ", {
            "JARVIS_AUTONOMOUS": "1",
            "JARVIS_AGENT_MAX_RUNTIME": "600",
            "JARVIS_AGENT_DRY_RUN": "1",
            "JARVIS_AGENT_DIR": "/tmp/agent-dir",
            "JARVIS_VISION_MODEL": "gemini/x",
            "JARVIS_KEEP_ME": "yes",
        }):
            env = child_environment()
        self.assertNotIn("JARVIS_AUTONOMOUS", env)
        for key in ("JARVIS_AGENT_MAX_RUNTIME", "JARVIS_AGENT_DRY_RUN",
                    "JARVIS_AGENT_DIR", "JARVIS_VISION_MODEL"):
            self.assertNotIn(key, env)
        self.assertEqual(env["JARVIS_AGENT_CHILD"], "1")
        self.assertEqual(env["JARVIS_KEEP_ME"], "yes")


if __name__ == "__main__":
    unittest.main()
