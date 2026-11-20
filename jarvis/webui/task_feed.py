"""Read-only mirror of the Task Flow tracker (core/task_flow.py) for the web page.

* ``task.flow``     one flow snapshot whenever it changes (and the recent ones when the page (re)loads)
* ``ui.task_flow``  "window" / "page" / "hide", when the owner asks (``show_task_progress`` tool)

Like the log feed, nothing is forwarded unless the assistant is in a fully normal, unlocked state
(not locked, not asking for a PIN, not silent, not in guest mode); that is judged at the moment the
flow changes. Flow text is already short and redacted by the tracker. Nothing flows back from the page.

It also names flows: ``You: …`` lines from the HUD log (typed or transcribed) become the title of the
tool flow they started. Autonomous tasks publish on events that the runner throttles, so a light poll
(only while a task is active, and only if the agent service already exists) keeps their steps live.
"""
from __future__ import annotations

import sys
from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from jarvis.core import failsoft, log_tap, task_flow

from . import redact

POLL_MS = 700
REPLAY = 10            # flows re-sent to a page that just (re)loaded


class TaskFeed(QObject):
    _out = pyqtSignal(str, object)      # emitted from any thread, delivered on the GUI thread

    def __init__(self, host, availability: Callable[[], str], tracker: task_flow.FlowTracker | None = None, parent=None):
        super().__init__(parent or host)
        self._host = host
        self._availability = availability
        self._tracker = tracker or task_flow.tracker()
        self._out.connect(self._deliver)
        self._unsub = [self._tracker.subscribe(self._on_tracker), log_tap.subscribe(self._on_log)]
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)
        self._timer.start()
        host.ready.connect(self.replay)

    def _allowed(self) -> bool:
        try:
            return self._availability() == "ok"
        except (AttributeError, RuntimeError, OSError):
            return False

    # any thread
    def _on_tracker(self, kind: str, payload) -> None:
        if self._allowed():                      # judged now, before anything can change
            self._out.emit(kind, payload)

    def _on_log(self, text: str) -> None:
        prepared = redact.prepare(text)
        if prepared is not None and prepared[0] == "you":
            self._tracker.note_command(prepared[1])

    # GUI thread
    def _deliver(self, kind: str, payload) -> None:
        if kind == "flow":
            self._host.bridge.publish("task.flow", flow=payload)
        elif kind == "view":
            self._host.bridge.publish("ui.task_flow", view=payload)

    def replay(self) -> None:
        if not self._allowed():
            return
        for flow in self._tracker.flows()[-REPLAY:]:
            self._host.bridge.publish("task.flow", flow=flow)

    def poll(self) -> None:
        integration = sys.modules.get("jarvis.agent.integration")   # never import (or create) the agent just to poll
        if integration is None:
            return
        try:
            service = integration.peek_service()
            if service is not None:
                service.mirror_active_flow()
        except Exception:
            failsoft.suppress("webui.task_feed:poll")

    def close(self) -> None:
        self._timer.stop()
        for fn in self._unsub:
            fn()
        self._unsub = []
