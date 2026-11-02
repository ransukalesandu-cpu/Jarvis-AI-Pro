"""Explicitly saved, non-executable workflow templates.

Templates retain only a user-approved label, objective, criteria and step
summaries. Commands, file contents, screen targets, outputs and credentials are
never copied. Reuse always asks the planner for a fresh plan and passes through
the normal owner/privacy/policy gates; a template is never an execution grant.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from agent.models import StepState, Task, TaskState
from agent.store import redact

_MAX_TEMPLATES = 40
_MAX_NAME = 80
_MAX_OBJECTIVE = 500
_MAX_CRITERIA = 6
_MAX_STEPS = 16

# Instances that point at the same file must serialize their entire
# read-modify-write transaction, not merely their own instance operations.
_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.expanduser().resolve())
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _safe_text(value: str, limit: int) -> str:
    """Redact secrets and absolute local paths before persisting user text."""
    cleaned = redact(str(value or ""), limit * 4)
    # Windows drive paths and UNC paths.
    cleaned = re.sub(r"(?i)(?:[a-z]:\\\\|\\\\\\\\)[^\\s\"'<>|]+", "[local-path]", cleaned)
    # POSIX absolute paths, excluding URL schemes.
    cleaned = re.sub(r"(?<![\\w:])/(?:[^\\s/]+/)*[^\\s/]+", "[local-path]", cleaned)
    return cleaned[:limit]


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8", newline="\\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


class WorkflowLibrary:
    """Small local library for workflows the user explicitly chooses to save."""

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()
        self._lock = _lock_for(self.path)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"id": row["id"], "name": row["name"],
                 "objective": row["objective"], "saved_at": row["saved_at"],
                 "step_count": len(row.get("steps", []))}
                for row in self._read()
            ]

    def save(self, task: Task, name: str) -> dict[str, Any]:
        """Save a completed task as a fresh-planning template; never save actions."""
        if not isinstance(task, Task) or task.state is not TaskState.COMPLETED:
            raise ValueError("Only a successfully completed task can be saved.")
        if not task.steps or any(step.state is not StepState.COMPLETED for step in task.steps):
            raise ValueError("Every workflow step must be verified complete before saving.")

        label = _safe_text(" ".join(str(name or "").split()), _MAX_NAME)
        if not label:
            raise ValueError("A workflow name is required.")
        steps = [
            {"title": _safe_text(step.title, 100), "kind": step.kind.value}
            for step in task.steps[:_MAX_STEPS]
        ]
        record = {
            "id": str(task.id),
            "name": label,
            "objective": _safe_text(task.objective, _MAX_OBJECTIVE),
            "criteria": [_safe_text(item, 160) for item in task.criteria[:_MAX_CRITERIA]],
            "steps": steps,
            "saved_at": time.time(),
            "requires_fresh_plan": True,
        }
        with self._lock:
            rows = [row for row in self._read() if row["id"] != record["id"]]
            rows.insert(0, record)
            _atomic_write(
                self.path,
                json.dumps(rows[:_MAX_TEMPLATES], ensure_ascii=False, indent=2),
            )
        return self._public(record)

    def get(self, workflow_id: str) -> dict[str, Any] | None:
        with self._lock:
            for row in self._read():
                if row["id"] == workflow_id:
                    return self._public(row)
        return None

    def suggest(self, objective: str, *, limit: int = 3) -> list[dict[str, Any]]:
        """Return relevant templates as suggestions only; never execute them."""
        query = _tokens(objective)
        if not query:
            return []
        with self._lock:
            rows = self._read()
        ranked = []
        for row in rows:
            candidate = _tokens(row["name"] + " " + row["objective"])
            if candidate:
                score = len(query & candidate) / max(1, len(query | candidate))
                if score > 0:
                    ranked.append((score, row))
        ranked.sort(
            key=lambda item: (item[0], item[1]["saved_at"]), reverse=True
        )
        return [
            self._public(row)
            for _, row in ranked[:max(1, min(int(limit), 5))]
        ]

    def build_fresh_request(self, workflow_id: str) -> dict[str, Any]:
        """Return planner input only; caller must use normal AgentService.start."""
        record = self.get(workflow_id)
        if record is None:
            raise KeyError("Saved workflow was not found.")
        return {
            "objective": record["objective"],
            "criteria": list(record["criteria"]),
            "source": "saved_workflow",
            "requires_fresh_plan": True,
        }

    def delete(self, workflow_id: str) -> bool:
        with self._lock:
            rows = self._read()
            kept = [row for row in rows if row["id"] != workflow_id]
            if len(kept) == len(rows):
                return False
            _atomic_write(
                self.path, json.dumps(kept, ensure_ascii=False, indent=2)
            )
            return True

    def _read(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return []
        if not isinstance(data, list):
            return []
        valid = []
        for row in data[:_MAX_TEMPLATES]:
            if not isinstance(row, dict):
                continue
            if not isinstance(row.get("id"), str):
                continue
            if not isinstance(row.get("name"), str):
                continue
            if not isinstance(row.get("objective"), str):
                continue
            if not isinstance(row.get("criteria"), list):
                continue
            if not all(isinstance(item, str) for item in row["criteria"]):
                continue
            if not isinstance(row.get("steps"), list):
                continue
            if not all(
                isinstance(step, dict)
                and isinstance(step.get("title"), str)
                and isinstance(step.get("kind"), str)
                for step in row["steps"]
            ):
                continue
            if isinstance(row.get("saved_at"), bool) or not isinstance(
                row.get("saved_at"), (int, float)
            ):
                continue
            # Sanitize old/hand-edited entries at read time as well.
            safe = dict(row)
            safe["name"] = _safe_text(row["name"], _MAX_NAME)
            safe["objective"] = _safe_text(row["objective"], _MAX_OBJECTIVE)
            safe["criteria"] = [_safe_text(item, 160) for item in row["criteria"][:_MAX_CRITERIA]]
            safe["steps"] = [
                {"title": _safe_text(step["title"], 100), "kind": step["kind"]}
                for step in row["steps"][:_MAX_STEPS]
            ]
            valid.append(safe)
        return valid

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "objective": row["objective"],
            "criteria": list(row.get("criteria", [])),
            "steps": list(row.get("steps", [])),
            "saved_at": row["saved_at"],
            "requires_fresh_plan": True,
        }


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9_]{2,}", str(value or "").casefold())
        if token not in {"the", "and", "for", "with", "from", "that", "this"}
    }
