"""Keep PortAudio callback failures from terminating the native audio stream.

Failures are reported at most once per operation per cooldown window so a
broken detector cannot flood the incident log on every microphone block.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

_LOCK = threading.Lock()
_LAST_REPORTED: dict[str, float] = {}
_QUEUE_STATS = {"enqueued": 0, "dropped_full": 0}


def guarded_audio_callback(
    operation: str,
    callback: Callable[..., Any],
    *args: Any,
    on_error: Callable[[Exception, str], Any] | None = None,
    cooldown_seconds: float = 30.0,
    **kwargs: Any,
) -> bool:
    """Run one audio callback; return False on error without raising it.

    Only the first failure for a given operation is reported during the
    cooldown. Diagnostic failures are swallowed too, because this function
    runs on the time-sensitive audio thread.
    """
    try:
        callback(*args, **kwargs)
        return True
    except Exception as exc:
        now = time.monotonic()
        key = str(operation)[:200] or "voice:audio_callback"
        with _LOCK:
            previous = _LAST_REPORTED.get(key)
            should_report = previous is None or now - previous >= max(0.0, float(cooldown_seconds))
            if should_report:
                _LAST_REPORTED[key] = now
        if should_report and on_error is not None:
            try:
                on_error(exc, key)
            except Exception:
                pass
        return False


def enqueue_audio_frame(queue: Any, item: Any) -> bool:
    """Queue one real-time audio frame and count accepted/dropped frames.

    The caller should schedule this on the queue's owning event loop. When
    the consumer falls behind, drop the newest frame rather than accumulating
    latency or raising an unhandled event-loop exception.
    """
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        with _LOCK:
            _QUEUE_STATS["dropped_full"] += 1
        return False
    with _LOCK:
        _QUEUE_STATS["enqueued"] += 1
    return True


def audio_queue_snapshot() -> dict[str, int]:
    """Return a thread-safe, read-only copy of audio queue counters."""
    with _LOCK:
        return dict(_QUEUE_STATS)
