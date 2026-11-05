"""QWebEngineView host for the React UI: locked to the bundled dist, no remote content, off the record."""
from __future__ import annotations

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from jarvis.core import failsoft

from . import DIST
from .bridge import WebUIBridge
from .navigation import is_allowed_url
from .telemetry import Telemetry
from .workspace_store import WorkspaceStore

BACKDROP = (5, 8, 13)      # matches --bg in tokens.css; the page paints this, not true transparency
TELEMETRY_MS = 1000
MAX_RELOADS = 3
HOST_VERSION = 1


class _LockedPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802 (Qt API)
        return is_allowed_url(url)

    def createWindow(self, window_type):  # noqa: N802 (Qt API)
        return None

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802 (Qt API)
        return None


class WebUIHost(QWidget):
    ready = pyqtSignal()   # emitted each time the page finishes loading (first load and reloads)

    def __init__(self, parent=None, *, debug: bool = False, workspace_path=None, gate=None):
        super().__init__(parent)
        self._reloads = 0
        self._debug = debug
        self._profile = QWebEngineProfile(self)  # unnamed -> off the record, nothing written to disk
        self._page = _LockedPage(self._profile, self)
        self._page.setBackgroundColor(QColor(*BACKDROP))
        s = self._page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        if hasattr(self._page, "permissionRequested"):
            self._page.permissionRequested.connect(lambda p: p.deny())

        self.bridge = WebUIBridge(self, WorkspaceStore(workspace_path), gate)
        self._channel = QWebChannel(self)
        self._channel.registerObject("jarvis", self.bridge)
        self._page.setWebChannel(self._channel)
        self.bridge.ready.connect(self._on_page_ready)

        self._view = QWebEngineView(self)
        self._view.setPage(self._page)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._view)

        self._telemetry = Telemetry()
        self._timer = QTimer(self)
        self._timer.setInterval(TELEMETRY_MS)
        self._timer.timeout.connect(self._push_metrics)
        self._page.renderProcessTerminated.connect(self._on_process_gone)
        self._view.load(QUrl.fromLocalFile(str(DIST / "index.html")))

    # ── lifecycle ───────────────────────────────────────────────────────
    def _on_page_ready(self) -> None:
        self.bridge.publish("host.hello", version=HOST_VERSION)
        self._push_metrics()
        self.bridge.refresh_availability(force=True)
        self.ready.emit()
        if self.isVisible():
            self._timer.start()

    def _on_process_gone(self, *_a) -> None:
        self._timer.stop()
        if self._reloads < MAX_RELOADS:
            self._reloads += 1
            self._view.reload()

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self._timer.start()

    def hideEvent(self, e):  # noqa: N802
        self._timer.stop()  # no polling while hidden
        super().hideEvent(e)

    def shutdown(self) -> None:
        self._timer.stop()
        try:
            self._page.setWebChannel(None)
            self._view.setPage(None)
        except Exception:
            failsoft.suppress('webui:WebUIHost.shutdown')
        self._page.deleteLater()

    # ── backend -> page ─────────────────────────────────────────────────
    def _push_metrics(self) -> None:
        self.bridge.refresh_availability()       # lock/PIN/guest state can change at any time
        snap = self._telemetry.snapshot()
        if snap is not None:
            self.bridge.publish("system.metrics_updated", **snap)

    def set_state(self, state: str) -> None:
        self.bridge.publish("assistant.state_changed", state=state)

    def set_level(self, level: float, source: str = "output") -> None:
        self.bridge.publish("assistant.audio_level", level=max(0.0, min(1.0, float(level))), source=source)

    def set_muted(self, muted: bool) -> None:
        self.bridge.publish("assistant.muted", muted=bool(muted))

    def set_persona(self, persona: str) -> None:
        self.bridge.publish("ui.persona", persona=persona)

    def set_provider(self, provider: str, model: str, connected: bool, fallback: bool = False) -> None:
        self.bridge.publish("provider.changed", provider=provider, model=model, connected=connected, fallback=fallback)
