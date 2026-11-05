"""Read-only mirror of the HUD log for the web page.

Every line is judged at the moment it is logged: if the assistant is not in a fully normal, unlocked state
(locked, awaiting a PIN, silent, guest mode), nothing is forwarded, because the classic typed-text box logs
what was typed *before* it knows it is a PIN. Lines are redacted, bounded and rate limited. Nothing flows
back from the page.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from jarvis.core import log_tap

from . import redact

BURST = 40            # lines
REFILL_PER_S = 10.0   # sustained lines per second


class LogFeed(QObject):
    line = pyqtSignal(str, str)      # (kind, text); emitted from any thread, delivered on the GUI thread

    def __init__(self, availability: Callable[[], str], clock: Callable[[], float] = time.monotonic, parent=None):
        super().__init__(parent)
        self._availability = availability
        self._clock = clock
        self._tokens = float(BURST)
        self._t = clock()
        self._unsub = log_tap.subscribe(self.tap)

    def tap(self, text: str) -> None:
        try:
            if self._availability() != "ok":              # judged now, on the logging thread, before anything can change
                return
        except (AttributeError, RuntimeError, OSError):
            return
        prepared = redact.prepare(text)
        if prepared is None:
            return
        now = self._clock()
        self._tokens = min(float(BURST), self._tokens + (now - self._t) * REFILL_PER_S)
        self._t = now
        if self._tokens < 1.0:
            return
        self._tokens -= 1.0
        self.line.emit(*prepared)

    def close(self) -> None:
        self._unsub()
