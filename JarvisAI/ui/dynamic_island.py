"""Pill-shaped floating "Dynamic Island" shown while JARVIS is minimised.

Why this exists
---------------
Minimising the HUD used to leave an ordinary square window (or a taskbar entry
that told the user nothing). The island is a frameless, always-on-top pill that
keeps the assistant *and its live state* visible while the big hologram is
away:

* it mirrors the real visual state (idle / listening / thinking / speaking /
  error) fed from the same bridge as the HUD;
* it shows the live hologram task summary and battery truthfully, or nothing at
  all when that information is unavailable;
* it shows a running autonomous task — progress, pause, stop, open — summarised
  by :mod:`agent.presentation`, so a long task cannot fail silently;
* clicking it restores the HUD, dragging moves it, Escape collapses it, and it
  is keyboard reachable (it is focusable and accepts Space/Enter/Escape).

Hard rules baked in
-------------------
* The island is a *view*. It never stops the microphone, playback or tasks; the
  only thing it "does" is ask its owner (via a signal) to pause or stop an
  autonomous task, which the controller forwards to the agent service.
* Window flags are applied defensively: ``WindowStaysOnTopHint`` and
  ``FramelessWindowHint`` behave differently per compositor, so a platform that
  rejects translucent windows still gets a working pill.
* Auto-collapse runs on a QTimer owned by the widget and is cancelled whenever a
  new notification arrives, so a burst of alerts cannot be cut off mid-read.
* Agent polling happens at 1 Hz and only while the pill is visible; it reads one
  small snapshot and owns no capture or worker thread.
"""

from __future__ import annotations

import math
import time
from typing import Any

from PyQt6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QToolButton, QWidget

from agent.presentation import (
    IslandSummary,
    clamp_position,
    island_geometry,
    summarize_task,
)

from core import failsoft
from core.hologram_theme import ThemePalette, palette_for_mode
from core.system_status import Notification

__all__ = ["DynamicIsland", "DynamicIslandController", "ISLAND_STATES", "IslandIdleClock"]

#: States the pill can display. "error" and "disconnected" are deliberately
#: distinct from idle: a silent failure must not look like calm.
ISLAND_STATES = ("idle", "listening", "thinking", "speaking", "error", "disconnected", "privacy")

#: Human labels for those states.
_STATE_LABELS = {
    "idle": "JARVIS",
    "listening": "LISTENING",
    "thinking": "THINKING",
    "speaking": "SPEAKING",
    "error": "ERROR",
    "disconnected": "OFFLINE",
    "privacy": "PRIVACY LOCK",
}


class DynamicIsland(QWidget):
    """Floating pill window. Owns its geometry, timers and painting only."""

    # Hologram/HUD side: restore requests, expansion, and "what was activated".
    sig_restore_requested = pyqtSignal()
    sig_expanded_changed = pyqtSignal(bool)
    sig_activated = pyqtSignal(str)   # "restore" | "settings" | "task"
    # Autonomous-task side: forwarded to the agent service by the controller.
    open_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    # Geometry comes from the Qt-free agent.presentation helpers so both the
    # pill and its tests agree with the panel sizing in one place.
    COLLAPSED_SIZE = island_geometry(False)      # (228, 46)
    EXPANDED_SIZE = island_geometry(True)        # (340, 148)
    NOTIFICATION_SIZE = (340, 96)

    def __init__(self, parent: QWidget | None = None, *, palette: ThemePalette | None = None,
                 service: Any | None = None):
        super().__init__(parent)
        self.setObjectName("JarvisDynamicIsland")
        self._palette = palette or palette_for_mode("jarvis")
        self._service = service
        self._task: Any | None = None
        self._summary = summarize_task(None)
        self._has_agent_task = False
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
        self.setWindowTitle("JARVIS status")
        self.setToolTip("JARVIS — click to restore the hologram window")
        self.setFixedSize(*self.COLLAPSED_SIZE)
        self._apply_window_flags()

        # Task controls. They exist only while the pill is expanded and there is
        # a live autonomous task to control.
        self._open_button = self._make_button("↗", "Open JARVIS", self.open_requested)
        self._pause_button = self._make_button("⏸", "Pause the task", self.pause_requested)
        self._stop_button = self._make_button("■", "Stop the task", self.stop_requested)
        self._position_buttons()
        self._set_buttons_visible(False)

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(60)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self._auto_collapse)

        # Agent refresh: 1 Hz, and only while visible (see show/hideEvent).
        self._agent_timer = QTimer(self)
        self._agent_timer.setInterval(1000)
        self._agent_timer.timeout.connect(self.refresh)

    # -- window setup -------------------------------------------------------
    def _apply_window_flags(self) -> None:
        """Best-effort frameless always-on-top; degrade rather than disappear."""
        try:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        except Exception:
            failsoft.suppress("ui.dynamic_island:window_flags")

    def _make_button(self, glyph: str, tooltip: str, signal) -> QToolButton:
        button = QToolButton(self)
        button.setText(glyph)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedSize(24, 24)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(signal.emit)
        button.hide()
        return button

    def _position_buttons(self) -> None:
        width, height = self.size().width(), self.size().height()
        self._open_button.move(width - 30, (height - 24) // 2)
        self._pause_button.move(width - 60, (height - 24) // 2)
        self._stop_button.move(width - 90, (height - 24) // 2)

    def _set_buttons_visible(self, visible: bool) -> None:
        accent = self._accent().name()
        for button in (self._open_button, self._pause_button, self._stop_button):
            button.setStyleSheet(
                "QToolButton { color: %s; background: rgba(12, 30, 40, 200);"
                " border: 1px solid rgba(255, 255, 255, 40); border-radius: 12px;"
                " font: 700 10pt 'Consolas'; }"
                "QToolButton:hover { color: #ffffff; border-color: %s; }" % (accent, accent)
            )
        self._open_button.setVisible(visible)
        self._pause_button.setVisible(visible and self._summary.is_active)
        self._stop_button.setVisible(visible and self._summary.is_active)

    # -- hologram state feed ------------------------------------------------
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
        self._set_buttons_visible(self._expanded)
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

    # -- autonomous-task feed ----------------------------------------------
    def set_summary(self, summary: IslandSummary) -> None:
        self._summary = summary
        self._has_agent_task = bool(getattr(summary, "expandable", False)) or (
            getattr(summary, "state", None) is not None and not summary.is_active
        )
        self._set_buttons_visible(self._expanded)
        self.update()

    def summary(self) -> IslandSummary:
        return self._summary

    @property
    def expanded(self) -> bool:
        return self._expanded

    def attach_service(self, service: Any | None) -> None:
        self._service = service
        self.refresh()

    def service(self) -> Any | None:
        if self._service is None:
            try:
                from agent.integration import get_service

                self._service = get_service()
            except Exception:
                self._service = None
        return self._service

    def refresh(self) -> None:
        """Read one small snapshot from the agent service; never blocks on work."""
        service = self.service()
        if service is None:
            return
        try:
            self._task = service.runner.active_task or self._latest(service)
        except Exception:
            self._task = None
        self.set_summary(summarize_task(self._task))

    @staticmethod
    def _latest(service: Any) -> Any | None:
        try:
            snapshot = service.status().get("task")
            if not snapshot:
                return None
            from agent.models import Task

            return Task.from_dict(snapshot)
        except Exception:
            return None

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
        self.setFixedSize(width, height)
        self._position_buttons()
        self._keep_on_screen()

    def expand(self, expanded: bool = True) -> None:
        """Expand (or collapse) the pill. Accepts the historical bool argument."""
        if expanded == self._expanded:
            self._set_buttons_visible(expanded)
            return
        self._expanded = bool(expanded)
        self._resize_for_content()
        self._set_buttons_visible(self._expanded)
        self.sig_expanded_changed.emit(self._expanded)
        self.update()

    def collapse(self) -> None:
        self._collapse_timer.stop()
        self._notification = None
        self.expand(False)

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

    def reposition(self) -> None:
        """Park the pill at the top-centre of the window's screen, clamped inside it."""
        screen = None
        try:
            parent = self.parentWidget()
            if parent is not None and parent.window().screen() is not None:
                screen = parent.window().screen()
        except Exception:
            screen = None
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        x = available.x() + (available.width() - self.width()) // 2
        y = available.y() + 8
        x, y = clamp_position(
            x, y, self.width(), self.height(),
            available.x() + available.width(),
            available.y() + available.height(),
            margin=8,
        )
        self.move(QPoint(x, y))

    def _keep_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x, y = clamp_position(
            self.x(), self.y(), self.width(), self.height(),
            area.x() + area.width(), area.y() + area.height(), margin=4,
        )
        if (x, y) != (self.x(), self.y()):
            self.move(QPoint(x, y))

    # -- lifecycle ----------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self.reposition()
        self._tick_timer.start()
        self._agent_timer.start()
        self.refresh()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._tick_timer.stop()
        self._agent_timer.stop()
        super().hideEvent(event)

    # -- painting -----------------------------------------------------------
    def _accent(self) -> QColor:
        if self._state in ("error", "disconnected"):
            return QColor("#ff6b6b")
        if self._state == "privacy":
            return QColor("#ff456b")
        return QColor(*self._palette.accent)

    def _tone(self) -> QColor:
        """Agent tone wins when a real task is being reported; else the state accent."""
        if self._has_agent_task:
            try:
                return QColor(self._summary.tone)
            except (TypeError, ValueError):
                pass
        return self._accent()

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
        radius = rect.height() / 2.0 if not self._expanded else 20.0
        accent = self._tone()

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

        # When the task controls are showing, the text stops before them.
        controls = 96.0 if self._expanded else 62.0
        text_x = 38.0
        text_width = max(40.0, rect.width() - text_x - controls)
        title = self._summary.title if self._has_agent_task else _STATE_LABELS.get(self._state, "JARVIS")
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QPen(QColor("#f1ece3")))
        painter.drawText(
            QRectF(text_x, rect.top() + 7, text_width, 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            str(title)[:42],
        )

        if self._battery_text:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(QColor(200, 200, 205, 210)))
            painter.drawText(
                QRectF(rect.right() - 62, rect.top() + 7, 52, 16),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                self._battery_text,
            )

        if self._notification is not None:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(QColor("#f5efe6")))
            painter.drawText(
                QRectF(text_x, rect.top() + 28, rect.width() - 48, 16),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self._notification.title[:44],
            )
            painter.setPen(QPen(QColor(205, 205, 210, 205)))
            painter.drawText(
                QRectF(text_x, rect.top() + 46, rect.width() - 48, 26),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                self._notification.body[:78],
            )
        elif self._expanded:
            detail = ""
            if self._has_agent_task:
                detail = str(self._summary.detail or "")
            elif self._task_summary:
                detail = self._task_summary
            if detail:
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(QPen(QColor(205, 205, 210, 210)))
                painter.drawText(
                    QRectF(text_x, rect.top() + 27, rect.width() - 48, 15),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    detail[:64],
                )
            # A progress bar only when there is a real fraction to draw.
            if self._has_agent_task:
                progress = max(0.0, min(1.0, float(self._summary.progress)))
                if progress:
                    bar = QRectF(rect.left() + 14, rect.bottom() - 14, rect.width() - 28, 3)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(255, 255, 255, 26))
                    painter.drawRoundedRect(bar, 1.5, 1.5)
                    painter.setBrush(accent)
                    painter.drawRoundedRect(
                        QRectF(bar.left(), bar.top(), bar.width() * progress, bar.height()), 1.5, 1.5
                    )
            elif self._task_summary:
                # Energy bar reflects real output energy only.
                bar = QRectF(rect.left() + 14, rect.bottom() - 14, rect.width() - 28, 3)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 26))
                painter.drawRoundedRect(bar, 1.5, 1.5)
                painter.setBrush(accent)
                painter.drawRoundedRect(
                    QRectF(bar.left(), bar.top(),
                           bar.width() * max(0.02, min(1.0, self._energy)), bar.height()),
                    1.5, 1.5,
                )
        painter.end()

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
                self.open_requested.emit()
        else:
            self._keep_on_screen()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        self.sig_activated.emit("restore")
        self.sig_restore_requested.emit()
        self.open_requested.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.sig_activated.emit("restore")
            self.sig_restore_requested.emit()
            self.open_requested.emit()
            return
        if key == Qt.Key.Key_Escape:
            self.collapse()
            return
        if key == Qt.Key.Key_Up:
            self.expand(True)
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
        return max(0.0, time.monotonic() - self._started)


class DynamicIslandController(QObject):
    """Creates (or adopts) the island and keeps it in sync with the HUD.

    ``island`` may be injected: the HUD owns one pill per process and hands it
    here, so battery/state feeds and the autonomous-task summary land on the
    same widget instead of two floating windows.
    """

    def __init__(self, window: QWidget, *, service: Any | None = None,
                 island: DynamicIsland | None = None):
        super().__init__(window)
        self._window = window
        self._service = service
        self._island: DynamicIsland | None = island
        if self._island is not None:
            self._connect()

    @property
    def island(self) -> DynamicIsland | None:
        return self._island

    def _connect(self) -> None:
        island = self._island
        if island is None:
            return
        for signal, slot in (
            (island.open_requested, self.restore_window),
            (island.pause_requested, self._pause),
            (island.stop_requested, self._stop),
        ):
            try:
                signal.connect(slot)
            except TypeError:
                # Already wired (the pill is shared and outlives one window).
                pass

    def ensure_island(self) -> DynamicIsland:
        if self._island is None:
            self._island = DynamicIsland(service=self._service)
            self._connect()
        return self._island

    def sync(self, minimized: bool) -> None:
        """Show the island when the HUD is minimised, hide it otherwise."""
        if not minimized:
            if self._island is not None and self._island.isVisible():
                self._island.hide()
            return
        island = self.ensure_island()
        if self._service is None:
            try:
                from agent.integration import get_service

                self._service = get_service()
                island.attach_service(self._service)
            except Exception:
                failsoft.suppress("ui.dynamic_island:sync")
        island.refresh()
        island.show()
        island.raise_()

    def restore_window(self) -> None:
        try:
            self._window.showNormal()
            self._window.raise_()
            self._window.activateWindow()
        except Exception:
            failsoft.suppress("ui.dynamic_island:restore_window")
        if self._island is not None:
            self._island.hide()

    def _pause(self) -> None:
        try:
            self.ensure_island().service().pause()
        except Exception:
            failsoft.suppress("ui.dynamic_island:_pause")
        if self._island is not None:
            QTimer.singleShot(150, self._island.refresh)

    def _stop(self) -> None:
        try:
            self.ensure_island().service().stop("Stopped from the status widget.")
        except Exception:
            failsoft.suppress("ui.dynamic_island:_stop")
        if self._island is not None:
            QTimer.singleShot(150, self._island.refresh)

    def shutdown(self) -> None:
        """Hide the pill. A shared pill is not deleted — the HUD may reuse it."""
        if self._island is not None:
            self._island.hide()
