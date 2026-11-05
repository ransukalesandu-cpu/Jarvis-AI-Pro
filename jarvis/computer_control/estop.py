"""Process-wide emergency stop for computer control.

One :class:`EmergencyStop` per process. Triggering it stops every action that
is running *now*; actions that start afterwards are unaffected (a stop is not a
permanent kill switch, so "Jarvis, stop" followed by a new request works).

How "now" is decided: every trigger increments a generation counter. A running
task holds a :class:`StopToken` taken when it started; the token reports
"stopped" as soon as the generation moves past the one it captured. Holding the
latch with :meth:`EmergencyStop.engage` blocks new actions too, until
:meth:`EmergencyStop.release`.

Wiring (owner decision 6) — the stop fires from every existing cancel path:

* ``JobManager.request_cancel`` / ``cancel`` set the job's ``cancel_event``,
  which the runner checks next to the token (a per-job stop);
* ``ToolDispatchMixin._stop_everything`` (used by the "Jarvis, stop" stop word)
  calls :func:`trigger` (a global stop);
* ``JarvisLive.interrupt`` (the HUD interrupt button, ``_do_interrupt``) calls
  :func:`trigger` as well.

Checks happen between every action and inside every wait (:meth:`StopToken.wait`
replaces ``time.sleep``), so the measured stop latency is the poll interval
(``POLL_S``) plus the time the current primitive input call takes.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

POLL_S = 0.02


class EmergencyStopped(RuntimeError):
    """Raised inside an action when the emergency stop (or job cancel) fired."""


@dataclass
class StopEvent:
    generation: int
    reason: str
    source: str
    at: float = field(default_factory=time.monotonic)


class EmergencyStop:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._engaged = False
        self._last: Optional[StopEvent] = None
        self._changed = threading.Condition(self._lock)
        self._listeners: list[Callable[[StopEvent], None]] = []

    # -- state -------------------------------------------------------------
    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def engaged(self) -> bool:
        with self._lock:
            return self._engaged

    @property
    def last(self) -> Optional[StopEvent]:
        with self._lock:
            return self._last

    def token(self, cancel_event: Optional[threading.Event] = None) -> "StopToken":
        with self._lock:
            return StopToken(self, self._generation, cancel_event)

    # -- control -----------------------------------------------------------
    def trigger(self, reason: str = "emergency stop", *, source: str = "owner",
                latch: bool = False) -> StopEvent:
        """Stop everything running now. Thread-safe and cheap; never raises."""
        with self._lock:
            self._generation += 1
            if latch:
                self._engaged = True
            event = StopEvent(self._generation, str(reason), str(source))
            self._last = event
            self._changed.notify_all()
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event)
            except Exception:
                from jarvis.core import failsoft
                failsoft.suppress("computer_control.estop:listener")
        return event

    def engage(self, reason: str = "emergency stop held", source: str = "owner") -> StopEvent:
        return self.trigger(reason, source=source, latch=True)

    def release(self) -> None:
        with self._lock:
            self._engaged = False
            self._changed.notify_all()

    def add_listener(self, fn: Callable[[StopEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(fn)

        def remove() -> None:
            with self._lock:
                if fn in self._listeners:
                    self._listeners.remove(fn)
        return remove

    def _wait_change(self, generation: int, timeout: float) -> None:
        with self._lock:
            if self._generation == generation:
                self._changed.wait(timeout)


class StopToken:
    """What a running action consults: global stop + its own job's cancel."""

    def __init__(self, owner: EmergencyStop, generation: int,
                 cancel_event: Optional[threading.Event] = None) -> None:
        self._owner = owner
        self._generation = generation
        self._cancel = cancel_event

    def reason(self) -> str:
        """'' while the action may continue, else why it must stop."""
        if self._cancel is not None and self._cancel.is_set():
            return "the job was cancelled"
        owner = self._owner
        if owner.generation != self._generation:
            last = owner.last
            return f"emergency stop ({last.reason})" if last else "emergency stop"
        if owner.engaged:
            return "emergency stop is held"
        return ""

    def stopped(self) -> bool:
        return bool(self.reason())

    def check(self) -> None:
        reason = self.reason()
        if reason:
            raise EmergencyStopped(reason)

    def wait(self, seconds: float) -> None:
        """Sleep that wakes within ``POLL_S`` of a stop. Raises EmergencyStopped."""
        deadline = time.monotonic() + max(0.0, float(seconds))
        while True:
            self.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._cancel is not None:
                if self._cancel.wait(min(POLL_S, remaining)):
                    self.check()
            else:
                self._owner._wait_change(self._generation, min(POLL_S, remaining))


_STOP = EmergencyStop()


def get() -> EmergencyStop:
    return _STOP


def trigger(reason: str = "emergency stop", *, source: str = "owner") -> StopEvent:
    """Module-level shortcut used by the stop word / interrupt / UI paths."""
    return _STOP.trigger(reason, source=source)


def token(cancel_event: Optional[threading.Event] = None) -> StopToken:
    return _STOP.token(cancel_event)


def reset_for_tests() -> None:
    global _STOP
    _STOP = EmergencyStop()
