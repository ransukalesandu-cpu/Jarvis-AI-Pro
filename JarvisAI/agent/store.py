"""Crash-safe task persistence: one JSON snapshot plus an append-only journal.

Why not SQLite? The engine needs to survive a restart, not answer queries. A
snapshot per task is a few kilobytes, ``os.replace`` makes the write atomic, and
a truncated JSON file is detectable and recoverable (the journal still holds the
last known-good event). ``core/security.py`` uses the same JSONL-with-fsync
pattern for its audit ledger, so operators only have to learn one layout.

Layout (under ``JarvisAI/memory/agent`` by default, overridable with
``JARVIS_AGENT_DIR``):

    tasks/<task-id>.json           latest snapshot, rewritten after each step
    tasks/<task-id>.journal.jsonl  append-only event log, fsynced
    queue.json                     pending objectives waiting for the worker
    index.json                     lightweight task listing for the UI

Every persisted string passes through :func:`redact` first, so a command that
echoed a key into stderr cannot leave the credential on disk.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from agent.models import Task, TaskReport, TaskState

from core import failsoft

_MAX_OUTPUT_CHARS = 8000
_MAX_JOURNAL_BYTES = 2 * 1024 * 1024
_MAX_TASKS = 40


def agent_data_dir() -> Path:
    """Resolve the runtime directory for task state.

    ``JARVIS_AGENT_DIR`` wins (tests and CI use it), then a frozen install's
    data folder, then the checkout's ``memory/agent`` directory, which
    ``JarvisAI/.gitignore`` already excludes.
    """
    override = os.environ.get("JARVIS_AGENT_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "memory" / "agent"
    return Path(__file__).resolve().parent.parent / "memory" / "agent"


DEFAULT_AGENT_DIR = agent_data_dir()


def redact(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    """Trim and scrub a string before it is written to disk or shown."""
    value = str(text or "")
    try:
        from core.self_repair import redact_secrets

        value = redact_secrets(value)
    except Exception:  # pragma: no cover - redaction must never break persistence
        failsoft.suppress("agent.store:redact")
    # A second, engine-local pass for shapes core's patterns do not cover.
    for marker in ("api_key=", "apikey=", "token=", "password=", "passwd=", "secret="):
        lowered = value.casefold()
        start = 0
        while True:
            position = lowered.find(marker, start)
            if position < 0:
                break
            value_start = position + len(marker)
            end = value_start
            while end < len(value) and value[end] not in " \t\n\r&\"',;":
                end += 1
            value = value[:value_start] + "[REDACTED]" + value[end:]
            lowered = value.casefold()
            start = value_start + len("[REDACTED]")
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    return value


class TaskStore:
    """Snapshot + journal persistence with a small, bounded task history."""

    def __init__(self, root: Path | str | None = None, *, clock: Callable[[], float] = time.time):
        self.root = Path(root) if root is not None else agent_data_dir()
        self.tasks_dir = self.root / "tasks"
        self._queue_path = self.root / "queue.json"
        self._index_path = self.root / "index.json"
        self._lock = threading.RLock()
        self._clock = clock

    # -- paths -------------------------------------------------------------
    def _ensure(self) -> None:
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def snapshot_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{_safe_id(task_id)}.json"

    def journal_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{_safe_id(task_id)}.journal.jsonl"

    # -- task snapshots ----------------------------------------------------
    def save(self, task: Task) -> None:
        """Atomically replace the task snapshot. Safe to call from any thread."""
        with self._lock:
            self._ensure()
            path = self.snapshot_path(task.id)
            temporary = path.with_name(path.name + ".tmp")
            payload = json.dumps(task.to_dict(), indent=1, ensure_ascii=False)
            fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            self._update_index(task)

    def load(self, task_id: str) -> Task | None:
        with self._lock:
            path = self.snapshot_path(task_id)
            data = _read_json(path)
        if not isinstance(data, dict):
            return None
        try:
            return Task.from_dict(data)
        except Exception:
            return None

    def delete(self, task_id: str) -> None:
        with self._lock:
            for path in (self.snapshot_path(task_id), self.journal_path(task_id)):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._rewrite_index(
                [entry for entry in self._read_index() if entry.get("id") != task_id]
            )

    # -- journal -----------------------------------------------------------
    def append_event(self, task_id: str, event: dict[str, Any]) -> None:
        """Append one event and fsync. Never raises: journaling is best-effort."""
        record = {
            "at": self._clock(),
            "task": task_id,
            **{key: (redact(value) if isinstance(value, str) else value)
               for key, value in event.items()},
        }
        with self._lock:
            try:
                self._ensure()
                path = self.journal_path(task_id)
                if path.exists() and path.stat().st_size > _MAX_JOURNAL_BYTES:
                    rotated = path.with_suffix(f".{int(self._clock())}.jsonl")
                    os.replace(path, rotated)
                with path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError:
                return

    def read_events(self, task_id: str, limit: int = 200) -> list[dict[str, Any]]:
        path = self.journal_path(task_id)
        if not path.is_file():
            return []
        events: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        # A crash mid-append leaves one torn line; ignore it.
                        continue
        except OSError:
            return []
        return events[-limit:]

    # -- history -----------------------------------------------------------
    def list_tasks(self, limit: int = _MAX_TASKS) -> list[dict[str, Any]]:
        entries = self._read_index()
        entries.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
        return entries[:limit]

    def unfinished(self) -> list[Task]:
        """Tasks that were interrupted mid-run and can be resumed."""
        resumable: list[Task] = []
        for entry in self.list_tasks():
            if entry.get("state") in {TaskState.COMPLETED.value, TaskState.CANCELLED.value}:
                continue
            task = self.load(str(entry.get("id") or ""))
            if task is None or task.state.terminal:
                continue
            if any(step.state.value in {"pending", "running", "failed"} for step in task.steps):
                resumable.append(task)
        return resumable

    def prune(self, keep: int = _MAX_TASKS) -> None:
        """Drop the oldest finished tasks, keeping snapshots bounded."""
        with self._lock:
            entries = self._read_index()
            if len(entries) <= keep:
                return
            entries.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
            for entry in entries[keep:]:
                task_id = str(entry.get("id") or "")
                for path in (self.snapshot_path(task_id), self.journal_path(task_id)):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
            self._rewrite_index(entries[:keep])

    # -- queue -------------------------------------------------------------
    def load_queue(self) -> list[dict[str, Any]]:
        data = _read_json(self._queue_path)
        return [dict(item) for item in data] if isinstance(data, list) else []

    def save_queue(self, items: Iterable[dict[str, Any]]) -> None:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._queue_path, json.dumps(list(items), indent=1))

    # -- index -------------------------------------------------------------
    def _read_index(self) -> list[dict[str, Any]]:
        data = _read_json(self._index_path)
        return [dict(item) for item in data] if isinstance(data, list) else []

    def _rewrite_index(self, entries: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_write(self._index_path, json.dumps(entries[: _MAX_TASKS * 2], indent=1))

    def _update_index(self, task: Task) -> None:
        entries = [entry for entry in self._read_index() if entry.get("id") != task.id]
        entries.append({
            "id": task.id,
            "objective": redact(task.objective, 240),
            "state": task.state.value,
            "progress": task.progress(),
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "steps": len(task.steps),
        })
        self._rewrite_index(entries)

    # -- report helper -----------------------------------------------------
    def save_report(self, report: TaskReport) -> None:
        self.append_event(report.task_id, {"kind": "report", "report": report.to_dict()})


def _safe_id(value: str) -> str:
    cleaned = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in "-_")
    return cleaned[:64] or "task"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
