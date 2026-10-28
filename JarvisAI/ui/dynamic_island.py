"""Compact floating status widget shown while JARVIS is minimised.

Minimising a 1280×800 HUD used to leave nothing but a taskbar entry, so a
running autonomous task could fail silently. This widget is the replacement: a
small, always-on-top pill in the style of a phone "dynamic island" that shows the
live state, expands to show progress and offers pause/stop, and reopens the full
HUD on click.

Platform behaviour that matters:

* It is a frameless ``Qt.Tool`` window, so it never creates a second taskbar
  entry and never takes focus (``WindowDoesNotAcceptFocus`` plus
  ``WA_ShowWithoutActivating``); typing in another app is not interrupted.
* It positions itself at the top-centre of the *current* screen and is clamped
  with :func:`agent.presentation.clamp_position`, so it cannot be dragged off a
  multi-monitor desktop.
* It polls the engine at 1 Hz only while visible and only reads a small
  snapshot; it owns no audio, no capture and no worker thread.

Every string/geometry decision lives in :mod:`agent.presentation`, which is
Qt-free and unit-tested on machines without a display.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QToolButton, QWidget

from agent.presentation import (
    IslandSummary,
    clamp_position,
    island_geometry,
    summarize_task,
)


class DynamicIsland(QWidget):
    """Frameless state pill with an expandable task view."""

    open_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, *, service: Any | None = None):
        super().__init__(parent)
        self._service = service
        self._summary = summarize_task(None)
        self._expanded = False
        self._task: Any | None = None

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("JARVIS status")
        self.setFixedSize(*island_geometry(False))

        self._pause_button = self._make_button("⏸", "Pause the task", self.pause_requested)
        self._stop_button = self._make_button("■", "Stop the task", self.stop_requested)
        self._open_button = self._make_button("↗", "Open JARVIS", self.open_requested)
        self._position_buttons()
        self._set_buttons_visible(False)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

    # ── construction helpers ─────────────────────────────────────────────
    def _make_button(self, glyph: str, tooltip: str, signal) -> QToolButton:
        button = QToolButton(self)
        button.setText(glyph)
        button.setToolTip(tooltip)
        button.setFixedSize(24, 24)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            "QToolButton { color: #d7f4ff; background: rgba(12, 30, 40, 200); "
            "border: 1px solid rgba(104, 217, 255, 0.35); border-radius: 12px; "
            "font: 700 10pt 'Consolas'; }"
            "QToolButton:hover { color: #ffffff; border-color: #80e7ff; }"
        )
        button.clicked.connect(signal.emit)
        return button

    def _position_buttons(self) -> None:
        width, height = self.size().width(), self.size().height()
        self._open_button.move(width - 30, (height - 24) // 2)
        self._pause_button.move(width - 60, (height - 24) // 2)
        self._stop_button.move(width - 90, (height - 24) // 2)

    def _set_buttons_visible(self, visible: bool) -> None:
        for button in (self._open_button, self._pause_button, self._stop_button):
            button.setVisible(visible)
        self._pause_button.setVisible(visible and self._summary.is_active)
        self._stop_button.setVisible(visible and self._summary.is_active)

    # ── state ────────────────────────────────────────────────────────────
    def set_summary(self, summary: IslandSummary) -> None:
        self._summary = summary
        self._set_buttons_visible(self._expanded)
        self.update()

    def summary(self) -> IslandSummary:
        return self._summary

    def expand(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        width, height = island_geometry(expanded)
        self.setFixedSize(width, height)
        self._position_buttons()
        self._set_buttons_visible(expanded)
        self.reposition()
        self.update()

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

    # ── window behaviour ─────────────────────────────────────────────────
    def reposition(self) -> None:
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
        x, y = clamp_position(x, y, self.width(), self.height(),
                              available.x() + available.width(),
                              available.y() + available.height(), margin=8)
        self.move(QPoint(x, y))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self.reposition()
        self._timer.start()
        self.refresh()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().y() < 30 and not self._expanded:
                self.expand(True)
            else:
                self.open_requested.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.open_requested.emit()
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width, height = self.width(), self.height()
        radius = height / 2 if not self._expanded else 18.0
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), radius, radius)

        painter.fillPath(path, QColor(8, 14, 20, 244))
        tone = QColor(self._summary.tone)
        pen = QPen(tone, 1.2)
        painter.setPen(pen)
        painter.drawPath(path)

        # State dot.
        dot = QColor(tone)
        dot.setAlpha(230)
        painter.setBrush(dot)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(13, height / 2 - 4, 8, 8))

        painter.setPen(QPen(QColor("#dff6ff")))
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(28, 6, width - 120, 16),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         self._summary.title)
        painter.setPen(QPen(QColor("#8fb8c6")))
        painter.setFont(QFont("Aptos", 8))
        detail_rect = QRectF(28, height - 22, width - 40, 16) if self._expanded \
            else QRectF(28, 22, width - 40, 16)
        painter.drawText(detail_rect,
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         self._summary.detail)

        if self._expanded:
            bar = QRectF(28, height - 16, width - 46, 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 26))
            painter.drawRoundedRect(bar, 2, 2)
            filled = QRectF(bar)
            filled.setWidth(max(0.0, bar.width() * float(self._summary.progress)))
            painter.setBrush(tone)
            painter.drawRoundedRect(filled, 2, 2)
        painter.end()


class DynamicIslandController(QObject):
    """Creates the island on first minimise and keeps it in sync."""

    def __init__(self, window: QWidget, *, service: Any | None = None):
        super().__init__(window)
        self._window = window
        self._service = service
        self._island: DynamicIsland | None = None

    @property
    def island(self) -> DynamicIsland | None:
        return self._island

    def ensure_island(self) -> DynamicIsland:
        if self._island is None:
            self._island = DynamicIsland(service=self._service)
            self._island.open_requested.connect(self.restore_window)
            self._island.pause_requested.connect(self._pause)
            self._island.stop_requested.connect(self._stop)
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
                pass
        island.refresh()
        island.show()
        island.raise_()

    def restore_window(self) -> None:
        try:
            self._window.showNormal()
            self._window.raise_()
            self._window.activateWindow()
        except Exception:
            pass
        if self._island is not None:
            self._island.hide()

    def _pause(self) -> None:
        try:
            self.ensure_island().service().pause()
        except Exception:
            pass
        if self._island is not None:
            QTimer.singleShot(150, self._island.refresh)

    def _stop(self) -> None:
        try:
            self.ensure_island().service().stop("Stopped from the status widget.")
        except Exception:
            pass
        if self._island is not None:
            QTimer.singleShot(150, self._island.refresh)

    def shutdown(self) -> None:
        if self._island is not None:
            self._island.hide()
            self._island.deleteLater()
            self._island = None
