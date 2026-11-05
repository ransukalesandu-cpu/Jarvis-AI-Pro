"""The one write path from the web UI into the assistant: a typed command.

Why a gate: the classic typed-text path is also where the Privacy Lock PIN and the guest-mode ``/owner``
credential are entered. A web page must never become a credential entry point (its JS memory, devtools
and the bridge are not the native secure prompt), so this gate refuses to forward anything while the
assistant is locked, waiting for a PIN, silent, or in guest mode, and refuses anything shaped like a
credential. It never logs or stores the text. No Qt.
"""
from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable

MAX_TEXT = 500
MIN_INTERVAL = 0.5        # seconds between commands
MAX_PER_MINUTE = 30

REASONS = ("sent", "empty", "too_long", "locked", "auth_required", "silent", "guest", "credential", "rate_limited", "unavailable")
AVAILABILITY = ("ok", "locked", "auth_required", "silent", "guest", "unavailable")

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_CREDENTIAL = re.compile(r"^\s*/(owner|pin|auth|login|password)\b", re.IGNORECASE)


def clean(text) -> str:
    return _CONTROL.sub("", str(text or "")).strip()


class CommandGate:
    def __init__(self, sink: Callable[[str], None] | None, manager: Callable[[], object], guest_active: Callable[[], bool],
                 clock: Callable[[], float] = time.monotonic, run: Callable[[Callable[[], None]], None] | None = None):
        self._sink = sink
        self._manager = manager
        self._guest_active = guest_active
        self._clock = clock
        self._run = run or (lambda fn: fn())
        self._last = -1e9
        self._recent: list[float] = []
        self._lock = threading.Lock()

    def availability(self) -> str:
        if self._sink is None:
            return "unavailable"
        try:
            m = self._manager()
            if m.is_privacy_lock_active():
                return "locked"
            if m.needs_pin():
                return "auth_required"
            if m.is_silent():
                return "silent"
            if self._guest_active():
                return "guest"
        except (AttributeError, RuntimeError, OSError):
            return "unavailable"          # cannot prove it is safe -> not available
        return "ok"

    def submit(self, text) -> str:
        t = clean(text)
        if not t:
            return "empty"
        if len(t) > MAX_TEXT:
            return "too_long"
        state = self.availability()
        if state != "ok":
            return state
        if _CREDENTIAL.match(t):
            return "credential"
        now = self._clock()
        with self._lock:
            self._recent = [x for x in self._recent if now - x < 60.0]
            if now - self._last < MIN_INTERVAL or len(self._recent) >= MAX_PER_MINUTE:
                return "rate_limited"
            self._last = now
            self._recent.append(now)
        self._run(lambda: self._sink(t))
        return "sent"
