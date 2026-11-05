"""The HUD's state bus and its shared animation clock.

One place holds what the interface shows (assistant state, audio level,
persona, performance tier, open windows...) and one clock drives every
animation, so the face, the heart, the orb and the energy wires pulse in step
and all pause together when the window is minimised.

No Qt. Values may be published from any thread: off the owner thread they are
queued and delivered by :meth:`StateBus.drain`, which the UI calls once per
frame, so subscribers always run on the UI thread.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

# Well-known keys. Anything else is allowed; these are what the HUD uses.
ASSISTANT = "assistant.state"      # idle / listening / thinking / speaking / sleeping / error
AUDIO_LEVEL = "audio.level"        # 0..1, the voice being played or heard
MUTED = "audio.muted"
PERSONA = "persona"                # jarvis / bihansa
PERF_TIER = "perf.tier"            # full / balanced / lite
WINDOWS = "windows"                # tuple of open window ids
FOCUS = "focus"                    # id of the focused window, or ""

ALL = "*"


class AnimationClock:
    """Monotonic time for animations, with a frame cap and a pause.

    ``now`` is animation time: it does not advance while paused, so nothing
    jumps when the window comes back. ``frame(wall)`` answers whether a new
    frame is due under the cap and returns its dt.
    """

    def __init__(self, fps_cap: float = 30.0, source: Callable[[], float] = time.monotonic):
        self._source = source
        self._fps = max(1.0, float(fps_cap))
        self._paused = False
        self._t = 0.0
        self._last_wall = source()
        self._last_frame = -1e9
        self.speed = 1.0

    @property
    def fps_cap(self) -> float:
        return self._fps

    @fps_cap.setter
    def fps_cap(self, value: float) -> None:
        self._fps = max(1.0, float(value))

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._advance()
        self._paused = True

    def resume(self) -> None:
        self._last_wall = self._source()
        self._paused = False

    def _advance(self) -> float:
        wall = self._source()
        dt = 0.0 if self._paused else max(0.0, min(0.25, wall - self._last_wall)) * self.speed
        self._last_wall = wall
        self._t += dt
        return dt

    @property
    def now(self) -> float:
        self._advance()
        return self._t

    def frame(self) -> float | None:
        """dt of a new frame, or None when paused or the cap says not yet."""
        if self._paused:
            return None
        wall = self._source()
        if wall - self._last_frame < (1.0 / self._fps) * 0.98:
            return None
        self._last_frame = wall
        return self._advance()


class StateBus:
    """Key/value state with change notifications, delivered on one thread."""

    def __init__(self):
        self._values: dict[str, Any] = {}
        self._subs: dict[str, list[Callable[[str, Any], None]]] = {}
        self._pending: list[tuple[str, Any]] = []
        self._lock = threading.Lock()
        self._owner = threading.get_ident()

    def adopt_thread(self) -> None:
        """Make the calling thread the delivery thread (call from the UI)."""
        self._owner = threading.get_ident()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    def set(self, key: str, value: Any) -> None:
        if threading.get_ident() != self._owner:
            with self._lock:
                self._pending.append((key, value))
            return
        self._apply(key, value)

    def _apply(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._values and self._values[key] == value:
                return
            self._values[key] = value
            subs = list(self._subs.get(key, ())) + list(self._subs.get(ALL, ()))
        for fn in subs:
            try:
                fn(key, value)
            except Exception as exc:        # one bad subscriber must not stop the rest
                print(f"[StateBus] subscriber for {key!r} failed: {exc}")

    def drain(self) -> int:
        """Deliver values queued from other threads; returns how many."""
        with self._lock:
            pending, self._pending = self._pending, []
        latest: dict[str, Any] = {}
        for key, value in pending:          # only the newest value of each key matters
            latest[key] = value
        for key, value in latest.items():
            self._apply(key, value)
        return len(pending)

    def subscribe(self, key: str, fn: Callable[[str, Any], None]) -> Callable[[], None]:
        with self._lock:
            self._subs.setdefault(key, []).append(fn)

        def unsubscribe() -> None:
            with self._lock:
                lst = self._subs.get(key, [])
                if fn in lst:
                    lst.remove(fn)
        return unsubscribe


_BUS: StateBus | None = None
_CLOCK: AnimationClock | None = None


def bus() -> StateBus:
    """The process-wide state bus."""
    global _BUS
    if _BUS is None:
        _BUS = StateBus()
    return _BUS


def clock() -> AnimationClock:
    """The process-wide animation clock."""
    global _CLOCK
    if _CLOCK is None:
        _CLOCK = AnimationClock()
    return _CLOCK
