"""QWebEngine host for the hologram page.

Security model: the page is a local file, JavaScript is the only capability, navigation is
locked to the hologram directory, new windows and permission prompts are refused, the profile
is off-the-record and there is no QWebChannel: the page reports through console lines only.
Raw audio never crosses the bridge, only a smoothed 0..1 level.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QLabel, QStackedLayout, QWidget

from jarvis.core.hologram_theme import backdrop_rgb
from jarvis.hologram import protocol

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
FLUSH_MS = 16          # coalesce high-rate level messages to ~60/s
HEARTBEAT_MS = 1000    # page falls back to "disconnected" if it hears nothing for ~6 s
MAX_RELOADS = 3


def is_allowed_url(url: QUrl) -> bool:
    """True only for files that live inside the hologram directory."""
    if not url.isLocalFile():
        return False
    try:
        path = Path(url.toLocalFile()).resolve()
    except (OSError, ValueError):
        return False
    return path == ROOT or ROOT in path.parents


class _LockedPage(QWebEnginePage):
    report = pyqtSignal(dict)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802 (Qt API)
        return is_allowed_url(url)

    def createWindow(self, window_type):  # noqa: N802
        return None

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        parsed = protocol.parse_report(message)
        if parsed is not None:
            self.report.emit(parsed)


class HologramHost(QWidget):
    """Drop-in replacement for the old visualizer widgets (same setter names)."""

    ready = pyqtSignal(dict)
    failed = pyqtSignal(str)
    quality_changed = pyqtSignal(str)

    def __init__(self, parent=None, *, debug: bool = False, quality: str = "auto"):
        super().__init__(parent)
        self._ready = False
        self._failed = False
        self._reloads = 0
        self._pending: dict[str, str] = {}
        self._last: dict[str, str] = {}
        self._ping = 0
        self._last_pong = 0.0
        self._debug = debug
        self._quality = quality
        self.ready_info: dict = {}

        self._profile = QWebEngineProfile(self)  # unnamed -> off-the-record, nothing on disk
        self._page = _LockedPage(self._profile, self)
        # Paint the HUD backdrop colour, not transparency: a transparent web view over an
        # opaque parent composites to black on some Windows setups (the old QPainter hologram
        # hit the same bug), and an opaque match is invisible against the HUD.
        self._page.setBackgroundColor(QColor(*backdrop_rgb()))
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
        self._page.report.connect(self._on_report)
        self._page.renderProcessTerminated.connect(self._on_process_gone)

        self._view = QWebEngineView(self)
        self._view.setPage(self._page)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._view.setStyleSheet("background: transparent; border: none;")
        self._fallback = QLabel("Hologram unavailable", self)
        self._fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fallback.setStyleSheet("color:#00e5ff;background:transparent;font:11pt 'Courier New';")
        lay = QStackedLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._view)
        lay.addWidget(self._fallback)
        self._stack = lay
        self._view.loadFinished.connect(self._on_loaded)

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush)
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(HEARTBEAT_MS)
        self._heartbeat.timeout.connect(self._send_ping)
        self._load()

    # ── loading / lifecycle ───────────────────────────────────────────────
    def _load(self) -> None:
        q = "?" + ("debug=1&" if self._debug else "") + f"quality={self._quality}"
        self._view.load(QUrl("file:///" + INDEX.as_posix().lstrip("/") + q))

    def _on_loaded(self, ok: bool) -> None:
        if not ok:
            self._fail("page failed to load")

    def _on_process_gone(self, *_args) -> None:
        self._ready = False
        self._heartbeat.stop()
        if self._reloads < MAX_RELOADS:
            self._reloads += 1
            log.warning("hologram render process ended; reload %d/%d", self._reloads, MAX_RELOADS)
            QTimer.singleShot(500, self._load)
        else:
            self._fail("render process keeps crashing")

    def _fail(self, reason: str) -> None:
        if self._failed:
            return
        self._failed = True
        self._stack.setCurrentWidget(self._fallback)
        log.error("hologram disabled: %s", reason)
        self.failed.emit(reason)

    def _on_report(self, rep: dict) -> None:
        kind = rep.get("t")
        if kind == "ready":
            self._ready = True
            self._reloads = 0
            self.ready_info = rep
            self._last_pong = time.monotonic()
            self._last.clear()  # a (re)loaded page knows nothing: resend current settings
            self._heartbeat.start()
            for text in list(self._sticky.values()):
                self._send(text)
            self.ready.emit(rep)
        elif kind == "pong":
            self._last_pong = time.monotonic()
        elif kind == "quality":
            self.quality_changed.emit(str(rep.get("tier", "")))
        elif kind == "error":
            log.warning("hologram page error: %s", rep.get("code", "?"))
            if not self._ready:
                self._fail(str(rep.get("code", "start error")))
        elif kind in ("contextlost", "contextrestored"):
            log.info("hologram %s", kind)

    @property
    def is_ready(self) -> bool:
        return self._ready and not self._failed

    @property
    def is_failed(self) -> bool:
        return self._failed

    # ── sending ───────────────────────────────────────────────────────────
    _sticky: dict = {}

    def _send(self, text: str | None) -> None:
        if text is None or not self._ready:
            return
        # The payload is validated JSON produced by protocol.encode; it is passed as a JS
        # string literal built from json.dumps so it cannot break out of the call.
        import json as _json
        self._page.runJavaScript(f"window.__holo&&window.__holo.receive({_json.dumps(text)})")

    def _post(self, kind: str, *, sticky: bool = False, rate_limited: bool = False, **fields) -> None:
        text = protocol.encode(kind, **fields)
        if text is None:
            return
        if sticky:
            self._sticky = {**self._sticky, kind: text}
        if self._last.get(kind) == text:
            return
        self._last[kind] = text
        if rate_limited:
            self._pending[kind] = text
            if not self._flush_timer.isActive():
                self._flush_timer.start()
        else:
            self._send(text)

    def _flush(self) -> None:
        if not self._pending:
            self._flush_timer.stop()
            return
        pending, self._pending = self._pending, {}
        for text in pending.values():
            self._send(text)

    def _send_ping(self) -> None:
        self._ping = (self._ping + 1) % 2_000_000_000
        self._send(protocol.encode("ping", n=self._ping))

    # ── public API (names match the old visualizer widgets) ───────────────
    def set_state(self, name: str) -> None:
        self._post("state", sticky=True, v=protocol.normalize_state(name))

    def set_profile(self, profile_id: str) -> None:
        self._post("profile", sticky=True, v=profile_id if profile_id in protocol.PROFILES else "jarvis")

    def set_audio_energy(self, level: float) -> None:
        """Microphone / input level (0..1)."""
        self._post("input", rate_limited=True, v=_clamp01(level))

    def set_output_level(self, level: float, openness: float | None = None, width: float | None = None) -> None:
        """Playback (speaker) level (0..1), optionally with mouth openness/width hints."""
        fields: dict = {"v": _clamp01(level)}
        if openness is not None:
            fields["open"] = _clamp01(openness)
        if width is not None:
            fields["width"] = max(-1.0, min(1.0, float(width)))
        self._post("output", rate_limited=True, **fields)

    def end_output(self) -> None:
        self._last.pop("output", None)
        self._pending.pop("output", None)
        self._post("output_end")

    def set_viseme(self, viseme_id: str, weight: float) -> None:
        """Compatibility shim: map legacy viseme weights to mouth openness/width."""
        table = {"aa": (1.0, 0.0), "oh": (0.6, -0.3), "ou": (0.35, -0.8), "ee": (0.4, 0.8), "ch": (0.3, 0.4), "m": (0.0, 0.0)}
        if viseme_id in table and weight > 0.5:
            o, w = table[viseme_id]
            self._viseme = (o, w)

    def set_performance_budget(self, frame_interval_ms: int, particle_scale: float, glow_scale: float) -> None:
        self._post("budget", sticky=True, frame_ms=max(8, min(100, int(frame_interval_ms))),
                   particles=max(0.2, min(1.0, float(particle_scale))), glow=max(0.0, min(1.5, float(glow_scale))))

    def set_reduced_motion(self, enabled: bool) -> None:
        self._post("motion", sticky=True, reduced=bool(enabled))

    def set_glow_intensity(self, value: float) -> None:
        self._post("glow", sticky=True, v=max(0.0, min(1.5, float(value))))

    def set_effects_enabled(self, enabled: bool) -> None:
        self._post("effects", sticky=True, v=bool(enabled))

    def set_voice_reactive(self, enabled: bool) -> None:
        self._post("voice_reactive", sticky=True, v=bool(enabled))

    def set_animation_speed(self, _value: float) -> None:  # accepted for compatibility
        return

    def set_quality(self, mode: str) -> None:
        self._post("quality", sticky=True, v=mode if mode in protocol.QUALITIES else "auto")

    def set_visible_hint(self, visible: bool) -> None:
        self._post("visible", sticky=True, v=bool(visible))

    def showEvent(self, e):  # noqa: N802
        self.set_visible_hint(True)
        super().showEvent(e)

    def hideEvent(self, e):  # noqa: N802
        self.set_visible_hint(False)
        super().hideEvent(e)

    def shutdown(self) -> None:
        """Stop timers and tear the page down (idempotent)."""
        self._flush_timer.stop()
        self._heartbeat.stop()
        self._ready = False
        try:
            self._view.setPage(None)
            self._page.deleteLater()
            self._profile.deleteLater()
        except RuntimeError:
            pass

    def closeEvent(self, e):  # noqa: N802
        self.shutdown()
        super().closeEvent(e)


def _clamp01(v: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if f != f else max(0.0, min(1.0, f))
