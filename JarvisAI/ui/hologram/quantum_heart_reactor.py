"""Quantum heart reactor for JARVIS AI Pro.

A small glowing reactor core rendered beside the holographic orb. It has no
functional role beyond ambience: a soft "lub-dub" heartbeat pulse that
quickens with audio energy, so the hologram group reads as alive rather than
purely decorative. Colours come from ``core.hologram_theme`` so it shares
identity with the rest of the hologram.

Standalone widget: usable on its own, or as part of ``hologram_panel.py``.
"""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from core.hologram_theme import JARVIS_PALETTE, ThemePalette


class QuantumHeartReactor(QWidget):
    """Small pulsing reactor core, wired to the holographic orb."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(40, 40)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self._palette: ThemePalette = JARVIS_PALETTE
        self._state = "IDLE"
        self._pulse_energy = 0.0
        self._target_energy = 0.0
        self._reduced_motion = False
        self._glow_scale = 1.0
        self._frame_interval = 33
        self._start_time = time.time()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(self._frame_interval)

    # ── public API ──────────────────────────────────────────────────────────
    @pyqtSlot(float)
    def set_pulse_energy(self, level: float) -> None:
        try:
            self._target_energy = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            self._target_energy = 0.0

    @pyqtSlot(str)
    def set_state(self, state: str) -> None:
        st = str(state or "IDLE").upper()
        if st == "LOCKDOWN":
            st = "PRIVACY_LOCK"
        self._state = st

    def get_state(self) -> str:
        return self._state

    def set_palette(self, palette: ThemePalette) -> None:
        if palette is None or palette == self._palette:
            return
        self._palette = palette
        self.update()

    def palette(self) -> ThemePalette:
        return self._palette

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)

    def set_performance_budget(self, frame_interval_ms: int, particle_scale: float, glow_scale: float) -> None:
        interval = max(16, min(200, int(frame_interval_ms)))
        if interval != self._frame_interval:
            self._frame_interval = interval
            self._timer.setInterval(interval)
        self._glow_scale = max(0.2, min(1.0, float(glow_scale)))

    def anchor_point(self) -> QPointF:
        """Left-hand connection point, wired to the orb beside it."""
        return QPointF(self.width() * 0.12, self.height() * 0.52)

    # ── animation ───────────────────────────────────────────────────────────
    def _step(self):
        self._pulse_energy += (self._target_energy - self._pulse_energy) * 0.2
        self.update()

    # ── painting ────────────────────────────────────────────────────────────
    @staticmethod
    def _heart_path(cx: float, cy: float, size: float) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(cx, cy + size * 0.32)
        path.cubicTo(cx - size * 1.1, cy - size * 0.55,
                     cx - size * 0.45, cy - size * 1.15,
                     cx, cy - size * 0.42)
        path.cubicTo(cx + size * 0.45, cy - size * 1.15,
                     cx + size * 1.1, cy - size * 0.55,
                     cx, cy + size * 0.32)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        base = min(w, h) * 0.28
        t = time.time() - self._start_time
        palette = self._palette
        accent = QColor(*palette.accent)
        secondary = QColor(*palette.secondary)

        # A soft double-beat ("lub-dub") drives the pulse instead of a plain
        # sine, which is what makes it read as a heartbeat rather than a buoy.
        phase = (t * (1.1 + self._pulse_energy * 1.6)) % 1.0 if not self._reduced_motion else 0.0
        beat = 0.0
        for centre, weight in ((0.08, 1.0), (0.26, 0.55)):
            beat += weight * math.exp(-((phase - centre) ** 2) / (2 * 0.022 ** 2))
        size = base * (1.0 + 0.18 * beat + 0.10 * self._pulse_energy)

        colour = QColor("#ff1744") if self._state == "PRIVACY_LOCK" else accent

        glow = QRadialGradient(QPointF(cx, cy), size * 2.4)
        alpha = int((90 + 90 * beat) * self._glow_scale)
        glow.setColorAt(0.0, QColor(colour.red(), colour.green(), colour.blue(), alpha))
        glow.setColorAt(0.6, QColor(colour.red(), colour.green(), colour.blue(), alpha // 3))
        glow.setColorAt(1.0, QColor(colour.red(), colour.green(), colour.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), size * 2.4, size * 2.4)

        heart = self._heart_path(cx, cy, size)
        body = QRadialGradient(QPointF(cx, cy - size * 0.2), size * 1.3)
        body.setColorAt(0.0, QColor(255, 245, 235, 235))
        body.setColorAt(0.45, QColor(colour.red(), colour.green(), colour.blue(), 220))
        body.setColorAt(1.0, QColor(colour.red(), colour.green(), colour.blue(), 90))
        painter.setBrush(body)
        painter.setPen(QPen(QColor(secondary.red(), secondary.green(), secondary.blue(), 200), 1.2))
        painter.drawPath(heart)

        painter.end()
