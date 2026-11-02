"""Cloud-only persistence adapter for the autonomous agent.

No task snapshot, event, checkpoint, report or history entry is written to the
local filesystem. If Supabase is unavailable, durable saves fail closed rather
than silently falling back to disk.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.models import Task, TaskReport
from core.personal_cloud_memory import (
    append_cloud_agent_event,
    delete_cloud_agent_task,
    list_cloud_agent_events,
    list_cloud_agent_tasks,
    load_cloud_agent_task,
    save_cloud_agent_task,
)

logger = logging.getLogger("Jarvis.CloudTaskStore")


class CloudTaskStore:
    """TaskStore-compatible adapter backed exclusively by the user's Supabase rows."""

    def save(self, task: Task) -> None:
        save_cloud_agent_task(task.to_dict())

    def load(self, task_id: str) -> Task | None:
        data = load_cloud_agent_task(str(task_id))
        if not isinstance(data, dict):
            return None
        try:
            return Task.from_dict(data)
        except Exception:
            return None

    def delete(self, task_id: str) -> None:
        delete_cloud_agent_task(str(task_id))

    def append_event(self, task_id: str, event: dict[str, Any]) -> None:
        try:
            append_cloud_agent_event(str(task_id), event)
        except Exception as exc:
            # Event journaling is best-effort, matching the legacy store. The
            # authoritative task snapshot still must succeed before progress.
            logger.warning("Cloud task event was not persisted (%s)", type(exc).__name__)

    def read_events(self, task_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = list_cloud_agent_events(str(task_id), limit)
        events = []
        for row in rows:
            data = row.get("event_data")
            if isinstance(data, dict):
                events.append({
                    "at": row.get("created_at"),
                    "task": str(task_id),
                    **data,
                })
        return events[-max(1, min(200, int(limit))):]

    def list_tasks(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = list_cloud_agent_tasks()
        return [
            {
                "id": str(row.get("task_id") or ""),
                "state": str(row.get("state") or ""),
                "objective": str(row.get("objective") or ""),
                "updated_at": row.get("updated_at"),
            }
            for row in rows[:max(1, min(40, int(limit)))]
            if isinstance(row, dict)
        ]

    def unfinished(self) -> list[Task]:
        tasks = []
        for row in self.list_tasks():
            if row["state"] in {"completed", "cancelled", "failed"}:
                continue
            task = self.load(row["id"])
            if task is not None and not task.state.terminal:
                tasks.append(task)
        return tasks

    def prune(self, keep: int = 40) -> None:
        # Server enforces the per-user history cap during each snapshot upsert.
        return None

    def save_report(self, report: TaskReport) -> None:
        self.append_event(report.task_id, {"kind": "report", "report": report.to_dict()})
