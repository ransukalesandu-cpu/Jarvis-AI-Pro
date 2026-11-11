"""P0-4: autonomous tasks in the shared job list, one cancel path, and "Jarvis, stop".

docs/research/JARVIS_SYSTEM_AUDIT.md B6: the web UI Jobs window, the job_status
voice tool and the job-cancel gate read only JobManager, so autonomous tasks were
invisible there; and the stop word did not stop autonomous tasks at all.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from jarvis.agent import integration
from jarvis.agent.events import AgentEvent
from jarvis.agent.integration import AgentService
from jarvis.agent.jobs_source import AgentJobSource, _name
from jarvis.agent.models import StepKind, Task, TaskState, TaskStep
from jarvis.agent.planner import Plan
from jarvis.agent.runner import TaskRunner
from jarvis.agent.settings import AgentSettings
from jarvis.agent.store import TaskStore
from jarvis.core.jobs import JobManager

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


class _Source:
    """A minimal JobSource."""

    def __init__(self, rows):
        self._rows, self.cancelled = rows, []

    def rows(self):
        return self._rows

    def owns(self, job_id):
        return any(r["id"] == job_id for r in self._rows)

    def cancel(self, job_id):
        self.cancelled.append(job_id)
        return True


def _row(i, status="running", started=100.0):
    return {"id": i, "name": f"Task: {i}", "status": status, "started": started, "finished": None}


# ── JobManager with sources ───────────────────────────────────────────────────
class TestJobManagerSources:
    def test_snapshot_merges_sorts_and_caps(self):
        manager = JobManager()
        manager.add_source(_Source([_row(f"task-{n}", started=float(n)) for n in range(25)]))
        snap = manager.snapshot()
        assert len(snap) == JobManager.MAX_ROWS
        assert snap[0]["id"] == "task-24"                     # newest first
        assert set(snap[0]) == {"id", "name", "status", "started", "finished"}

    def test_unknown_states_and_crashing_sources_are_dropped(self):
        manager = JobManager()

        class Broken(_Source):
            def rows(self):
                raise RuntimeError("source bug")
        manager.add_source(_Source([_row("task-a"), _row("task-b", status="exploded")]))
        manager.add_source(Broken([]))
        assert [r["id"] for r in manager.snapshot()] == ["task-a"]

    def test_running_ids_include_waiting_and_paused_rows(self):
        manager = JobManager()
        manager.add_source(_Source([_row("t1"), _row("t2", "waiting"), _row("t3", "paused"),
                                    _row("t4", "done")]))
        assert manager.running_ids() == ["t1", "t2", "t3"]

    def test_cancel_is_delegated_to_the_owning_source(self):
        manager = JobManager()
        source = _Source([_row("task-x")])
        manager.add_source(source)
        assert manager.request_cancel("task-x") and manager.cancel("task-x")
        assert source.cancelled == ["task-x", "task-x"]
        assert not manager.cancel("job-unknown")

    def test_cancel_all_only_touches_own_jobs(self):
        manager = JobManager()
        source = _Source([_row("task-x")])
        manager.add_source(source)
        assert manager.cancel_all() == 0 and source.cancelled == []

    def test_listeners_hear_source_changes_and_removal(self):
        manager = JobManager()
        calls = []
        manager.add_listener(lambda: calls.append(1))
        remove = manager.add_source(_Source([]))
        manager.notify()
        remove()
        assert len(calls) == 3

    def test_summaries_include_source_rows(self):
        manager = JobManager()
        manager.add_source(_Source([_row("task-1", "waiting", started=time.time() - 5)]))
        lines = manager.summaries()
        assert lines and "Task: task-1 (task-1) is waiting" in lines[0]


# ── TaskRunner.cancel_task ───────────────────────────────────────────────────
class TestCancelTask:
    def _runner(self, tmp_path):
        return TaskRunner(store=TaskStore(tmp_path), workspace=ROOT_DIR,
                          logger=lambda message: None, sleep=lambda seconds: None,
                          wait_cancel=lambda delay: False)

    def test_cancelling_a_queued_task_leaves_the_rest_queued(self, tmp_path):
        runner = self._runner(tmp_path)
        a, b, c = (runner.submit(f"task {n}") for n in "abc")
        assert runner.cancel_task(b.id)
        assert runner._queue == [a.id, c.id]
        assert runner.store.load(b.id).state is TaskState.CANCELLED
        assert not runner.cancel_task(b.id)                  # already gone
        assert not runner.cancel_task("task-nope")

    def test_cancelling_the_active_task_does_not_clear_the_queue(self, tmp_path):
        runner = self._runner(tmp_path)
        queued = runner.submit("waits")
        active = Task(objective="running now")
        active.state = TaskState.RUNNING
        runner._active = active
        assert runner.cancel_task(active.id)
        assert runner._cancel.is_set() and runner._cancel_for == active.id
        assert runner._cancel_clears_queue is False
        assert runner._queue == [queued.id]

    def test_plain_cancel_still_clears_the_queue(self, tmp_path):
        runner = self._runner(tmp_path)
        runner.submit("one")
        runner.submit("two")
        assert runner.cancel("stop")
        assert runner._queue == [] and runner._cancel_clears_queue is True


# ── AgentJobSource with a real service ───────────────────────────────────────
class _StubPlanner:
    def plan(self, objective, criteria=None):
        return Plan(steps=[TaskStep(title="note", kind=StepKind.NOTE, detail="looked")],
                    criteria=["done"], source="stub")


@pytest.fixture()
def service(tmp_path):
    svc = AgentService(settings=AgentSettings(enabled=True, max_runtime_s=30.0, retry_budget=1),
                       workspace=ROOT_DIR, store=TaskStore(tmp_path), planner=_StubPlanner(),
                       ask_model=None, logger_=lambda message: None)
    svc._owner_authorized = lambda: True
    svc._privacy_locked = lambda: False
    yield svc
    svc.shutdown()


class TestAgentJobSource:
    def test_a_started_task_appears_and_finishes_in_the_job_list(self, service):
        manager = JobManager()
        changes = []
        manager.add_listener(lambda: changes.append(1))
        source = AgentJobSource(service, manager)
        try:
            task = service.start("look at the project")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not any(
                    r["id"] == task.id and r["status"] == "done" for r in manager.snapshot()):
                time.sleep(0.02)
            row = next(r for r in manager.snapshot() if r["id"] == task.id)
            assert row["name"] == "Task: look at the project"
            assert row["status"] == "done" and row["finished"]
            assert changes, "displays must be refreshed"
        finally:
            source.close()
        assert manager.snapshot() == []                      # closed source is gone

    def test_rows_map_agent_states_and_cancel_targets_one_task(self, service):
        manager = JobManager()
        source = AgentJobSource(service, manager)
        cancelled = []
        service.cancel_task = lambda task_id, reason="": cancelled.append(task_id) or True
        try:
            for state, expected in ((TaskState.PLANNING, "running"), (TaskState.WAITING, "waiting"),
                                    (TaskState.PAUSED, "paused"), (TaskState.FAILED, "failed")):
                source._on_event(AgentEvent(kind="step", task_id="task-1", state=state))
                assert manager.snapshot()[0]["status"] == expected
            source._on_event(AgentEvent(kind="step", task_id="task-2", state=TaskState.WAITING))
            assert manager.running_ids() == ["task-2"]
            assert manager.request_cancel("task-2") and cancelled == ["task-2"]
        finally:
            source.close()

    def test_long_objectives_are_shortened(self):
        name = _name("x " * 200)
        assert len(name) <= 80 and name.startswith("Task: ") and name.endswith("…")

    def test_only_the_process_wide_service_registers(self, monkeypatch, service):
        manager = JobManager()
        monkeypatch.setattr("jarvis.core.jobs._MANAGER", manager)
        monkeypatch.setattr(integration, "_SERVICE", None)
        monkeypatch.setattr(integration, "AgentService", lambda: service)
        try:
            assert integration.existing_service() is None
            svc = integration.get_service()
            assert integration.existing_service() is svc
            assert isinstance(svc._job_source, AgentJobSource)
            assert manager._sources == [svc._job_source]
        finally:
            svc._job_source.close()
            monkeypatch.setattr(integration, "_SERVICE", None)


# ── voice tool and stop word ─────────────────────────────────────────────────
class TestVoiceAndStop:
    def test_job_status_lists_and_cancels_autonomous_tasks(self, monkeypatch):
        from jarvis.actions import jobs_tools
        manager = JobManager()
        source = _Source([_row("task-9", "paused", started=time.time())])
        manager.add_source(source)
        monkeypatch.setattr(jobs_tools, "get_job_manager", lambda: manager)
        assert "Task: task-9 (task-9) is paused" in jobs_tools.job_status({})
        assert "is paused" in jobs_tools.job_status({"job_id": "task-9"})
        assert jobs_tools.job_status({"action": "cancel", "job_id": "task-9"}) == "Cancelled task-9."
        assert source.cancelled == ["task-9"]

    def _live(self):
        from jarvis.core.runtime.live_tools import ToolDispatchMixin

        class Live(ToolDispatchMixin):
            def __init__(self):
                self.manager = JobManager()

            def _job_manager(self):
                return self.manager
        return Live()

    def test_stop_word_stops_the_autonomous_agent(self, monkeypatch):
        stopped = []

        class _Service:
            def stop(self, reason):
                stopped.append(reason)
                return True
        monkeypatch.setattr(integration, "existing_service", lambda: _Service())
        calls, jobs = self._live()._stop_everything()
        assert stopped and "Jarvis, stop" in stopped[0]
        assert jobs == 1

    def test_stop_word_never_creates_the_agent_service(self, monkeypatch):
        monkeypatch.setattr(integration, "existing_service", lambda: None)
        monkeypatch.setattr(integration, "get_service",
                            lambda: pytest.fail("stop must not create the agent service"))
        assert self._live()._stop_everything() == (0, 0)
