from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.cloud_store import CloudTaskStore
from agent.integration import AgentService
from agent.models import StepKind, StepState, Task, TaskState, TaskStep
from agent.workflow_library import WorkflowLibrary
from core.personal_cloud_memory import _redact_cloud_payload


def completed_task(objective="inspect project and run tests"):
    task = Task(objective=objective, criteria=["tests pass"])
    task.set_plan([
        TaskStep(title="Inspect files", kind=StepKind.INSPECT,
                 command="git status --short"),
        TaskStep(title="Run tests", kind=StepKind.RUN_TESTS,
                 command="python -m pytest -q", path="JarvisAI/tests",
                 content="must never enter workflow template"),
    ])
    task.transition(TaskState.PLANNING)
    task.transition(TaskState.RUNNING)
    for step in task.steps:
        step.mark(StepState.COMPLETED, output="completed")
    task.transition(TaskState.COMPLETED)
    return task


class WorkflowLibraryTests(unittest.TestCase):
    def setUp(self):
        self.library = WorkflowLibrary()

    def test_only_verified_completed_tasks_can_be_saved(self):
        with self.assertRaises(ValueError):
            self.library.save(Task(objective="unfinished"), "unfinished")
        task = completed_task()
        task.steps[0].state = StepState.FAILED
        with self.assertRaises(ValueError):
            self.library.save(task, "incomplete")

    @patch("agent.workflow_library.save_cloud_agent_workflow")
    def test_save_sends_only_safe_metadata_to_cloud(self, save_cloud):
        save_cloud.return_value = {
            "workflow_id": "task-123",
            "name": "Project checks",
            "objective": "inspect project and run tests",
            "criteria": ["tests pass"],
            "steps": [{"title": "Inspect files", "kind": "inspect"}],
            "updated_at": "2026-11-02T00:00:00Z",
        }
        task = completed_task("inspect C:\\Users\\Acer\\private and run tests")
        task.steps[0].title = "Inspect C:\\Users\\Acer\\private"
        saved = self.library.save(task, "Project checks")
        payload = save_cloud.call_args.args[0]
        self.assertEqual(payload["workflow_id"], task.id)
        self.assertEqual(set(payload["steps"][0]), {"title", "kind"})
        self.assertNotIn("command", str(payload))
        self.assertNotIn("content", str(payload))
        self.assertNotIn("C:\\Users\\Acer", str(payload))
        self.assertTrue(saved["requires_fresh_plan"])

    @patch("agent.workflow_library.list_cloud_agent_workflows")
    def test_suggestions_and_fresh_plan_are_cloud_backed(self, list_cloud):
        list_cloud.return_value = [{
            "workflow_id": "task-1", "name": "Project checks",
            "objective": "inspect project and run tests",
            "criteria": ["tests pass"],
            "steps": [{"title": "Run tests", "kind": "run_tests"}],
            "updated_at": "2026-11-02T00:00:00Z",
        }]
        self.assertEqual(len(self.library.suggest("inspect project tests")), 1)
        request = self.library.build_fresh_request("task-1")
        self.assertEqual(request["objective"], "inspect project and run tests")
        self.assertEqual(request["criteria"], ["tests pass"])
        self.assertTrue(request["requires_fresh_plan"])
        self.assertNotIn("steps", request)
        self.assertNotIn("command", request)

    @patch("agent.workflow_library.get_cloud_agent_workflow", return_value=None)
    def test_missing_workflow_is_not_found_in_cloud(self, _get):
        with self.assertRaises(KeyError):
            self.library.build_fresh_request("missing")

    @patch("agent.workflow_library.delete_cloud_agent_workflow", return_value=True)
    def test_delete_uses_cloud_endpoint(self, delete_cloud):
        self.assertTrue(self.library.delete("task-1"))
        delete_cloud.assert_called_once_with("task-1")


class CloudTaskStoreTests(unittest.TestCase):
    def test_task_payload_redacts_credentials_before_cloud_upload(self):
        clean = _redact_cloud_payload({
            "objective": "run test",
            "output": "api_key=super-secret",
        })
        self.assertNotIn("super-secret", str(clean))
        self.assertIn("[REDACTED]", str(clean))

    @patch("agent.cloud_store.save_cloud_agent_task", side_effect=RuntimeError("cloud unavailable"))
    def test_cloud_failure_does_not_fall_back_to_local_storage(self, _save_cloud):
        task = completed_task()
        with self.assertRaises(RuntimeError):
            CloudTaskStore().save(task)

    @patch("agent.cloud_store.save_cloud_agent_task")
    def test_snapshot_is_sent_to_cloud_not_a_local_path(self, save_cloud):
        task = completed_task()
        store = CloudTaskStore()
        store.save(task)
        save_cloud.assert_called_once_with(task.to_dict())
        self.assertIn("Supabase Cloud", store.root)
        self.assertFalse(hasattr(store, "tasks_dir"))
        self.assertFalse(hasattr(store, "tasks_dir"))

    @patch("agent.cloud_store.load_cloud_agent_task")
    def test_load_rehydrates_cloud_snapshot(self, load_cloud):
        task = completed_task()
        load_cloud.return_value = task.to_dict()
        restored = CloudTaskStore().load(task.id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.id, task.id)

    @patch("agent.cloud_store.list_cloud_agent_tasks")
    @patch("agent.cloud_store.load_cloud_agent_task")
    def test_resume_candidates_are_loaded_from_cloud(self, load_cloud, list_cloud):
        task = completed_task()
        task.state = TaskState.PAUSED
        list_cloud.return_value = [{
            "task_id": task.id, "state": "paused", "objective": task.objective,
        }]
        load_cloud.return_value = task.to_dict()
        rows = CloudTaskStore().unfinished()
        self.assertEqual([item.id for item in rows], [task.id])


class AgentWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.service = AgentService.__new__(AgentService)
        self.service.settings = SimpleNamespace(enabled=True)
        self.service._sync_capture_access = Mock(return_value=False)
        self.service._owner_authorized = Mock(return_value=True)
        self.service.store = Mock()
        self.service._workflow_library_instance = WorkflowLibrary()

    @patch("agent.workflow_library.save_cloud_agent_workflow")
    def test_service_saves_only_after_owner_and_privacy_gates(self, save_cloud):
        task = completed_task()
        self.service.store.load.return_value = task
        save_cloud.return_value = {
            "workflow_id": task.id, "name": "Protected workflow",
            "objective": task.objective, "criteria": task.criteria,
            "steps": [{"title": "Inspect files", "kind": "inspect"}],
        }
        saved = self.service.save_workflow(task.id, "Protected workflow")
        self.assertEqual(saved["name"], "Protected workflow")
        self.service._owner_authorized.assert_called()
        self.service._sync_capture_access.assert_called()

    def test_service_refuses_workflow_operations_when_privacy_locked(self):
        self.service._sync_capture_access.return_value = True
        with self.assertRaises(PermissionError):
            self.service.list_workflows()

    @patch("agent.workflow_library.get_cloud_agent_workflow")
    def test_reuse_starts_a_fresh_task_instead_of_replaying_steps(self, get_cloud):
        task = completed_task()
        get_cloud.return_value = {
            "workflow_id": task.id, "name": "Project checks",
            "objective": task.objective, "criteria": task.criteria,
            "steps": [{"title": "Run tests", "kind": "run_tests"}],
        }
        self.service.start = Mock(return_value=task)
        self.service.run_saved_workflow(task.id)
        self.service.start.assert_called_once_with(
            task.objective,
            criteria=task.criteria,
            source="saved_workflow",
        )


if __name__ == "__main__":
    unittest.main()
