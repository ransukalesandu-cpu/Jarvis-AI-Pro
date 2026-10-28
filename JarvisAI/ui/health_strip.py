"""Live system-health strip and lightweight in-HUD notifications.

Two small pieces of chrome that keep the home screen honest without turning it
back into a dashboard:

``HudStatusStrip``
    A single row of four tiny indicators — microphone, speaker, network, AI
    session — painted from :class:`core.system_status.HealthState`. Each one
    carries a **letter** as well as a colour, so status never depends on hue
    alone, and its tooltip holds the real detail string. Unavailable subsystems
    render as a hollow ring ("—"), never green.

``HudToast``
    A compact, non-modal card for notifications while the hologram is open
    (when minimised, the Dynamic Island shows them instead). One at a time,
    auto-dismiss, dismissible by click or Escape, never blocks input.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from core.hologram_theme import JARVIS_PALETTE, ThemePalette
from core.system_status import HealthState, Notification, SubsystemStatus

__all__ = ["HudStatusStrip", "HudToast"]

_STATE_COLOURS = {
    "ok": QColor("#8ce6b0"),
    "error": QColor("#ff7a7a"),
    "unavailable": QColor("#8b98a3"),
}

_STATE_GLYPHS = {"ok": "●", "error": "!", "unavailable": "○"}

_ORDER = ("microphone", "speaker", "network", "provider")

_SHORT = {"microphone": "MIC", "speaker": "SPK", "network": "NET", "provider": "AI"}


class HudStatusStrip(QWidget):
    """Four compact subsystem indicators, updated from real health snapshots."""

    def __init__(self, parent: QWidget | None = None, palette: ThemePalette | None = None):
        super().__init__(parent)
        self.setObjectName("HudStatusStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedHeight(20)
        self.setMinimumWidth(206)
        self.setFixedWidth(206)
        self._palette = palette or JARVIS_PALETTE
        self._statuses: dict[str, str] = {name: "unavailable" for name in _ORDER}
        self._details: dict[str, str] = {name: "" for name in _ORDER}
        self.setToolTip("System health — hover an indicator for detail")

    def set_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def apply_health(self, health: HealthState) -> None:
        mapping = {
            "microphone": health.microphone,
            "speaker": health.speaker,
            "network": health.network,
            "provider": health.provider,
        }
        for name, status in mapping.items():
            self._set(name, status)

    def set_status(self, name: str, state: str, detail: str = "") -> None:
        """Direct feed for tests and for subsystems the HUD sets by hand."""
        if name not in self._statuses:
            return
        self._statuses[name] = state if state in _STATE_COLOURS else "unavailable"
        self._details[name] = str(detail or "")
        self.update()

    def _set(self, name: str, status: SubsystemStatus) -> None:
        self._statuses[name] = status.state
        self._details[name] = status.detail

    def state_of(self, name: str) -> str:
        return self._statuses.get(name, "unavailable")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        x = 2.0
        metrics = painter.fontMetrics()
        for name in _ORDER:
            state = self._statuses[name]
            colour = _STATE_COLOURS[state]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colour.red(), colour.green(), colour.blue(), 46))
            painter.drawEllipse(QRectF(x, 4, 12, 12))
            painter.setPen(QPen(colour, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(x, 4, 12, 12))
            painter.setPen(QPen(colour))
            painter.drawText(QRectF(x, 4, 12, 12), int(Qt.AlignmentFlag.AlignCenter), _STATE_GLYPHS[state])
            label = _SHORT[name]
            painter.setPen(QPen(QColor(190, 196, 203, 220)))
            painter.drawText(QRectF(x + 15, 3, metrics.horizontalAdvance(label) + 2, 15),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            x += 19 + metrics.horizontalAdvance(label) + 9
        painter.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Tooltip follows the indicator under the cursor (real detail text)."""
        x = 2.0
        metrics = self.fontMetrics()
        for name in _ORDER:
            width = 19 + metrics.horizontalAdvance(_SHORT[name]) + 9
            if x <= event.position().x() <= x + width:
                state = self._statuses[name]
                detail = self._details.get(name) or "no detail reported"
                self.setToolTip(f"{name.title()}: {state} — {detail}")
                break
            x += width
        super().mouseMoveEvent(event)


class HudToast(QWidget):
    """Compact notification card. One instance is reused; it shows, then hides."""

    sig_dismissed = pyqtSignal()
    sig_activated = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None, palette: ThemePalette | None = None):
        super().__init__(parent)
        self.setObjectName("HudToast")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._palette = palette or JARVIS_PALETTE
        self._title = ""
        self._body = ""
        self._priority = 2
        self._note: Notification | None = None
        self.resize(340, 62)
        self.hide()
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_hide_timeout)

    def set_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def show_notification(self, note: Notification, duration_ms: int = 5200) -> None:
        self._note = note
        self._title = note.title[:60]
        self._body = note.body[:110]
        self._priority = note.priority
        self.show()
        self.raise_()
        self._hide_timer.start(max(2500, min(12000, duration_ms)))
        self.update()

    def _on_hide_timeout(self) -> None:
        try:
            self.dismiss()
        except RuntimeError:
            pass

    def dismiss(self) -> None:
        self._hide_timer.stop()
        self._note = None
        if self.isVisible():
            self.hide()
            self.sig_dismissed.emit()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        accent = QColor(*self._palette.accent)
        if self._priority <= 1:
            accent = QColor("#ff8f5a")
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 170), 1.2))
        painter.setBrush(QColor(9, 13, 19, 232))
        painter.drawPath(path)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QPen(QColor("#f3eee5")))
        painter.drawText(QRectF(14, 8, rect.width() - 28, 18),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._title)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QPen(QColor(205, 206, 212, 210)))
        painter.drawText(QRectF(14, 28, rect.width() - 28, 26),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), self._body)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        if self._note is not None:
            self.sig_activated.emit(self._note.source)
        self.dismiss()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return
        super().keyPressEvent(event)
