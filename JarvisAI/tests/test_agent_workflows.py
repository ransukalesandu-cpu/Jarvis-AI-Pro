from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from agent.integration import AgentService
from actions.autonomous_task import TOOL, autonomous_task

from agent.models import StepKind, StepState, Task, TaskState, TaskStep
from agent.workflow_library import WorkflowLibrary


class WorkflowLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "workflows.json"
        self.library = WorkflowLibrary(self.path)

    def _completed_task(self, objective="inspect project and run tests"):
        task = Task(objective=objective, criteria=["tests pass"])
        task.set_plan([
            TaskStep(title="Inspect files", kind=StepKind.INSPECT,
                     command="git status --short"),
            TaskStep(title="Run tests", kind=StepKind.RUN_TESTS,
                     command="python -m pytest -q", path="JarvisAI/tests",
                     content="must not persist"),
        ])
        task.transition(TaskState.PLANNING)
        task.transition(TaskState.RUNNING)
        for step in task.steps:
            step.mark(StepState.COMPLETED, output="completed")
        task.transition(TaskState.COMPLETED)
        return task

    def test_save_only_completed_tasks(self):
        with self.assertRaises(ValueError):
            self.library.save(Task(objective="unfinished"), "unfinished")

    def test_rejects_task_with_unverified_step(self):
        task = self._completed_task()
        task.steps[0].state = StepState.FAILED
        with self.assertRaises(ValueError):
            self.library.save(task, "incomplete")

    def test_saved_template_excludes_executable_details_and_paths(self):
        task = self._completed_task(
            "inspect C:\\Users\\Acer\\secret and run tests"
        )
        task.criteria = ["check /home/user/private/file.txt"]
        task.steps[0].title = "Inspect C:\\Users\\Acer\\project"
        task.steps[0].command = "echo api_key=secret"
        saved = self.library.save(task, "Project checks /home/user/private")
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("command", raw)
        self.assertNotIn("content", raw)
        self.assertNotIn("api_key=secret", raw)
        self.assertNotIn("C:\\Users\\Acer", raw)
        self.assertNotIn("/home/user/private", raw)
        self.assertTrue(saved["requires_fresh_plan"])
        self.assertEqual(saved["steps"][1]["kind"], "run_tests")

    def test_suggest_and_fresh_request_never_include_actions(self):
        task = self._completed_task()
        self.library.save(task, "Project checks")
        self.assertEqual(
            len(self.library.suggest("inspect project and run tests")), 1
        )
        request = self.library.build_fresh_request(task.id)
        self.assertEqual(request["objective"], task.objective)
        self.assertTrue(request["requires_fresh_plan"])
        self.assertNotIn("steps", request)
        self.assertNotIn("command", request)

    def test_delete_and_missing_workflow(self):
        task = self._completed_task()
        self.library.save(task, "Project checks")
        self.assertTrue(self.library.delete(task.id))
        self.assertFalse(self.library.delete(task.id))
        with self.assertRaises(KeyError):
            self.library.build_fresh_request(task.id)

    def test_bounded_history_and_corrupt_file_recovery(self):
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(self.library.list(), [])
        for index in range(45):
            task = self._completed_task(f"task {index}")
            task.id = f"task-{index}"
            self.library.save(task, f"workflow {index}")
        self.assertEqual(len(self.library.list()), 40)

    def test_rejects_partial_records_missing_required_fields(self):
        self.path.write_text(json.dumps([
            {"id": "valid-ish", "objective": "incomplete"},
            {"id": "missing-time", "name": "x", "objective": "y",
             "criteria": [], "steps": [], "saved_at": "yesterday"},
            {"id": "valid", "name": "ok", "objective": "test",
             "criteria": [], "steps": [], "saved_at": 1.0},
        ]), encoding="utf-8")
        self.assertEqual([row["id"] for row in self.library.list()], ["valid"])

    def test_multiple_instances_share_lock_and_preserve_writes(self):
        libraries = [WorkflowLibrary(self.path) for _ in range(4)]
        errors = []

        def save_many(index):
            try:
                for item in range(8):
                    task = self._completed_task(f"task-{index}-{item}")
                    task.id = f"task-{index}-{item}"
                    libraries[index].save(task, f"workflow-{index}-{item}")
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=save_many, args=(index,))
            for index in range(len(libraries))
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.library.list()), 32)




class AgentWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = AgentService.__new__(AgentService)
        self.service.settings = SimpleNamespace(enabled=True)
        self.service._sync_capture_access = Mock(return_value=False)
        self.service._owner_authorized = Mock(return_value=True)
        self.service.store = Mock()
        self.service._workflow_library_instance = WorkflowLibrary(
            Path(self.tmp.name) / "workflows.json"
        )

    def test_service_saves_only_after_owner_and_privacy_gates(self):
        task = WorkflowLibraryTests()._completed_task()
        self.service.store.load.return_value = task
        saved = self.service.save_workflow(task.id, "Protected workflow")
        self.assertEqual(saved["name"], "Protected workflow")
        self.service._owner_authorized.assert_called()
        self.service._sync_capture_access.assert_called()

    def test_service_refuses_workflow_operations_when_privacy_locked(self):
        self.service._sync_capture_access.return_value = True
        with self.assertRaises(PermissionError):
            self.service.list_workflows()

    def test_reuse_starts_a_fresh_task_instead_of_replaying_steps(self):
        task = WorkflowLibraryTests()._completed_task()
        self.service._workflow_library_instance.save(task, "Project checks")
        self.service.start = Mock(return_value=task)
        self.service.run_saved_workflow(task.id)
        self.service.start.assert_called_once_with(
            task.objective,
            criteria=task.criteria,
            source="saved_workflow",
        )




class WorkflowVoiceToolTests(unittest.TestCase):
    def test_tool_schema_exposes_workflow_actions_and_parameters(self):
        properties = TOOL["parameters"]["properties"]
        self.assertIn("save_workflow", properties["action"]["enum"])
        self.assertIn("run_workflow", properties["action"]["enum"])
        self.assertIn("list_workflows", properties["action"]["enum"])
        self.assertIn("suggest_workflows", properties["action"]["enum"])
        self.assertIn("task_id", properties)
        self.assertIn("name", properties)
        self.assertIn("workflow_id", properties)

    def test_voice_tool_forwards_workflow_arguments(self):
        service = Mock()
        service.handle_tool.return_value = "ok"
        with unittest.mock.patch("actions.autonomous_task.get_service", return_value=service):
            result = autonomous_task(
                action="save_workflow",
                task_id="task-123",
                name="Project checks",
            )
        self.assertEqual(result, "ok")
        params = service.handle_tool.call_args.args[0]
        self.assertEqual(params["action"], "save_workflow")
        self.assertEqual(params["task_id"], "task-123")
        self.assertEqual(params["name"], "Project checks")


if __name__ == "__main__":
    unittest.main()
