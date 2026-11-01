from __future__ import annotations
import tempfile, unittest
from pathlib import Path
from agent.models import StepKind, StepState, Task, TaskState, TaskStep
from agent.workflow_library import WorkflowLibrary

class WorkflowLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "workflows.json"
        self.library = WorkflowLibrary(self.path)

    def _completed_task(self, objective="inspect project and run tests"):
        task = Task(objective=objective, criteria=["tests pass"])
        task.set_plan([
            TaskStep(title="Inspect files", kind=StepKind.INSPECT, command="git status --short"),
            TaskStep(title="Run tests", kind=StepKind.RUN_TESTS,
                     command="python -m pytest -q", path="JarvisAI/tests", content="must not persist"),
        ])
        task.transition(TaskState.PLANNING); task.transition(TaskState.RUNNING)
        for step in task.steps: step.mark(StepState.COMPLETED, output="completed")
        task.transition(TaskState.COMPLETED)
        return task

    def test_save_only_completed_tasks(self):
        with self.assertRaises(ValueError):
            self.library.save(Task(objective="unfinished"), "unfinished")

    def test_saved_template_excludes_executable_details(self):
        task = self._completed_task()
        task.steps[0].command = "echo api_key=secret"
        saved = self.library.save(task, "Project checks")
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("command", raw); self.assertNotIn("content", raw)
        self.assertNotIn("api_key=secret", raw)
        self.assertTrue(saved["requires_fresh_plan"])
        self.assertEqual(saved["steps"][1]["kind"], "run_tests")

    def test_suggest_and_fresh_request_never_include_actions(self):
        task = self._completed_task(); self.library.save(task, "Project checks")
        self.assertEqual(len(self.library.suggest("inspect project and run tests")), 1)
        request = self.library.build_fresh_request(task.id)
        self.assertEqual(request["objective"], task.objective)
        self.assertTrue(request["requires_fresh_plan"])
        self.assertNotIn("steps", request); self.assertNotIn("command", request)

    def test_delete_and_missing_workflow(self):
        task = self._completed_task(); self.library.save(task, "Project checks")
        self.assertTrue(self.library.delete(task.id)); self.assertFalse(self.library.delete(task.id))
        with self.assertRaises(KeyError): self.library.build_fresh_request(task.id)

    def test_bounded_history_and_corrupt_file_recovery(self):
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(self.library.list(), [])
        for index in range(45):
            task = self._completed_task(f"task {index}"); task.id = f"task-{index}"
            self.library.save(task, f"workflow {index}")
        self.assertEqual(len(self.library.list()), 40)

if __name__ == "__main__": unittest.main()
