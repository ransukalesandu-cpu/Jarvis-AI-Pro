"""Pill-shaped floating "Dynamic Island" shown while JARVIS is minimised.

Why this exists
---------------
Minimising the HUD used to leave an ordinary square window (or a taskbar entry
that told the user nothing). The island is a frameless, always-on-top pill that
keeps the assistant *and its live state* visible while the big hologram is
away:

* it mirrors the real visual state (idle / listening / thinking / speaking /
  error) fed from the same bridge as the HUD;
* it shows the live task summary and battery truthfully, or nothing at all when
  that information is unavailable;
* clicking it restores the HUD, dragging moves it, Escape collapses it, and it
  is keyboard reachable (it is focusable and accepts Space/Enter/Escape).

Hard rules baked in
-------------------
* The island is a *view*. It never stops the microphone, playback or tasks;
  nothing in this module talks to audio or the session at all.
* Window flags are applied defensively: ``WindowStaysOnTopHint`` and
  ``FramelessWindowHint`` behave differently per compositor, so a platform that
  rejects translucent windows still gets a working pill (opaque fallback flag
  handled by :meth:`DynamicIsland._apply_window_flags`).
* Auto-collapse runs on a QTimer owned by the widget and is cancelled whenever a
  new notification arrives, so a burst of alerts cannot be cut off mid-read.
"""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from core import failsoft
from core.hologram_theme import ThemePalette, palette_for_mode
from core.system_status import Notification

__all__ = ["DynamicIsland", "ISLAND_STATES"]

#: States the pill can display. "error" and "disconnected" are deliberately
#: distinct from idle: a silent failure must not look like calm.
ISLAND_STATES = ("idle", "listening", "thinking", "speaking", "error", "disconnected", "privacy")


class DynamicIsland(QWidget):
    """Floating pill window. Owns its geometry, timers and painting only."""

    sig_restore_requested = pyqtSignal()
    sig_expanded_changed = pyqtSignal(bool)
    sig_activated = pyqtSignal(str)   # "restore" | "settings" | "task"

    COLLAPSED_SIZE = (208, 44)
    EXPANDED_SIZE = (344, 108)
    NOTIFICATION_SIZE = (344, 84)

    def __init__(self, parent: QWidget | None = None, palette: ThemePalette | None = None):
        super().__init__(parent)
        self.setObjectName("JarvisDynamicIsland")
        self._palette = palette or palette_for_mode("jarvis")
        self._state = "idle"
        self._energy = 0.0
        self._task_summary = ""
        self._battery_text = ""
        self._notification: Notification | None = None
        self._expanded = False
        self._phase = 0.0
        self._drag_offset: QPoint | None = None
        self._moved = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("JARVIS status island")
        self.setToolTip("JARVIS — click to restore the hologram window")
        self.resize(*self.COLLAPSED_SIZE)
        self._apply_window_flags()

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(60)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self._auto_collapse)

    # -- window setup -------------------------------------------------------
    def _apply_window_flags(self) -> None:
        """Best-effort frameless always-on-top; degrade rather than disappear."""
        try:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        except Exception:
            failsoft.suppress("ui.dynamic_island:window_flags")

    # -- state feed ---------------------------------------------------------
    def set_state(self, state: str) -> None:
        st = str(state or "idle").strip().lower()
        if st not in ISLAND_STATES:
            st = {"privacy_lock": "privacy", "lockdown": "privacy", "idle_quiet": "idle"}.get(st, "idle")
        if st != self._state:
            self._state = st
            self.update()

    @property
    def state(self) -> str:
        return self._state

    def accent_name(self) -> str:
        """Current accent as ``#rrggbb`` (state-aware, testable without painting)."""
        return self._accent().name()

    def set_energy(self, energy: float) -> None:
        try:
            self._energy = max(0.0, min(1.0, float(energy)))
        except (TypeError, ValueError):
            self._energy = 0.0

    def set_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def set_task_summary(self, text: str) -> None:
        """Live task text ("" hides the row). Never invent a percentage here."""
        self._task_summary = " ".join(str(text or "").split())[:52]
        if self._expanded:
            self.update()

    def set_battery_text(self, text: str) -> None:
        self._battery_text = str(text or "")[:24]
        self.update()

    def set_reduced_motion(self, enabled: bool) -> None:
        self._tick_timer.setInterval(140 if enabled else 60)
        self.update()

    # -- notifications ------------------------------------------------------
    def show_notification(self, note: Notification, auto_collapse_ms: int = 6500) -> None:
        """Show an alert in the pill; critical ones stay longer."""
        self._notification = note
        if note.is_critical:
            auto_collapse_ms = max(auto_collapse_ms, 9000)
        self._expanded = True
        self._resize_for_content()
        self.sig_expanded_changed.emit(True)
        self._collapse_timer.start(auto_collapse_ms)
        self.update()

    def clear_notification(self) -> None:
        self._notification = None
        self.collapse()

    # -- geometry -----------------------------------------------------------
    def _resize_for_content(self) -> None:
        if self._notification is not None:
            width, height = self.NOTIFICATION_SIZE
        elif self._expanded:
            width, height = self.EXPANDED_SIZE
        else:
            width, height = self.COLLAPSED_SIZE
        self.resize(width, height)
        self._keep_on_screen()

    def expand(self) -> None:
        if self._expanded:
            return
        self._expanded = True
        self._resize_for_content()
        self.sig_expanded_changed.emit(True)
        self.update()

    def collapse(self) -> None:
        self._collapse_timer.stop()
        was = self._expanded
        self._expanded = False
        self._notification = None
        self._resize_for_content()
        if was:
            self.sig_expanded_changed.emit(False)
        self.update()

    def _auto_collapse(self) -> None:
        try:
            self.collapse()
        except RuntimeError:
            failsoft.suppress("ui.dynamic_island:auto_collapse")

    def move_to_default_position(self) -> None:
        """Park the pill at the bottom-centre of the primary screen."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.center().x() - self.width() // 2,
            area.bottom() - self.height() - 24,
        )

    def _keep_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = min(max(self.x(), area.left() + 4), area.right() - self.width() - 4)
        y = min(max(self.y(), area.top() + 4), area.bottom() - self.height() - 4)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    # -- painting -----------------------------------------------------------
    def _accent(self) -> QColor:
        base = self._palette.accent
        if self._state == "error" or self._state == "disconnected":
            return QColor("#ff6b6b")
        if self._state == "privacy":
            return QColor("#ff456b")
        return QColor(*base)

    def _tick(self) -> None:
        try:
            self._phase = (self._phase + (2.4 + self._energy * 6.0)) % 360.0
            if self._state in ("thinking", "speaking", "listening") or self._notification is not None:
                self.update()
        except RuntimeError:
            failsoft.suppress("ui.dynamic_island:tick")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = rect.height() / 2.0 if not self._expanded else 22.0
        accent = self._accent()

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 170), 1.3))
        painter.setBrush(QColor(8, 11, 16, 238))
        painter.drawPath(path)

        # Live status dot: pulses only while there is state to show.
        pulse = 0.5 + 0.5 * math.sin(math.radians(self._phase))
        dot_r = 4.0 + (1.6 * pulse if self._state in ("listening", "speaking", "thinking") else 0.0)
        centre = QPointF(22.0, rect.center().y())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 70))
        painter.drawEllipse(centre, dot_r + 4, dot_r + 4)
        painter.setBrush(accent)
        painter.drawEllipse(centre, dot_r, dot_r)

        label = {
            "idle": "JARVIS",
            "listening": "LISTENING",
            "thinking": "THINKING",
            "speaking": "SPEAKING",
            "error": "ERROR",
            "disconnected": "OFFLINE",
            "privacy": "PRIVACY LOCK",
        }.get(self._state, "JARVIS")
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QPen(QColor("#f1ece3")))
        text_x = 38
        text_width = rect.width() - 90
        painter.drawText(
            QRectF(text_x, rect.top() + 8, text_width, 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )

        if self._battery_text:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(QColor(200, 200, 205, 210)))
            painter.drawText(
                QRectF(rect.right() - 60, rect.top() + 8, 50, 16),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                self._battery_text,
            )

        if self._notification is not None:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(QColor("#f5efe6")))
            painter.drawText(
                QRectF(text_x, rect.top() + 28, rect.width() - 46, 16),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self._notification.title[:44],
            )
            painter.setPen(QPen(QColor(205, 205, 210, 205)))
            painter.drawText(
                QRectF(text_x, rect.top() + 46, rect.width() - 46, 26),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                self._notification.body[:78],
            )
        elif self._expanded and self._task_summary:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(QColor(205, 205, 210, 210)))
            painter.drawText(
                QRectF(text_x, rect.top() + 27, rect.width() - 46, 15),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self._task_summary,
            )
            # Energy bar reflects real output energy only.
            bar = QRectF(rect.left() + 12, rect.bottom() - 16, rect.width() - 24, 3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 26))
            painter.drawRoundedRect(bar, 1.5, 1.5)
            painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 210))
            painter.drawRoundedRect(
                QRectF(bar.left(), bar.top(), bar.width() * max(0.02, min(1.0, self._energy)), bar.height()),
                1.5, 1.5,
            )

    # -- interaction --------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag_offset is None:
            return
        target = event.globalPosition().toPoint() - self._drag_offset
        if (target - self.pos()).manhattanLength() > 2:
            self._moved = True
        self.move(target)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag_offset is None:
            return
        was_drag = self._moved
        self._drag_offset = None
        if not was_drag:
            if self._notification is not None:
                self.clear_notification()
            elif self._expanded:
                self.collapse()
            else:
                self.sig_activated.emit("restore")
                self.sig_restore_requested.emit()
        else:
            self._keep_on_screen()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        self.sig_activated.emit("restore")
        self.sig_restore_requested.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.sig_activated.emit("restore")
            self.sig_restore_requested.emit()
            return
        if key == Qt.Key.Key_Escape:
            self.collapse()
            return
        if key == Qt.Key.Key_Up:
            self.expand()
            return
        if key == Qt.Key.Key_Down:
            self.collapse()
            return
        super().keyPressEvent(event)


class IslandIdleClock:
    """Tiny helper kept separate so tests can drive time without sleeping."""

    def __init__(self):
        self._started = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._started


__all__.append("IslandIdleClock")
