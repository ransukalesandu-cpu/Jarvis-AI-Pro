"""The QWebChannel object the page talks to. It holds no backend objects and exposes no privileged call."""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from . import contract


class WebUIBridge(QObject):
    event = pyqtSignal(str)            # Python -> page (validated JSON)
    ready = pyqtSignal()               # the page connected and subscribed
    ping_received = pyqtSignal(int)    # heartbeat from the page

    @pyqtSlot(str)
    def request(self, raw: str) -> None:  # noqa: D401 - Qt slot
        msg = contract.parse_request(raw)
        if msg is None:
            return
        if msg["kind"] == "ready":
            self.ready.emit()
        elif msg["kind"] == "ping":
            self.ping_received.emit(int(msg["n"]))

    def publish(self, kind: str, **fields) -> bool:
        text = contract.encode_event(kind, **fields)
        if text is None:
            return False
        self.event.emit(text)
        return True
