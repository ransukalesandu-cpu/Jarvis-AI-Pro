"""Live owner/Privacy Lock gates for autonomous task continuation."""

from __future__ import annotations

import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for path in (str(ROOT_DIR), str(JARVIS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from agent.integration import AgentService
from agent.models import Task, TaskStep
from agent.settings import AgentSettings


class FakeCapture:
    def __init__(self):
        self.paused = False

    def set_paused(self, value):
        self.paused = bool(value)


class FakeRunner:
    def __init__(self):
        self.resumed = False
        self.resumed_task = None

    def resume(self):
        self.resumed = True
        return True

    def resume_task(self, task_id):
        self.resumed_task = task_id
        return Task(id=task_id, objective="resumed")


class FakeStore:
    def unfinished(self):
        return [Task(id="task-1", objective="unfinished")]


def make_service(*, privacy_locked=False, owner_authorized=True, dry_run=True):
    service = AgentService.__new__(AgentService)
    service.settings = AgentSettings(enabled=True, dry_run=dry_run)
    service.capture = FakeCapture()
    service._manual_screen_paused = False
    service.runner = FakeRunner()
    service.store = FakeStore()
    service._privacy_locked = lambda: privacy_locked
    service._owner_authorized = lambda: owner_authorized
    service._log = lambda _message: None
    return service


class AutonomousAccessGuardTests(unittest.TestCase):
    def test_resume_is_blocked_when_privacy_lock_is_active(self):
        service = make_service(privacy_locked=True)
        with self.assertRaisesRegex(PermissionError, "Privacy Lock"):
            service.resume()
        self.assertFalse(service.runner.resumed)
        self.assertTrue(service.capture.paused)

    def test_resume_last_requires_owner_verification(self):
        service = make_service(owner_authorized=False)
        with self.assertRaisesRegex(PermissionError, "Owner verification"):
            service.resume_last()
        self.assertIsNone(service.runner.resumed_task)

    def test_each_step_is_blocked_after_privacy_lock_activates(self):
        service = make_service(privacy_locked=True)
        reason = service._authorize_task_step(TaskStep(title="read screen"))
        self.assertIn("Privacy Lock", reason)
        self.assertTrue(service.capture.paused)

    def test_owner_session_expiry_blocks_next_step(self):
        service = make_service(owner_authorized=False)
        reason = service._authorize_task_step(TaskStep(title="inspect"))
        self.assertIn("Owner verification expired", reason)

    def test_dry_run_does_not_override_privacy_lock(self):
        service = make_service(privacy_locked=True, dry_run=True)
        allowed, reason = service._authorize_desktop("test click")
        self.assertFalse(allowed)
        self.assertIn("Privacy Lock", reason)

    def test_security_state_import_failure_fails_closed(self):
        service = AgentService.__new__(AgentService)
        with mock.patch.dict(sys.modules, {
            "security.auth_manager": None,
            "core.security": None,
        }):
            self.assertTrue(service._privacy_locked())


if __name__ == "__main__":
    unittest.main()
