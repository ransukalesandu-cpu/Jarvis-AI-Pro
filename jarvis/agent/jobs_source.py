"""Autonomous tasks in the shared job list (audit P0-4, B6).

The web UI Jobs window, the ``job_status`` voice tool and the job-cancel gate all
read :class:`jarvis.core.jobs.JobManager`. Autonomous tasks run in the agent's own
TaskRunner, so before this they were invisible there. :class:`AgentJobSource`
registers with the JobManager as a source (no fake asyncio job, no second
announcement — the agent keeps speaking its own milestones):

* rows come from an in-memory table updated by agent events — never from the
  store, which may be the cloud — so a display refresh does no I/O;
* only tasks started, resumed or queued during this run are shown;
* the row name is the task objective (the owner's own request), shortened;
* cancelling a row cancels exactly that task (``TaskRunner.cancel_task``); the
  rest of the queue is left alone.

Status mapping: pending/planning/running/verifying → ``running``; waiting →
``waiting``; paused → ``paused``; completed → ``done``; failed → ``failed``;
cancelled → ``cancelled``.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from jarvis.agent.models import TaskState

_STATUS = {
    TaskState.PENDING: "running", TaskState.PLANNING: "running", TaskState.RUNNING: "running",
    TaskState.VERIFYING: "running", TaskState.WAITING: "waiting", TaskState.PAUSED: "paused",
    TaskState.COMPLETED: "done", TaskState.FAILED: "failed", TaskState.CANCELLED: "cancelled",
}
MAX_ROWS = 20
NAME_LIMIT = 80


def _name(objective: str) -> str:
    text = "Task: " + " ".join(str(objective or "autonomous task").split())
    return text if len(text) <= NAME_LIMIT else text[:NAME_LIMIT - 1].rstrip() + "…"


class AgentJobSource:
    def __init__(self, service: Any, manager: Any | None = None):
        if manager is None:
            from jarvis.core.jobs import get_job_manager
            manager = get_job_manager()
        self._service = service
        self._manager = manager
        self._rows: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = threading.Lock()
        self._unsubscribe_events = service.subscribe(self._on_event)
        self._unsubscribe_source = manager.add_source(self)

    # -- JobSource -------------------------------------------------------------
    def rows(self) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self._rows.values()]

    def owns(self, job_id: str) -> bool:
        with self._lock:
            return str(job_id) in self._rows

    def cancel(self, job_id: str) -> bool:
        return bool(self._service.cancel_task(str(job_id), "Cancelled from the job list."))

    # -- events ------------------------------------------------------------------
    def _on_event(self, event: Any) -> None:
        task_id = str(getattr(event, "task_id", "") or "")
        if not task_id:
            return
        state = getattr(event, "state", None)
        status = _STATUS.get(state, "running")
        with self._lock:
            row = self._rows.get(task_id)
            new = row is None
            if new:
                task = self._service.runner.live_task(task_id)
                objective = getattr(task, "objective", "") if task is not None else ""
                started = float(getattr(task, "created_at", 0.0) or time.time()) if task else time.time()
                row = {"id": task_id, "name": _name(objective), "status": status,
                       "started": started, "finished": None}
                self._rows[task_id] = row
            changed = row["status"] != status
            row["status"] = status
            if status in ("done", "failed", "cancelled"):
                row["finished"] = row["finished"] or time.time()
            else:
                row["finished"] = None
            self._rows.move_to_end(task_id)
            while len(self._rows) > MAX_ROWS:
                self._rows.popitem(last=False)
        if new or changed:
            self._manager.notify()

    def close(self) -> None:
        self._unsubscribe_events()
        self._unsubscribe_source()
