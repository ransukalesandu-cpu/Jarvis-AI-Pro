"""Durable data model for the autonomous task engine.

A task is a *plan plus a cursor plus evidence*. Everything the engine needs to
resume after a crash or an app restart lives in these two dataclasses, and both
serialise to plain JSON — no database, no pickle, no Qt types. That is what makes
``test_agent_persistence.py`` able to kill a runner mid-step and prove that the
next call picks up exactly where the last one stopped.

States are deliberately strict. ``Task.transition()`` refuses illegal moves, so
a task cannot jump from ``completed`` back to ``running`` or be cancelled after
it has already finished. Every transition also stamps ``updated_at``, which is
what the UI uses to avoid repainting unchanged snapshots.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


def _now() -> float:
    return time.time()


def new_id(prefix: str = "task") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class TaskState(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING = "waiting"       # waiting on approval / external resource
    VERIFYING = "verifying"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"       # needs a credential, permission or human decision
    SKIPPED = "skipped"

    @property
    def settled(self) -> bool:
        return self in {
            StepState.COMPLETED,
            StepState.FAILED,
            StepState.BLOCKED,
            StepState.SKIPPED,
        }


class StepKind(str, Enum):
    """What an executor handler is asked to do for one step."""

    INSPECT = "inspect"              # read-only shell inspection
    RUN_COMMAND = "run_command"      # any policy-checked command
    RUN_TESTS = "run_tests"          # test command with parsed pass/fail counts
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    OBSERVE_SCREEN = "observe_screen"
    SCREEN_ACTION = "screen_action"
    VERIFY = "verify"                # check the previous result, do not act
    NOTE = "note"                    # record an observation / decision


#: Legal task transitions. Anything outside this map raises ``InvalidTransition``
#: instead of silently corrupting a journal.
TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {TaskState.PLANNING, TaskState.CANCELLED, TaskState.FAILED},
    TaskState.PLANNING: {
        TaskState.RUNNING, TaskState.PAUSED, TaskState.FAILED,
        TaskState.CANCELLED, TaskState.WAITING,
    },
    TaskState.RUNNING: {
        TaskState.VERIFYING, TaskState.WAITING, TaskState.PAUSED,
        TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED,
    },
    TaskState.VERIFYING: {
        TaskState.RUNNING, TaskState.PAUSED, TaskState.WAITING,
        TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED,
    },
    TaskState.WAITING: {
        TaskState.RUNNING, TaskState.PAUSED, TaskState.FAILED,
        TaskState.CANCELLED, TaskState.COMPLETED,
    },
    TaskState.PAUSED: {TaskState.RUNNING, TaskState.CANCELLED, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}


class InvalidTransition(RuntimeError):
    """Raised when a task is asked to move between incompatible states."""


@dataclass
class TaskStep:
    """One ordered unit of work.

    ``expect`` describes how success is judged before the step runs. It is the
    difference between "the command exited 0" and "the command exited 0 *and*
    the test summary shows no failures"; the executor only trusts the fields
    it understands and reports the rest as evidence.
    """

    title: str
    kind: StepKind = StepKind.NOTE
    detail: str = ""
    command: str = ""
    path: str = ""
    content: str = ""
    target: str = ""                       # screen element label for SCREEN_ACTION
    depends_on: list[int] = field(default_factory=list)
    expect: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 1
    timeout_s: float = 180.0
    consequential: bool = False
    index: int = 0
    id: str = field(default_factory=lambda: new_id("step"))
    state: StepState = StepState.PENDING
    attempts: int = 0
    output: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    last_error: str = ""
    blocked_reason: str = ""
    started_at: float | None = None
    finished_at: float | None = None

    # -- lifecycle ---------------------------------------------------------
    def mark_running(self) -> None:
        self.state = StepState.RUNNING
        self.attempts += 1
        self.started_at = _now()
        self.finished_at = None
        self.last_error = ""

    def mark(self, state: StepState, *, output: str = "", error: str = "",
             evidence: dict[str, Any] | None = None, blocked_reason: str = "") -> None:
        self.state = state
        if output:
            self.output = output
        if error:
            self.last_error = error
        if evidence:
            self.evidence.update(evidence)
        if blocked_reason:
            self.blocked_reason = blocked_reason
        if state.settled:
            self.finished_at = _now()

    def reset_for_retry(self) -> None:
        self.state = StepState.PENDING
        self.finished_at = None

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "index": self.index,
            "title": self.title,
            "kind": self.kind.value,
            "detail": self.detail,
            "command": self.command,
            "path": self.path,
            "content": self.content,
            "target": self.target,
            "depends_on": list(self.depends_on),
            "expect": dict(self.expect),
            "max_retries": self.max_retries,
            "timeout_s": self.timeout_s,
            "consequential": self.consequential,
            "state": self.state.value,
            "attempts": self.attempts,
            "output": self.output,
            "evidence": dict(self.evidence),
            "last_error": self.last_error,
            "blocked_reason": self.blocked_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskStep":
        data = dict(data or {})
        kind = _coerce_enum(StepKind, data.get("kind"), StepKind.NOTE)
        state = _coerce_enum(StepState, data.get("state"), StepState.PENDING)
        return cls(
            title=str(data.get("title") or "Untitled step"),
            kind=kind,
            detail=str(data.get("detail") or ""),
            command=str(data.get("command") or ""),
            path=str(data.get("path") or ""),
            content=str(data.get("content") or ""),
            target=str(data.get("target") or ""),
            depends_on=_int_list(data.get("depends_on")),
            expect=dict(data.get("expect") or {}),
            max_retries=_int(data.get("max_retries"), 1),
            timeout_s=_float(data.get("timeout_s"), 180.0),
            consequential=bool(data.get("consequential", False)),
            index=_int(data.get("index"), 0),
            id=str(data.get("id") or new_id("step")),
            state=state,
            attempts=_int(data.get("attempts"), 0),
            output=str(data.get("output") or ""),
            evidence=dict(data.get("evidence") or {}),
            last_error=str(data.get("last_error") or ""),
            blocked_reason=str(data.get("blocked_reason") or ""),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
        )


@dataclass
class TaskReport:
    """Final, human-readable outcome. Used by voice, UI and the journal."""

    task_id: str = ""
    objective: str = ""
    state: TaskState = TaskState.PENDING
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    blocked: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    tests: dict[str, Any] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    attempts: int = 0
    duration_s: float = 0.0
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "state": self.state.value,
            "completed": list(self.completed),
            "failed": list(self.failed),
            "blocked": [list(item) for item in self.blocked],
            "skipped": list(self.skipped),
            "tests": dict(self.tests),
            "blockers": list(self.blockers),
            "attempts": self.attempts,
            "duration_s": round(float(self.duration_s), 3),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskReport":
        data = dict(data or {})
        return cls(
            task_id=str(data.get("task_id") or ""),
            objective=str(data.get("objective") or ""),
            state=_coerce_enum(TaskState, data.get("state"), TaskState.PENDING),
            completed=[str(x) for x in data.get("completed") or []],
            failed=[str(x) for x in data.get("failed") or []],
            blocked=[
                (str(item[0]), str(item[1]))
                for item in data.get("blocked") or []
                if isinstance(item, (list, tuple)) and len(item) == 2
            ],
            skipped=[str(x) for x in data.get("skipped") or []],
            tests=dict(data.get("tests") or {}),
            blockers=[str(x) for x in data.get("blockers") or []],
            attempts=_int(data.get("attempts"), 0),
            duration_s=_float(data.get("duration_s"), 0.0),
            created_at=_float(data.get("created_at"), _now()),
        )

    # -- speech / UI text --------------------------------------------------
    def headline(self) -> str:
        if self.state is TaskState.COMPLETED:
            return "Task complete."
        if self.state is TaskState.CANCELLED:
            return "Task stopped."
        if self.state is TaskState.FAILED:
            return "Task failed."
        return "Task finished."

    def as_text(self, *, max_lines: int = 24) -> str:
        """Compact report for the voice layer and the UI report box."""
        lines = [self.headline(), f"Objective: {self.objective}"]
        if self.completed:
            lines.append(f"Completed {len(self.completed)} step(s):")
            lines.extend(f"  ✔ {item}" for item in self.completed[:8])
        if self.failed:
            lines.append("Failed:")
            lines.extend(f"  ✘ {item}" for item in self.failed[:6])
        if self.blocked:
            lines.append("Blocked:")
            lines.extend(f"  ⛔ {title} — {reason}" for title, reason in self.blocked[:6])
        if self.tests:
            passed = self.tests.get("passed")
            failed = self.tests.get("failed")
            lines.append(f"Tests: {passed if passed is not None else '?'} passed, "
                         f"{failed if failed is not None else '?'} failed")
        if self.blockers:
            lines.append("Blockers:")
            lines.extend(f"  • {item}" for item in self.blockers[:6])
        lines.append(f"Attempts: {self.attempts} | Duration: {self.duration_s:.0f}s")
        if len(lines) > max_lines:
            lines = lines[: max_lines - 1] + ["…"]
        return "\n".join(lines)


@dataclass
class Task:
    objective: str
    criteria: list[str] = field(default_factory=list)
    steps: list[TaskStep] = field(default_factory=list)
    id: str = field(default_factory=lambda: new_id("task"))
    state: TaskState = TaskState.PENDING
    cursor: int = 0
    source: str = "voice"
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    started_at: float | None = None
    finished_at: float | None = None
    max_runtime_s: float = 1800.0
    retry_budget: int = 12
    retries_used: int = 0
    resume_count: int = 0
    wait_reason: str = ""
    cancel_reason: str = ""
    blockers: list[str] = field(default_factory=list)
    report: TaskReport | None = None
    version: int = 1
    journal: list[dict[str, Any]] = field(default_factory=list)

    # -- planning ----------------------------------------------------------
    def set_plan(self, steps: Iterable[TaskStep], criteria: Iterable[str] | None = None) -> None:
        ordered = list(steps)
        for position, step in enumerate(ordered):
            step.index = position
        self.steps = ordered
        if criteria is not None:
            self.criteria = [str(item) for item in criteria if str(item).strip()]
        self.cursor = 0
        self.updated_at = _now()

    # -- state -------------------------------------------------------------
    def transition(self, new_state: TaskState, reason: str = "") -> None:
        new_state = TaskState(new_state)
        if new_state is self.state:
            return
        if new_state not in TRANSITIONS[self.state]:
            raise InvalidTransition(
                f"cannot move task {self.id} from {self.state.value} to {new_state.value}"
            )
        self.state = new_state
        self.updated_at = _now()
        if new_state is TaskState.RUNNING and self.started_at is None:
            self.started_at = _now()
        if new_state.terminal:
            self.finished_at = _now()
        if reason:
            self.note(f"state → {new_state.value}: {reason}")

    def note(self, message: str) -> None:
        self.journal.append({"at": _now(), "message": str(message)})
        if len(self.journal) > 400:
            del self.journal[: len(self.journal) - 400]
        self.updated_at = _now()

    # -- progress ----------------------------------------------------------
    def current_step(self) -> TaskStep | None:
        if 0 <= self.cursor < len(self.steps):
            return self.steps[self.cursor]
        return None

    def next_pending_index(self) -> int | None:
        """First unsettled step at or after the cursor whose deps are satisfied."""
        for position in range(self.cursor, len(self.steps)):
            step = self.steps[position]
            if step.state.settled:
                continue
            if all(
                dependency < len(self.steps)
                and self.steps[dependency].state is StepState.COMPLETED
                for dependency in step.depends_on
            ):
                return position
        return None

    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for step in self.steps if step.state is StepState.COMPLETED)
        return round(done / len(self.steps), 4)

    def counts(self) -> dict[str, int]:
        counts = {state.value: 0 for state in StepState}
        for step in self.steps:
            counts[step.state.value] = counts.get(step.state.value, 0) + 1
        return counts

    def deadline_exceeded(self, now: float | None = None) -> bool:
        if not self.max_runtime_s or self.started_at is None:
            return False
        return ((now if now is not None else _now()) - self.started_at) > float(self.max_runtime_s)

    def autosave_ready(self) -> bool:
        return not self.state.terminal

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "id": self.id,
            "objective": self.objective,
            "criteria": list(self.criteria),
            "state": self.state.value,
            "cursor": self.cursor,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "max_runtime_s": self.max_runtime_s,
            "retry_budget": self.retry_budget,
            "retries_used": self.retries_used,
            "resume_count": self.resume_count,
            "wait_reason": self.wait_reason,
            "cancel_reason": self.cancel_reason,
            "blockers": list(self.blockers),
            "report": self.report.to_dict() if self.report else None,
            "steps": [step.to_dict() for step in self.steps],
            "journal": list(self.journal),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        data = dict(data or {})
        report = TaskReport.from_dict(data["report"]) if data.get("report") else None
        task = cls(
            objective=str(data.get("objective") or "").strip() or "Untitled task",
            criteria=[str(x) for x in data.get("criteria") or []],
            steps=[TaskStep.from_dict(item) for item in data.get("steps") or []],
            id=str(data.get("id") or new_id("task")),
            state=_coerce_enum(TaskState, data.get("state"), TaskState.PENDING),
            cursor=_int(data.get("cursor"), 0),
            source=str(data.get("source") or "voice"),
            created_at=_float(data.get("created_at"), _now()),
            updated_at=_float(data.get("updated_at"), _now()),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            max_runtime_s=_float(data.get("max_runtime_s"), 1800.0),
            retry_budget=_int(data.get("retry_budget"), 12),
            retries_used=_int(data.get("retries_used"), 0),
            resume_count=_int(data.get("resume_count"), 0),
            wait_reason=str(data.get("wait_reason") or ""),
            cancel_reason=str(data.get("cancel_reason") or ""),
            blockers=[str(x) for x in data.get("blockers") or []],
            report=report,
            version=_int(data.get("version"), 1),
            journal=[
                dict(item) for item in data.get("journal") or [] if isinstance(item, dict)
            ],
        )
        # A resumed task that was mid-step must not stay "running" forever.
        for step in task.steps:
            if step.state is StepState.RUNNING:
                step.state = StepState.PENDING
        return task


# ── small coercion helpers ───────────────────────────────────────────────────

def _coerce_enum(enum_cls, value, default):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value))
    except (ValueError, TypeError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_list(value: Any) -> list[int]:
    out: list[int] = []
    for item in value or []:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out
