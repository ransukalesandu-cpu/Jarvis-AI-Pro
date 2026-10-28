"""Qt-free text and geometry helpers for the agent panel and Dynamic Island.

Keeping this module free of PyQt6 is deliberate: the strings, colours, progress
text and island geometry are the parts worth unit-testing, and they must be
testable on a machine where Qt's system libraries are unavailable (headless CI,
containers, this project's own Linux test runner). The widget modules are thin
wrappers around these functions.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.models import StepState, Task, TaskReport, TaskState


#: Colour accents reused from the HUD palette so the island looks native.
TONE = {
    "idle": "#00e5ff",
    "listening": "#70ffc4",
    "thinking": "#a78bfa",
    "speaking": "#8fffd6",
    "working": "#00e5ff",
    "waiting": "#ffb86b",
    "paused": "#ffd166",
    "error": "#ff6280",
    "done": "#70ffc4",
}

_STATE_TONE = {
    TaskState.PENDING: "idle",
    TaskState.PLANNING: "thinking",
    TaskState.RUNNING: "working",
    TaskState.VERIFYING: "thinking",
    TaskState.WAITING: "waiting",
    TaskState.PAUSED: "paused",
    TaskState.COMPLETED: "done",
    TaskState.FAILED: "error",
    TaskState.CANCELLED: "error",
}

_STATE_LABEL = {
    TaskState.PENDING: "QUEUED",
    TaskState.PLANNING: "PLANNING",
    TaskState.RUNNING: "WORKING",
    TaskState.VERIFYING: "VERIFYING",
    TaskState.WAITING: "WAITING",
    TaskState.PAUSED: "PAUSED",
    TaskState.COMPLETED: "COMPLETE",
    TaskState.FAILED: "FAILED",
    TaskState.CANCELLED: "STOPPED",
}


def _as_state(state: TaskState | str) -> TaskState | None:
    """Coerce a state or its string value. ``str(TaskState.X)`` is not its value."""
    if isinstance(state, TaskState):
        return state
    try:
        return TaskState(str(state).strip().lower())
    except (ValueError, TypeError):
        return None


def state_label(state: TaskState | str) -> str:
    resolved = _as_state(state)
    if resolved is not None:
        return _STATE_LABEL[resolved]
    return str(state or "IDLE").upper()


def state_color(state: TaskState | str) -> str:
    resolved = _as_state(state)
    if resolved is not None:
        return TONE[_STATE_TONE[resolved]]
    return TONE["idle"]


@dataclass(frozen=True)
class IslandSummary:
    """What the compact floating widget shows."""

    title: str
    detail: str
    progress: float
    state: TaskState
    tone: str
    expandable: bool

    @property
    def is_active(self) -> bool:
        return not self.state.terminal


def summarize_task(task: Task | None, *, idle_label: str = "JARVIS READY") -> IslandSummary:
    """One-line status for the island, safe with ``None`` (no task yet)."""
    if task is None:
        return IslandSummary(idle_label, "Tap to open JARVIS", 0.0,
                             TaskState.PENDING, TONE["idle"], False)
    step = task.current_step()
    if task.state is TaskState.WAITING and task.wait_reason:
        detail = task.wait_reason
    elif step is not None and task.state in (TaskState.RUNNING, TaskState.VERIFYING):
        detail = step.title
    elif task.state is TaskState.COMPLETED:
        detail = "Task complete"
    elif task.state is TaskState.FAILED:
        detail = (task.report.headline() if task.report else "Task failed")
    elif task.state is TaskState.CANCELLED:
        detail = task.cancel_reason or "Stopped"
    elif task.state is TaskState.PAUSED:
        detail = f"Paused at {step.title}" if step else "Paused"
    else:
        detail = f"{len(task.steps)} step plan" if task.steps else "Planning"
    return IslandSummary(
        title=state_label(task.state),
        detail=detail[:120],
        progress=task.progress(),
        state=task.state,
        tone=state_color(task.state),
        expandable=bool(task.steps),
    )


def progress_text(task: Task | None) -> str:
    if task is None:
        return "No task running."
    done = sum(1 for step in task.steps if step.state is StepState.COMPLETED)
    return f"{done}/{len(task.steps)} steps · {int(task.progress() * 100)}%"


def step_line(index: int, title: str, state: StepState | str) -> str:
    glyph = {
        StepState.COMPLETED.value: "✔",
        StepState.FAILED.value: "✘",
        StepState.BLOCKED.value: "⛔",
        StepState.SKIPPED.value: "–",
        StepState.RUNNING.value: "▶",
        StepState.VERIFYING.value: "◈",
    }.get(str(getattr(state, "value", state)), "·")
    return f"{glyph} {index + 1:02d}  {title}"


def report_text(report: TaskReport | None) -> str:
    if report is None:
        return "No report yet."
    return report.as_text()


def active_task_label(task: Task | None) -> str:
    """Short status chip text used on the HUD home screen."""
    if task is None:
        return "AUTONOMY IDLE"
    return f"AUTONOMY {state_label(task.state)} {int(task.progress() * 100)}%"


def clamp_position(
    x: int, y: int, width: int, height: int,
    screen_width: int, screen_height: int, margin: int = 12,
) -> tuple[int, int]:
    """Keep a floating window fully on screen (multi-monitor safe callers)."""
    max_x = max(0, int(screen_width) - int(width) - margin)
    max_y = max(0, int(screen_height) - int(height) - margin)
    return (
        max(margin, min(int(x), max_x)) if max_x >= margin else 0,
        max(margin, min(int(y), max_y)) if max_y >= margin else 0,
    )


def island_geometry(expanded: bool) -> tuple[int, int]:
    return (340, 148) if expanded else (228, 46)
