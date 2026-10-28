"""End-to-end checks with a *real* process executor.

Unlike the other agent tests, this one does not script the executor: it plans a
tiny task against this repository, runs the real StepExecutor (real subprocess,
real output parsing, real verification) and inspects the report. It stays small
so the suite remains fast: `git status` plus a single test file.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.events import EventBus
from agent.models import StepKind, StepState, Task, TaskState, TaskStep
from agent.runner import RunnerConfig, TaskRunner
from agent.store import TaskStore


class RealExecutionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = TaskStore(Path(self._tmp.name))

    def _runner(self) -> TaskRunner:
        return TaskRunner(
            store=self.store,
            workspace=ROOT_DIR,
            bus=EventBus(),
            config=RunnerConfig(retry_backoff_s=0.0, progress_min_interval_s=0.0),
            logger=lambda message: None,
            sleep=lambda seconds: None,
            wait_cancel=lambda delay: False,
        )

    def test_git_and_a_single_test_file_run_for_real(self):
        python = sys.executable
        task = Task(objective="Verify the agent can execute real commands")
        task.set_plan([
            TaskStep(title="git status", kind=StepKind.INSPECT,
                     command="git status --porcelain", timeout_s=60),
            TaskStep(title="run one test file", kind=StepKind.RUN_TESTS,
                     command=f'"{python}" -m pytest JarvisAI/tests/test_agent_core.py -q',
                     timeout_s=180),
            TaskStep(title="verify", kind=StepKind.VERIFY,
                     expect={"test_failures": 0}, depends_on=[1]),
        ])
        runner = self._runner()
        runner.run_task(task)

        self.assertIs(task.state, TaskState.COMPLETED, task.report.as_text()
                      if task.report else "no report")
        self.assertEqual([step.state for step in task.steps],
                         [StepState.COMPLETED] * 3)
        self.assertEqual(task.steps[1].evidence.get("failed"), 0)
        self.assertGreater(task.steps[1].evidence.get("passed", 0), 0)
        assert task.report is not None
        self.assertIn("Tests:", task.report.as_text())
        self.assertIsNotNone(self.store.load(task.id))

    def test_failing_command_is_recorded_with_its_output(self):
        task = Task(objective="A failing command must be honest about it")
        task.set_plan([
            TaskStep(title="false", kind=StepKind.RUN_COMMAND,
                     command="git rev-parse --verify definitely-not-a-real-ref",
                     max_retries=0, timeout_s=60),
        ])
        runner = self._runner()
        runner.run_task(task)
        self.assertIs(task.state, TaskState.FAILED)
        step = task.steps[0]
        self.assertIs(step.state, StepState.FAILED)
        self.assertNotEqual(step.evidence.get("returncode"), 0)
        assert task.report is not None
        self.assertTrue(task.report.failed)

    def test_status_report_of_an_unknown_workspace_command(self):
        task = Task(objective="Unknown binaries are reported, not retried forever")
        task.set_plan([
            TaskStep(title="missing binary", kind=StepKind.RUN_COMMAND,
                     command="jarvis-definitely-not-installed --version",
                     max_retries=0, timeout_s=30),
        ])
        runner = self._runner()
        runner.run_task(task)
        self.assertIs(task.state, TaskState.FAILED)
        self.assertIn("not found", task.steps[0].output.casefold())


if __name__ == "__main__":
    unittest.main()
