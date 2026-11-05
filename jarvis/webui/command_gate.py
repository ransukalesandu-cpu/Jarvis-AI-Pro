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

REASONS = ("sent", "empty", "too_long", "locked", "auth_required", "silent", "guest", "credential", "rate_limited", "unavailable", "done", "noop")
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


MODE_ACTIONS = ("mode_jarvis", "mode_bihansa")
PERF_ACTIONS = ("perf_auto", "perf_full", "perf_balanced", "perf_lite")
# Changing how JARVIS behaves (persona, performance) needs the same fully-normal state as unmuting the microphone.
GUARDED = frozenset({"unmute", *MODE_ACTIONS, *PERF_ACTIONS})
ACTIONS = ("interrupt", "mute", "unmute", "fullscreen", *MODE_ACTIONS, *PERF_ACTIONS)


class ControlGate:
    """Small allow-listed controls. Things that stop or quiet JARVIS (interrupt, mute) are always allowed; turning
    the microphone back on is not allowed from the page while locked / awaiting a PIN / silent / in guest mode."""

    def __init__(self, gate: CommandGate, actions: dict[str, Callable[[], None]], is_muted: Callable[[], bool],
                 clock: Callable[[], float] = time.monotonic, already: dict[str, Callable[[], bool]] | None = None):
        self._gate, self._actions, self._is_muted, self._clock = gate, actions, is_muted, clock
        self._already = already or {}      # action -> "is it already in that state?" (answers "noop")
        self._last = -1e9

    def do(self, action) -> str:
        fn = self._actions.get(action) if action in ACTIONS else None
        if fn is None:
            return "unavailable"
        now = self._clock()
        if now - self._last < 0.3:
            return "rate_limited"
        try:
            muted = bool(self._is_muted())
        except (AttributeError, RuntimeError):
            return "unavailable"
        if action == "mute" and muted or action == "unmute" and not muted:
            return "noop"
        check = self._already.get(action)
        if check is not None:
            try:
                if check():
                    return "noop"
            except (AttributeError, RuntimeError, OSError):
                return "unavailable"
        if action in GUARDED:
            state = self._gate.availability()
            if state != "ok":
                return state
        self._last = now
        fn()
        return "done"
