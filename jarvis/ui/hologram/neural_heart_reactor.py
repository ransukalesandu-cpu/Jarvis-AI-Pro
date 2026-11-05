"""Subtle breathing neural-heart / quantum-reactor overlay for the central HUD.

Independent transparent paint layer; NeuralWireframeHead and status orb renderers
remain unchanged. The heart continuously cycles through red, pink and orange.
"""
from __future__ import annotations

import math
import time

from PyQt6.QtCore import Qt, QEvent, QTimer, QPointF
from PyQt6.QtGui import QColor, QBrush, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget


class NeuralHeartReactor(QWidget):
    """Small heart-shaped neural mesh with subtle head/orb conduits and aura."""

    def __init__(self, stage: QWidget, parent=None):
        super().__init__(stage)
        self._stage = stage
        self._state = "IDLE"
        self._audio_energy = 0.0
        self._started_at = time.monotonic()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setObjectName("NeuralHeartReactor")
        self.setGeometry(stage.rect())
        stage.installEventFilter(self)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(33)

    def eventFilter(self, watched, event):
        if watched is self._stage and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._stage.rect())
            self.raise_()
        return super().eventFilter(watched, event)

    def set_state(self, state: str):
        self._state = str(state or "IDLE").upper()
        self.update()

    def set_audio_energy(self, level: float) -> None:
        """Drive the reactor pulse from normalized live audio energy."""
        try:
            value = float(level)
        except (TypeError, ValueError):
            value = 0.0
        if not math.isfinite(value):
            value = 0.0
        self._audio_energy = max(0.0, min(1.0, value))
        self.update()

    @staticmethod
    def _cycle_color(elapsed: float) -> QColor:
        """Smoothly loop only through red -> pink -> orange -> red."""
        palette = ((255, 48, 68), (255, 65, 160), (255, 139, 35))
        phase = (elapsed / 3.2) % len(palette)
        index = int(phase)
        blend = phase - index
        start, end = palette[index], palette[(index + 1) % len(palette)]
        return QColor(*(round(a + (b - a) * blend) for a, b in zip(start, end)))

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w < 80 or h < 120:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = time.monotonic() - self._started_at
        pulse_rate = 0.42 + self._audio_energy * 0.48
        pulse = (math.sin(t * 2.0 * math.pi * pulse_rate) + 1.0) * 0.5
        breath = 1.0 + (0.055 + self._audio_energy * 0.035) * math.sin(t * 2.0 * math.pi * pulse_rate)
        c = self._cycle_color(t)
        # Audio and state gently intensify the reactor without changing its palette.
        state_boost = 1.0 + self._audio_energy * 0.35
        if self._state in ("SPEAKING", "THINKING"):
            state_boost *= 1.12
        elif self._state in ("PRIVACY_LOCK", "ERROR", "DISCONNECTED"):
            state_boost *= 0.72

        # Small heart (about 40px) on the hologram's left side; smaller than orb.
        cx, cy = max(31.0, min(47.0, w * 0.085)), h * 0.37
        hw, hh = 28.0 * breath, 31.0 * breath

        aura = QRadialGradient(QPointF(cx, cy), 42.0 * breath)
        aura_center = QColor(c)
        aura_center.setAlpha(min(255, int((28 + 18 * pulse) * state_boost)))
        aura.setColorAt(0.0, aura_center)
        aura.setColorAt(0.55, QColor(c.red(), c.green(), c.blue(), 9))
        aura.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(aura))
        p.drawEllipse(QPointF(cx, cy), 42.0 * breath, 42.0 * breath)

        # Only a few dim neural wires, so the hologram remains visually dominant.
        p.setBrush(Qt.BrushStyle.NoBrush)
        wire = QPen(QColor(c.red(), c.green(), c.blue(), int((58 + 28 * pulse) * state_boost)), 0.8)
        wire.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(wire)
        head_anchor = QPointF(w * 0.30, h * 0.30)
        heart_anchor = QPointF(cx + hw * 0.60, cy - hh * 0.05)
        link = QPainterPath(heart_anchor)
        link.cubicTo(QPointF(cx + 38, cy - 24), QPointF(w * 0.18, h * 0.23), head_anchor)
        p.drawPath(link)

        # Two delicate strands flow from the heart down to the status orb.
        orb_anchor = QPointF(w * 0.50, h - 24.0)
        for offset in (-3.0, 3.0):
            strand = QPainterPath(QPointF(cx + offset, cy + hh * 0.63))
            strand.cubicTo(
                QPointF(cx + 16 + offset, cy + 42),
                QPointF(w * 0.20 + offset, h * 0.72),
                QPointF(orb_anchor.x() + offset * 0.35, orb_anchor.y() - 5),
            )
            p.drawPath(strand)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(c.red(), c.green(), c.blue(), int((90 + 50 * pulse) * state_boost))))
        p.drawEllipse(head_anchor, 1.7, 1.7)
        p.drawEllipse(orb_anchor, 2.0, 2.0)

        # Quantum-reactor heart shell.
        left, top = cx - hw / 2.0, cy - hh / 2.0
        heart = QPainterPath()
        heart.moveTo(cx, top + hh * 0.27)
        heart.cubicTo(cx - hw * 0.10, top - hh * 0.02,
                      left - hw * 0.10, top + hh * 0.08, left, top + hh * 0.36)
        heart.cubicTo(left + hw * 0.06, top + hh * 0.61,
                      cx - hw * 0.12, top + hh * 0.82, cx, top + hh)
        heart.cubicTo(cx + hw * 0.12, top + hh * 0.82,
                      left + hw * 1.06, top + hh * 0.61, left + hw, top + hh * 0.36)
        heart.cubicTo(left + hw * 1.10, top + hh * 0.08,
                      cx + hw * 0.10, top - hh * 0.02, cx, top + hh * 0.27)
        heart.closeSubpath()
        p.setBrush(QBrush(QColor(c.red(), c.green(), c.blue(), int((20 + 12 * pulse) * state_boost))))
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), min(255, int((175 + 55 * pulse) * state_boost))), 1.05))
        p.drawPath(heart)

        # Sparse internal mesh.
        points = [
            QPointF(cx, top + hh * 0.27),
            QPointF(cx - hw * 0.29, top + hh * 0.38),
            QPointF(cx + hw * 0.29, top + hh * 0.38),
            QPointF(cx - hw * 0.18, top + hh * 0.62),
            QPointF(cx + hw * 0.18, top + hh * 0.62),
            QPointF(cx, top + hh * 0.84),
        ]
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), min(255, int(150 * state_boost))), 0.75))
        for a, b in ((0, 1), (0, 2), (1, 2), (1, 3), (1, 4),
                     (2, 3), (2, 4), (3, 4), (3, 5), (4, 5)):
            p.drawLine(points[a], points[b])

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 225, 235, min(255, 190 + int(45 * pulse)))))
        core = 2.2 + 0.65 * pulse
        p.drawEllipse(QPointF(cx, cy + 1.0), core, core)
        p.end()
