"""The QWebChannel object the page talks to. It holds no backend objects and exposes no privileged call."""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from . import contract
from .workspace_store import LAST, WorkspaceStore


class WebUIBridge(QObject):
    event = pyqtSignal(str)            # Python -> page (validated JSON)
    ready = pyqtSignal()               # the page connected and subscribed
    ping_received = pyqtSignal(int)    # heartbeat from the page
    capability = pyqtSignal(bool)      # the page can (True) or cannot (False) render the 3D hologram

    def __init__(self, parent=None, store: WorkspaceStore | None = None, gate=None, controls=None, links=None, jobs=None,
                 features=None):
        super().__init__(parent)
        self.features = features       # callable(feature) -> (summary, items); default: features_feed.snapshot
        self.store = store or WorkspaceStore()
        self.controls = controls       # ControlGate or None
        self.jobs = jobs               # JobGate or None
        self.links = links             # LinkGate or None
        self.gate = gate               # CommandGate or None (=> commands unavailable)
        self._avail = None

    @pyqtSlot(str)
    def request(self, raw: str) -> None:  # noqa: D401 - Qt slot
        msg = contract.parse_request(raw)
        if msg is None:
            return
        if msg["kind"] == "ready":
            self.ready.emit()
        elif msg["kind"] == "ping":
            self.ping_received.emit(int(msg["n"]))
        elif msg["kind"] == "hologram.capability":
            self.capability.emit(bool(msg["webgl2"]))
        elif msg["kind"] == "workspace.save":
            if self.store.save(msg["name"], msg["layout"]) and msg["name"].strip().lower() != LAST:
                self._publish_list()
        elif msg["kind"] == "workspace.load":
            n = msg["name"].strip().lower()
            self.publish("workspace.loaded", name=n, layout=self.store.load(n))
        elif msg["kind"] == "workspace.delete":
            self.store.delete(msg["name"])
            self._publish_list()
        elif msg["kind"] == "workspace.list":
            self._publish_list()
        elif msg["kind"] == "prefs.load":
            self.publish("ui.prefs", prefs=self.store.load_prefs())
        elif msg["kind"] == "prefs.save":
            self.store.save_prefs(msg["prefs"])
        elif msg["kind"] == "control.do":
            self.publish("control.result", reason=self.controls.do(msg["action"]) if self.controls else "unavailable")
        elif msg["kind"] == "job.cancel":
            self.publish("control.result", reason=self.jobs.cancel(msg["id"]) if self.jobs else "unavailable")
        elif msg["kind"] == "news.open":
            self.publish("control.result", reason=self.links.open(msg["index"]) if self.links else "unavailable")
        elif msg["kind"] == "feature.refresh":
            self._publish_feature(msg["feature"])
        elif msg["kind"] == "command.submit":
            self.publish("command.result", reason=self.gate.submit(msg["text"]) if self.gate else "unavailable")
            self.refresh_availability()

    def refresh_availability(self, force: bool = False) -> None:
        """Tell the page whether typing a command is allowed right now (only when it changes)."""
        state = self.gate.availability() if self.gate else "unavailable"
        if force or state != self._avail:
            self._avail = state
            self.publish("command.availability", state=state)

    def _publish_feature(self, feature: str) -> None:
        """Snapshot of one feature for the Features Hub, only while typing a command would be allowed."""
        from . import features_feed
        state = self.gate.availability() if self.gate else "unavailable"
        if state != "ok":
            self.publish("feature.snapshot", feature=feature, summary=features_feed.UNAVAILABLE.get(state, "Not available"),
                         items=[])
            return
        summary, items = (self.features or features_feed.snapshot)(feature)
        if not self.publish("feature.snapshot", feature=feature, summary=summary, items=items):
            self.publish("feature.snapshot", feature=feature, summary="Snapshot rejected (too large)", items=[])

    def _publish_list(self) -> None:
        self.publish("workspace.list", names=self.store.names())

    def publish(self, kind: str, **fields) -> bool:
        text = contract.encode_event(kind, **fields)
        if text is None:
            return False
        self.event.emit(text)
        return True
