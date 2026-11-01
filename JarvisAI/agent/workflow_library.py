"""Explicitly saved, non-executable workflow templates.

Templates retain only a user-approved label, objective, criteria and step
summaries. Commands, file contents, screen targets, outputs and credentials are
never copied. Reuse always asks the planner for a fresh plan and passes through
the normal owner/privacy/policy gates; a template is never an execution grant.
"""
from __future__ import annotations
import json, os, re, threading, time
from pathlib import Path
from typing import Any
from agent.models import Task, TaskState
from agent.store import redact

_MAX_TEMPLATES = 40
_MAX_NAME = 80
_MAX_OBJECTIVE = 500
_MAX_CRITERIA = 6
_MAX_STEPS = 16

def _tokens(value: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]{2,}", str(value or "").casefold())
            if t not in {"the", "and", "for", "with", "from", "that", "this"}}

def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try: temporary.unlink(missing_ok=True)
        except OSError: pass

class WorkflowLibrary:
    """Small local library for workflows the user explicitly chooses to save."""
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.RLock()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"id": r["id"], "name": r["name"], "objective": r["objective"],
                     "saved_at": r["saved_at"], "step_count": len(r.get("steps", []))}
                    for r in self._read()]

    def save(self, task: Task, name: str) -> dict[str, Any]:
        """Save a completed task as a fresh-planning template; never save actions."""
        if not isinstance(task, Task) or task.state is not TaskState.COMPLETED:
            raise ValueError("Only a successfully completed task can be saved.")
        label = " ".join(str(name or "").split())[:_MAX_NAME]
        if not label: raise ValueError("A workflow name is required.")
        steps = [{"title": redact(step.title, 100), "kind": step.kind.value}
                 for step in task.steps[:_MAX_STEPS]]
        record = {
            "id": task.id, "name": redact(label, _MAX_NAME),
            "objective": redact(task.objective, _MAX_OBJECTIVE),
            "criteria": [redact(item, 160) for item in task.criteria[:_MAX_CRITERIA]],
            "steps": steps, "saved_at": time.time(), "requires_fresh_plan": True,
        }
        with self._lock:
            rows = [row for row in self._read() if row.get("id") != record["id"]]
            rows.insert(0, record)
            _atomic_write(self.path, json.dumps(rows[:_MAX_TEMPLATES],
                                                ensure_ascii=False, indent=2))
        return self._public(record)

    def get(self, workflow_id: str) -> dict[str, Any] | None:
        with self._lock:
            for row in self._read():
                if row.get("id") == workflow_id: return self._public(row)
        return None

    def suggest(self, objective: str, *, limit: int = 3) -> list[dict[str, Any]]:
        """Return relevant templates as suggestions only; never execute them."""
        query = _tokens(objective)
        if not query: return []
        with self._lock: rows = self._read()
        ranked = []
        for row in rows:
            candidate = _tokens(row.get("name", "") + " " + row.get("objective", ""))
            if candidate:
                score = len(query & candidate) / max(1, len(query | candidate))
                if score > 0: ranked.append((score, row))
        ranked.sort(key=lambda item: (item[0], item[1].get("saved_at", 0)), reverse=True)
        return [self._public(row) for _, row in ranked[:max(1, min(int(limit), 5))]]

    def build_fresh_request(self, workflow_id: str) -> dict[str, Any]:
        """Return planner input only; caller must use normal AgentService.start."""
        record = self.get(workflow_id)
        if record is None: raise KeyError("Saved workflow was not found.")
        return {"objective": record["objective"], "criteria": list(record["criteria"]),
                "source": "saved_workflow", "requires_fresh_plan": True}

    def delete(self, workflow_id: str) -> bool:
        with self._lock:
            rows = self._read()
            kept = [row for row in rows if row.get("id") != workflow_id]
            if len(kept) == len(rows): return False
            _atomic_write(self.path, json.dumps(kept, ensure_ascii=False, indent=2))
            return True

    def _read(self) -> list[dict[str, Any]]:
        try: data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError): return []
        if not isinstance(data, list): return []
        return [r for r in data[:_MAX_TEMPLATES]
                if isinstance(r, dict) and isinstance(r.get("id"), str)
                and isinstance(r.get("objective"), str)]

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {"id": row["id"], "name": row["name"], "objective": row["objective"],
                "criteria": list(row.get("criteria", [])),
                "steps": list(row.get("steps", [])), "saved_at": row.get("saved_at"),
                "requires_fresh_plan": True}
