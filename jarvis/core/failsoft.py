"""Make intentional fail-soft handling visible instead of invisible.

Why this module exists
----------------------
JARVIS is designed to *fail soft*: a missing optional dependency, an
unavailable audio device or an offline network must never take the assistant
down. The usual way to express that is

    try:
        do_something_optional()
    except Exception:
        pass

The pattern is right; the silent ``pass`` is not. Two real bugs shipped that
way:

* the memory panel imported ``get_memory_manager`` (which does not exist) and
  swallowed the ``ImportError`` on every call, so it showed zero facts forever;
* the scheduler panel called ``ProspectiveMemory().get_pending_tasks()`` (also
  nonexistent), so it always said "No upcoming tasks".

Both looked like working features. Nobody could tell, because nothing was
recorded anywhere.

``suppress()`` is the approved one-line replacement::

    try:
        do_something_optional()
    except Exception:
        failsoft.suppress("core.audio_playback:probe_device")

It never raises, never changes control flow, and it records what was swallowed
in a bounded in-memory table that :func:`summary` exposes. ``diagnose.py`` and
the test suite can then answer "what is quietly broken right now?" without
anyone re-reading 700 except blocks.

Rules of thumb
--------------
* Genuinely expected and *boring* (device absent, file missing, optional
  package not installed) → ``suppress()``; that is what it is for.
* Unexpected failure where the feature still works degraded → log a warning
  first, then ``suppress()``.
* A failure the user must know about → do not swallow it; let it propagate or
  show it in the UI.

Set ``JARVIS_FAILSOFT_LOG=1`` to also emit each suppressed error as a WARNING
log line (off by default so the normal run stays quiet, and so a single broken
optional path cannot spam the console).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass

__all__ = [
    "SuppressedError",
    "reset",
    "suppress",
    "summary",
    "report",
    "count",
]

_LOG = logging.getLogger("Jarvis.FailSoft")

# Bounded so a failure inside a 20 Hz audio callback cannot grow memory.
_MAX_EVENTS = 200

_events: deque["SuppressedError"] = deque(maxlen=_MAX_EVENTS)
_lock = threading.Lock()

# Identical failures repeat constantly (a missing device is probed on every
# utterance). Count them instead of filling the ring buffer with duplicates.
_counts: dict[tuple[str, str, str], int] = {}


def _logging_enabled() -> bool:
    return os.environ.get("JARVIS_FAILSOFT_LOG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class SuppressedError:
    """One swallowed exception, as recorded by :func:`suppress`."""

    feature: str
    exception_type: str
    message: str
    location: str
    when: float

    def as_dict(self) -> dict:
        return {
            "feature": self.feature,
            "exception_type": self.exception_type,
            "message": self.message,
            "location": self.location,
            "when": self.when,
        }


def _caller_location() -> str:
    """Best-effort ``file:line`` of the code that swallowed the error."""
    try:
        frame = sys._getframe(2)
        return f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_lineno}"
    except Exception:  # pragma: no cover - interpreter without frames
        return ""


def suppress(feature: str) -> None:
    """Record the exception currently being handled. Never raises.

    Call it *inside* an ``except`` block in place of ``pass``::

        except Exception:
            failsoft.suppress("core:probe_speaker")

    ``feature`` should name the subsystem and what it was trying to do, in the
    form ``"<module>:<operation>"``. It is the key used for the counts, so it
    must be a literal string, not an f-string built from changing values.
    """
    try:
        exc_type, exc, _tb = sys.exc_info()
    except Exception:  # pragma: no cover - interpreter without exc_info
        return

    if exc is None:
        # Called outside an handler: almost certainly a bug in the caller.
        _LOG.debug("failsoft.suppress(%r) called outside an except block", feature)
        exc_type, exc = RuntimeError, RuntimeError("suppress() outside except")

    kind = getattr(exc_type, "__name__", "Exception")
    message = str(exc)
    # Keep messages bounded; some carry a whole HTML page or stack.
    if len(message) > 300:
        message = message[:297] + "..."

    key = (feature, kind, message)
    try:
        with _lock:
            _counts[key] = _counts.get(key, 0) + 1
            seen = _counts[key]
            if seen == 1:
                _events.append(
                    SuppressedError(
                        feature=feature,
                        exception_type=kind,
                        message=message,
                        location=_caller_location(),
                        when=time.time(),
                    )
                )
    except Exception:  # pragma: no cover - defensive
        return

    if _logging_enabled():
        _LOG.warning("suppressed in %s (%s): %s", feature, kind, message)


def summary(*, limit: int | None = None) -> list[dict]:
    """Suppressed errors, most frequent first, with repeat counts."""
    try:
        with _lock:
            rows = [
                {
                    "feature": event.feature,
                    "exception_type": event.exception_type,
                    "message": event.message,
                    "location": event.location,
                    "when": event.when,
                    "count": _counts.get(
                        (event.feature, event.exception_type, event.message), 1
                    ),
                }
                for event in _events
            ]
    except Exception:  # pragma: no cover - defensive
        return []
    rows.sort(key=lambda row: row["count"], reverse=True)
    return rows if limit is None else rows[:limit]


def count() -> int:
    """Total number of suppressed exceptions since start, repeats included."""
    try:
        with _lock:
            return sum(_counts.values())
    except Exception:  # pragma: no cover - defensive
        return 0


def report(*, limit: int = 10) -> str:
    """Human-readable summary, or an empty string when nothing was swallowed."""
    rows = summary(limit=limit)
    if not rows:
        return ""
    lines = [f"Fail-soft: {count()} suppressed error(s) in {len(rows)} distinct place(s)"]
    for row in rows:
        lines.append(
            f"  ×{row['count']:<4} {row['feature']} — {row['exception_type']}: "
            f"{row['message']}  ({row['location']})"
        )
    return "\n".join(lines)


def reset() -> None:
    """Forget everything recorded so far (used by tests)."""
    with _lock:
        _events.clear()
        _counts.clear()
