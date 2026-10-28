"""Thread-safe progress bus between the worker thread and the UI/voice layers.

The runner executes on a background thread; Qt widgets and the speech engine
live elsewhere. Rather than giving the engine a Qt dependency (or touching a
widget from the wrong thread), it publishes plain snapshots here and each
consumer decides how to marshal them. The bus keeps a small bounded history so a
panel opened late can repaint immediately, and every subscriber call is wrapped:
a broken listener must never abort a task.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.models import Task, TaskReport, TaskState


@dataclass(frozen=True)
class AgentEvent:
    """One immutable progress notification."""

    kind: str                      # task_started | planning | step | progress | waiting | finished
    task_id: str = ""
    state: TaskState = TaskState.PENDING
    progress: float = 0.0
    message: str = ""
    at: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "task_id": self.task_id,
            "state": self.state.value,
            "progress": self.progress,
            "message": self.message,
            "at": self.at,
            "data": dict(self.data),
        }


def event_from_task(kind: str, task: Task, *, message: str = "",
                    **data: Any) -> AgentEvent:
    return AgentEvent(
        kind=kind,
        task_id=task.id,
        state=task.state,
        progress=task.progress(),
        message=message,
        data=data,
    )


class EventBus:
    """Bounded publish/subscribe with a replayable tail."""

    def __init__(self, *, history: int = 128):
        self._subscribers: list[Callable[[AgentEvent], None]] = []
        self._history: deque[AgentEvent] = deque(maxlen=max(8, int(history)))
        self._lock = threading.RLock()

    def subscribe(self, callback: Callable[[AgentEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            self.unsubscribe(callback)

        return unsubscribe

    def unsubscribe(self, callback: Callable[[AgentEvent], None]) -> None:
        with self._lock:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

    def publish(self, event: AgentEvent) -> None:
        with self._lock:
            self._history.append(event)
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                # A UI listener must never be able to stop the engine.
                continue

    def publish_report(self, task: Task, report: TaskReport) -> None:
        self.publish(
            AgentEvent(
                kind="finished",
                task_id=task.id,
                state=report.state,
                progress=1.0,
                message=report.headline(),
                data={"report": report.to_dict()},
            )
        )

    def history(self, limit: int = 32) -> list[AgentEvent]:
        with self._lock:
            items = list(self._history)
        return items[-max(1, int(limit)):]

    def latest(self) -> AgentEvent | None:
        with self._lock:
            return self._history[-1] if self._history else None
