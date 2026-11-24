"""Correlation identifiers survive persistence and follow task events."""

import unittest

from jarvis.agent.events import EventBus, event_from_task
from jarvis.agent.models import Task, TaskState
from jarvis.agent.runner import RunnerConfig, TaskRunner


class CorrelationIdTests(unittest.TestCase):
    def test_task_generates_and_round_trips_correlation_id(self):
        task = Task(objective="trace me")
        self.assertTrue(task.correlation_id.startswith("corr-"))

        restored = Task.from_dict(task.to_dict())

        self.assertEqual(restored.correlation_id, task.correlation_id)

    def test_legacy_task_payload_gets_a_correlation_id(self):
        restored = Task.from_dict({"objective": "legacy"})

        self.assertTrue(restored.correlation_id.startswith("corr-"))

    def test_event_carries_task_correlation_id(self):
        task = Task(objective="trace events")
        task.transition(TaskState.PLANNING)
        event = event_from_task("planning", task, message="planning")
        bus = EventBus()
        bus.publish(event)

        published = bus.latest()
        self.assertIsNotNone(published)
        self.assertEqual(published.correlation_id, task.correlation_id)
        self.assertEqual(
            published.to_dict()["correlation_id"], task.correlation_id
        )

    def test_submit_accepts_a_caller_correlation_id(self):
        class Store:
            def save(self, task):
                self.task = task

            def append_event(self, task_id, event):
                pass

        store = Store()
        runner = TaskRunner(
            store=store,
            config=RunnerConfig(),
            logger=lambda message: None,
        )

        task = runner.submit("trace this", correlation_id="request-123")

        self.assertEqual(task.correlation_id, "request-123")
        self.assertEqual(store.task.correlation_id, "request-123")


if __name__ == "__main__":
    unittest.main()
