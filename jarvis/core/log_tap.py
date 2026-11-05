"""A tiny observer hook on the HUD's log, so other views can mirror it without touching the log panel's internals.

No Qt. ``publish`` is called from whatever thread logged the line, so observers must be thread-safe and fast.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

_observers: list[Callable[[str], None]] = []
_lock = threading.Lock()


def subscribe(fn: Callable[[str], None]) -> Callable[[], None]:
    with _lock:
        _observers.append(fn)

    def unsubscribe() -> None:
        with _lock:
            if fn in _observers:
                _observers.remove(fn)
    return unsubscribe


def publish(text: str) -> None:
    with _lock:
        subs = list(_observers)
    for fn in subs:
        try:
            fn(text)
        except Exception as exc:          # a broken observer must never break logging
            print(f"[log_tap] observer failed: {type(exc).__name__}")
