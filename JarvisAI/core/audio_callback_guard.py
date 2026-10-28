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

from core import failsoft

_LOCK = threading.Lock()
_LAST_REPORTED: dict[str, float] = {}


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
                failsoft.suppress('core.audio_callback_guard:guarded_audio_callback')
        return False


def enqueue_audio_frame(queue: Any, item: Any) -> bool:
    """Queue one real-time audio frame without leaking QueueFull exceptions.

    The caller should schedule this on the queue's owning event loop. When
    the consumer falls behind, drop the newest frame rather than accumulating
    latency or raising an unhandled exception on the event loop.
    """
    try:
        queue.put_nowait(item)
        return True
    except asyncio.QueueFull:
        return False
