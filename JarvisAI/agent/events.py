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
from dataclasses from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from agent.models import Task, TaskReport, TaskState

from core import failsoft


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
    sequence: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "task_id": self.task_id,
            "state": self.state.value,
            "progress": self.progress,
            "message": self.message,
            "at": self.at,
            "data": dict(self.data),
            "sequence": self.sequence,
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
        self._changed = threading.Condition(self._lock)
        self._sequence = 0

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
        with self._changed:
            self._sequence += 1
            event = replace(event, sequence=self._sequence)
            self._history.append(event)
            subscribers = list(self._subscribers)
            self._changed.notify_all()
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                # A UI listener must never be able to stop the engine.
                failsoft.suppress("agent.events:publish")
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

    def events_since(
        self, sequence: int = 0, *, timeout: float = 0.0, limit: int = 32
    ) -> list[AgentEvent]:
        """Read a replayable progress stream after a cursor, optionally waiting.

        The cursor is monotonic for this EventBus lifetime. If the requested
        cursor predates the bounded history, the oldest retained events are
        returned; consumers can detect the gap from the first sequence number.
        """
        cursor = max(0, int(sequence))
        wait_s = max(0.0, min(float(timeout), 30.0))
        with self._changed:
            if not any(item.sequence > cursor for item in self._history) and wait_s:
                self._changed.wait_for(
                    lambda: any(item.sequence > cursor for item in self._history),
                    timeout=wait_s,
                )
            items = [item for item in self._history if item.sequence > cursor]
            return items[:max(1, min(int(limit), 128))]

    def latest(self) -> AgentEvent | None:
        with self._lock:
            return self._history[-1] if self._history else None
