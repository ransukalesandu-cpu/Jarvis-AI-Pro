"""User-approved workflow templates stored only in Supabase Cloud.

A saved template contains descriptive metadata only. Reuse always requests a
fresh plan through AgentService; saved steps are never replayed as commands.
"""
from __future__ import annotations

import re
from typing import Any

from agent.models import StepState, Task, TaskState
from agent.store import redact
from core.personal_cloud_memory import (
    delete_cloud_agent_workflow,
    get_cloud_agent_workflow,
    list_cloud_agent_workflows,
    save_cloud_agent_workflow,
)

_MAX_TEMPLATES = 40


def _safe_text(value: str, limit: int) -> str:
    text = redact(" ".join(str(value or "").split()), limit * 4)
    text = re.sub(r"""(?i)\b[A-Z]:\\[^\s"'<>|]+|\\\\[^\s"'<>|]+""", "[local-path]", text)
    text = re.sub(r"(?<![\w:/])/(?!/)(?:[^\s/]+/)*[^\s/]+", "[local-path]", text)
    return text[:limit]


class WorkflowLibrary:
    """Cloud-backed saved workflow library; no local file storage or fallback."""

    def list(self) -> list[dict[str, Any]]:
        rows = list_cloud_agent_workflows()
        return [
            {
                "id": str(row.get("workflow_id") or ""),
                "name": str(row.get("name") or ""),
                "objective": str(row.get("objective") or ""),
                "saved_at": row.get("updated_at"),
                "step_count": len(row.get("steps", [])) if isinstance(row.get("steps"), list) else 0,
            }
            for row in rows[:_MAX_TEMPLATES]
        ]

    def save(self, task: Task, name: str) -> dict[str, Any]:
        if not isinstance(task, Task) or task.state is not TaskState.COMPLETED:
            raise ValueError("Only a successfully completed task can be saved.")
        if not task.steps or any(step.state is not StepState.COMPLETED for step in task.steps):
            raise ValueError("Every workflow step must be verified complete before saving.")
        label = _safe_text(name, 80)
        objective = _safe_text(task.objective, 500)
        if not label or not objective:
            raise ValueError("A workflow name and objective are required.")
        criteria = [_safe_text(item, 100) for item in task.criteria[:6]]
        steps = [
            {"title": _safe_text(step.title, 60), "kind": step.kind.value}
            for step in task.steps[:16]
        ]
        record = save_cloud_agent_workflow({
            "workflow_id": str(task.id),
            "name": label,
            "objective": objective,
            "criteria": criteria,
            "steps": steps,
        })
        return self._public(record)

    def get(self, workflow_id: str) -> dict[str, Any] | None:
        key = str(workflow_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key):
            return None
        row = get_cloud_agent_workflow(key)
        return self._public(row) if row else None

    def suggest(self, objective: str, *, limit: int = 3) -> list[dict[str, Any]]:
        query = _tokens(objective)
        if not query:
            return []
        ranked = []
        for row in list_cloud_agent_workflows():
            candidate = _tokens(str(row.get("name") or "") + " " + str(row.get("objective") or ""))
            if candidate:
                score = len(query & candidate) / max(1, len(query | candidate))
                if score > 0:
                    ranked.append((score, row))
        ranked.sort(key=lambda item: (item[0], str(item[1].get("updated_at") or "")), reverse=True)
        return [self._public(row) for _, row in ranked[:max(1, min(int(limit), 5))]]

    def build_fresh_request(self, workflow_id: str) -> dict[str, Any]:
        record = self.get(workflow_id)
        if record is None:
            raise KeyError("Saved workflow was not found in cloud storage.")
        return {
            "objective": record["objective"],
            "criteria": list(record["criteria"]),
            "source": "saved_workflow",
            "requires_fresh_plan": True,
        }

    def delete(self, workflow_id: str) -> bool:
        return delete_cloud_agent_workflow(str(workflow_id))

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("workflow_id") or row.get("id") or ""),
            "name": str(row.get("name") or ""),
            "objective": str(row.get("objective") or ""),
            "criteria": list(row.get("criteria") or []),
            "steps": list(row.get("steps") or []),
            "saved_at": row.get("updated_at") or row.get("saved_at"),
            "requires_fresh_plan": True,
        }


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9_]{2,}", str(value or "").casefold())
        if token not in {"the", "and", "for", "with", "from", "that", "this"}
    }
