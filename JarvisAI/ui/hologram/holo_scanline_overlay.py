"""Subtle scanline overlay for the neural-wireframe hologram.

Attach this transparent child to a NeuralWireframeHead. It paints only a
soft, palette-aware scan band and does not modify the face mesh or app state.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget


class HologramScanlineOverlay(QWidget):
    """A low-cost scanline animation layered over an existing hologram head."""

    SWEEP_SECONDS = 3.6
    PAUSE_SECONDS = 1.6

    def __init__(self, host: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent if parent is not None else host)
        self._host = host
        self._enabled = True
        self._reduced_motion = False
        self._frame_interval = 33
        self._glow_scale = 1.0
        self._start_time = time.monotonic()
        self._static_phase = 0.18

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(0, 0, max(1, host.width()), max(1, host.height()))
        host.installEventFilter(self)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self.update)
        self._timer.start(self._frame_interval)

    def set_enabled_effect(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._sync_timer()
        self.update()

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        self._sync_timer()
        self.update()

    def set_performance_budget(
        self, frame_interval_ms: int, particle_scale: float, glow_scale: float
    ) -> None:
        del particle_scale  # The scanline has no particles.
        self._frame_interval = max(16, min(200, int(frame_interval_ms)))
        self._glow_scale = max(0.0, min(1.0, float(glow_scale)))
        if self._timer.isActive():
            self._timer.setInterval(self._frame_interval)
        self.update()

    def _sync_timer(self) -> None:
        if self._enabled and not self._reduced_motion:
            if not self._timer.isActive():
                self._timer.start(self._frame_interval)
        else:
            self._timer.stop()

    def eventFilter(self, obj, event):
        if obj is self._host and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
        ):
            self.setGeometry(
                0, 0, max(1, self._host.width()), max(1, self._host.height())
            )
        return False

    def _phase(self) -> float:
        if self._reduced_motion:
            return self._static_phase
        cycle = self.SWEEP_SECONDS + self.PAUSE_SECONDS
        elapsed = (time.monotonic() - self._start_time) % cycle
        return 1.0 if elapsed >= self.SWEEP_SECONDS else elapsed / self.SWEEP_SECONDS

    @staticmethod
    def _rgb(value) -> tuple[int, int, int]:
        """Validate palette RGB tuples before passing them to QColor."""
        if not isinstance(value, (tuple, list)) or len(value) < 3:
            return (255, 160, 90)
        return tuple(max(0, min(255, int(channel))) for channel in value[:3])

    def paintEvent(self, event) -> None:
        del event
        if not self._enabled or self._host is None:
            return

        try:
            face_rect = self._host.face_rect()
            palette = self._host.palette()
            primary_rgb = self._rgb(palette.primary)
            accent_rgb = self._rgb(palette.accent)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

        if face_rect is None or face_rect.width() <= 0 or face_rect.height() <= 0:
            return

        rect = QRectF(face_rect)
        phase = self._phase()
        edge_fade = 1.0
        if phase < 0.06:
            edge_fade = phase / 0.06
        elif phase > 0.94:
            edge_fade = (1.0 - phase) / 0.06
        edge_fade = max(0.0, min(1.0, edge_fade))

        band_y = rect.top() + rect.height() * phase
        band_half_height = rect.height() * 0.08
        primary = QColor(*primary_rgb)
        accent = QColor(*accent_rgb)

        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.save()

        clip_path = QPainterPath()
        clip_path.addEllipse(rect)
        painter.setClipPath(clip_path)

        wash_alpha = int(38 * self._glow_scale * edge_fade)
        if wash_alpha:
            gradient = QLinearGradient(
                0.0, band_y - band_half_height, 0.0, band_y + band_half_height
            )
            gradient.setColorAt(0.0, QColor(*primary_rgb, 0))
            gradient.setColorAt(0.5, QColor(*primary_rgb, wash_alpha))
            gradient.setColorAt(1.0, QColor(*primary_rgb, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRect(
                QRectF(
                    rect.left(),
                    band_y - band_half_height,
                    rect.width(),
                    band_half_height * 2,
                )
            )

        core_alpha = int(125 * edge_fade)
        if core_alpha:
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), core_alpha))
            pen.setWidthF(1.2)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(rect.left(), band_y), QPointF(rect.right(), band_y)
            )

        painter.restore()
        painter.end()
