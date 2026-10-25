"""Helpers for promptly stopping locally buffered assistant playback."""
from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Any


def interrupt_playback(
    interrupt_event: Event,
    output_stream: Any = None,
    *,
    on_error: Callable[[str], Any] | None = None,
) -> bool:
    """Signal the playback worker to discard buffered PCM and abort device output.

    Returns True when no device abort was needed or the abort succeeded.
    Returns False if the device abort raised; the interrupt event remains set
    so the worker can still clear its private buffer when it next runs.
    """
    interrupt_event.set()
    if output_stream is None:
        return True
    try:
        output_stream.abort()
        return True
    except Exception as exc:
        if on_error is not None:
            try:
                on_error(type(exc).__name__)
            except Exception:
                pass
        return False
