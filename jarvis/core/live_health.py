"""Counters for the Gemini Live session, so flakiness is measured, not guessed.

The run loop calls ``record`` at its connect/disconnect points; ``snapshot`` and
``describe`` feed the ``self_check`` tool. In-memory only, thread-safe, and
bounded: nothing here can slow or break the voice path.
"""
from __future__ import annotations

import threading
import time
from collections import deque

EVENTS = ("connected", "voluntary_reconnect", "unexpected_drop", "error")
_lock = threading.Lock()
_started = time.time()
_totals: dict[str, int] = {e: 0 for e in EVENTS}
_recent: deque[tuple[float, str]] = deque(maxlen=200)
_last_detail: dict[str, str] = {}


def record(event: str, detail: str = "") -> None:
    if event not in _totals:
        return
    with _lock:
        _totals[event] += 1
        _recent.append((time.time(), event))
        if detail:
            _last_detail[event] = str(detail)[:160]


def snapshot(window_s: float = 3600.0, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    with _lock:
        recent = {e: 0 for e in EVENTS}
        for ts, ev in _recent:
            if now - ts <= window_s:
                recent[ev] += 1
        return {"uptime_s": int(now - _started), "totals": dict(_totals),
                "last_window": recent, "window_s": int(window_s),
                "last_detail": dict(_last_detail)}


def describe(window_s: float = 3600.0) -> str:
    s = snapshot(window_s)
    t, w = s["totals"], s["last_window"]
    line = (f"Voice session: {t['connected']} connects, {t['voluntary_reconnect']} planned reconnects, "
            f"{t['unexpected_drop']} unexpected drops since start; last hour: {w['unexpected_drop']} drops.")
    if w["unexpected_drop"] >= 3:
        line += " The connection looks unstable; check the network or the API quota."
    return line


def reset_for_tests() -> None:
    with _lock:
        for e in _totals:
            _totals[e] = 0
        _recent.clear()
        _last_detail.clear()
