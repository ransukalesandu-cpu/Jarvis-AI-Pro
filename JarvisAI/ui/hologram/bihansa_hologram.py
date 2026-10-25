"""Bihansa Mode's standalone rose-pink hologram widget.

This is intentionally isolated from the existing JARVIS hologram and audio
pipeline. It renders a generic head-and-hair silhouette until a user-provided
reference asset is available.
"""
from __future__ import annotations

import math
import random
import time
from typing import List, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QBrush, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget


class BihansaHologram(QWidget):
    """Animated pink neural hologram with a small, explicit state API."""

    sig_state_changed = pyqtSignal(str)

    COLOR_BG = QColor("#07040a")
    COLOR_PRIMARY = QColor("#ff72c6")
    COLOR_SECONDARY = QColor("#ffb3e2")
    COLOR_GLOW = QColor("#ff3eae")

    VALID_STATES = {"IDLE", "LISTENING", "THINKING", "SPEAKING", "MUTED", "ERROR"}

    def __init__(self, parent=None, *, reduced_motion: bool = False):
        super().__init__(parent)
        self.setMinimumSize(280, 320)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._state = "IDLE"
        self._audio_energy = 0.0
        self._target_energy = 0.0
        self._reduced_motion = bool(reduced_motion)
        self._glow_intensity = 1.0
        self._animation_speed = 1.0
        self._started_at = time.monotonic()
        self._phase = 0.0
        self._rng = random.Random(4217)
        self._particles = [
            {
                "angle": self._rng.uniform(0, math.tau),
                "radius": self._rng.uniform(0.72, 1.12),
                "speed": self._rng.uniform(0.15, 0.45),
                "size": self._rng.uniform(1.0, 2.7),
            }
            for _ in range(42)
        ]
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @pyqtSlot(str)
    def set_state(self, state: str) -> None:
        """Set IDLE, LISTENING, THINKING, SPEAKING, MUTED, or ERROR."""
        normalized = str(state or "IDLE").strip().upper()
        if normalized not in self.VALID_STATES:
            normalized = "IDLE"
        if normalized != self._state:
            self._state = normalized
            self.sig_state_changed.emit(normalized)
            self.update()

    def get_state(self) -> str:
        return self._state

    @pyqtSlot(float)
    def set_audio_energy(self, level: float) -> None:
        """Set a normalized audio activity value between 0 and 1."""
        try:
            self._target_energy = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            self._target_energy = 0.0

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        self.update()

    def set_glow_intensity(self, intensity: float) -> None:
        self._glow_intensity = max(0.0, min(1.5, float(intensity)))
        self.update()

    def set_animation_speed(self, speed: float) -> None:
        self._animation_speed = max(0.0, min(2.0, float(speed)))

    def _tick(self) -> None:
        self._audio_energy += (self._target_energy - self._audio_energy) * 0.22
        if not self._reduced_motion:
            dt = 0.033 * self._animation_speed
            self._phase += dt
            for particle in self._particles:
                particle["angle"] += particle["speed"] * dt
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), self.COLOR_BG)

        w, h = float(self.width()), float(self.height())
        cx, cy = w * 0.5, h * 0.48
        unit = min(w * 0.42, h * 0.34)
        pulse = 1.0 if self._reduced_motion else 1.0 + 0.018 * math.sin(self._phase * 2.0)
        pulse += self._audio_energy * (0.055 if self._state in {"LISTENING", "SPEAKING"} else 0.0)
        unit *= pulse

        # Soft aura: multiple translucent ellipses avoid extra graphics dependencies.
        painter.setPen(Qt.PenStyle.NoPen)
        for idx, alpha in enumerate((8, 12, 17, 22)):
            radius = unit * (1.30 + idx * 0.12) * self._glow_intensity
            painter.setBrush(QBrush(QColor(255, 62, 174, alpha)))
            painter.drawEllipse(QPointF(cx, cy), radius, radius * 1.12)

        # Floating particles around the head.
        for particle in self._particles:
            angle = particle["angle"]
            radius = unit * particle["radius"]
            px = cx + math.cos(angle) * radius
            py = cy + math.sin(angle) * radius * 1.22
            alpha = 105 if self._state not in {"THINKING", "SPEAKING"} else 210
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 179, 226, alpha))
            painter.drawEllipse(QPointF(px, py), particle["size"], particle["size"])

        # Generic hair silhouette. Replaceable independently when reference art arrives.
        hair = QPainterPath()
        hair.moveTo(cx - unit * 0.70, cy - unit * 0.18)
        hair.cubicTo(cx - unit * 0.88, cy - unit * 1.05,
                     cx - unit * 0.28, cy - unit * 1.23,
                     cx + unit * 0.02, cy - unit * 1.08)
        hair.cubicTo(cx + unit * 0.52, cy - unit * 1.22,
                     cx + unit * 0.89, cy - unit * 0.70,
                     cx + unit * 0.72, cy - unit * 0.05)
        hair.cubicTo(cx + unit * 0.77, cy + unit * 0.42,
                     cx + unit * 0.64, cy + unit * 0.82,
                     cx + unit * 0.54, cy + unit * 0.92)
        hair.lineTo(cx + unit * 0.40, cy + unit * 0.28)
        hair.cubicTo(cx + unit * 0.27, cy - unit * 0.06,
                     cx + unit * 0.18, cy - unit * 0.45,
                     cx + unit * 0.03, cy - unit * 0.55)
        hair.cubicTo(cx - unit * 0.10, cy - unit * 0.26,
                     cx - unit * 0.25, cy - unit * 0.12,
                     cx - unit * 0.42, cy + unit * 0.12)
        hair.lineTo(cx - unit * 0.52, cy + unit * 0.88)
        hair.cubicTo(cx - unit * 0.72, cy + unit * 0.58,
                     cx - unit * 0.82, cy + unit * 0.18,
                     cx - unit * 0.70, cy - unit * 0.18)
        hair.closeSubpath()
        painter.setBrush(QColor(255, 62, 174, 16))
        painter.setPen(QPen(QColor(255, 114, 198, 170), 1.25))
        painter.drawPath(hair)

        # Face silhouette and neck outline.
        face = QPainterPath()
        face.moveTo(cx - unit * 0.49, cy - unit * 0.45)
        face.cubicTo(cx - unit * 0.47, cy - unit * 0.04,
                     cx - unit * 0.37, cy + unit * 0.38,
                     cx, cy + unit * 0.55)
        face.cubicTo(cx + unit * 0.37, cy + unit * 0.38,
                     cx + unit * 0.47, cy - unit * 0.04,
                     cx + unit * 0.49, cy - unit * 0.45)
        face.cubicTo(cx + unit * 0.26, cy - unit * 0.71,
                     cx - unit * 0.24, cy - unit * 0.72,
                     cx - unit * 0.49, cy - unit * 0.45)
        painter.setBrush(QColor(255, 114, 198, 8))
        painter.setPen(QPen(self.COLOR_PRIMARY, 1.35))
        painter.drawPath(face)

        # Neural face grid clipped to the face outline.
        painter.save()
        painter.setClipPath(face)
        painter.setPen(QPen(QColor(255, 114, 198, 105), 0.8))
        for row in range(9):
            y = cy - unit * 0.57 + row * unit * 0.13
            half = unit * (0.17 + 0.31 * math.sin((row + 1) / 10 * math.pi))
            painter.drawLine(QPointF(cx - half, y), QPointF(cx + half, y))
        for col in range(-4, 5):
            x = cx + col * unit * 0.105
            painter.drawLine(QPointF(x, cy - unit * 0.52), QPointF(x, cy + unit * 0.48))
        painter.restore()

        # Eye glows; dim during MUTED/ERROR.
        eye_alpha = 75 if self._state in {"MUTED", "ERROR"} else 230
        eye_y = cy - unit * 0.13
        for eye_x in (cx - unit * 0.20, cx + unit * 0.20):
            painter.setPen(QPen(QColor(255, 179, 226, eye_alpha), 2.2))
            painter.drawLine(QPointF(eye_x - unit * 0.075, eye_y),
                             QPointF(eye_x + unit * 0.075, eye_y))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 62, 174, eye_alpha))
            painter.drawEllipse(QPointF(eye_x, eye_y), unit * 0.035, unit * 0.035)

        # Neural nodes and cheek/jaw links.
        nodes = [
            (cx - unit * .40, cy - unit * .34), (cx + unit * .40, cy - unit * .34),
            (cx - unit * .32, cy + unit * .05), (cx + unit * .32, cy + unit * .05),
            (cx, cy + unit * .33), (cx - unit * .20, cy + unit * .40),
            (cx + unit * .20, cy + unit * .40),
        ]
        painter.setPen(QPen(QColor(255, 114, 198, 150), 0.9))
        painter.drawLine(nodes[0][0], nodes[0][1], nodes[2][0], nodes[2][1])
        painter.drawLine(nodes[1][0], nodes[1][1], nodes[3][0], nodes[3][1])
        painter.drawLine(nodes[2][0], nodes[2][1], nodes[4][0], nodes[4][1])
        painter.drawLine(nodes[3][0], nodes[3][1], nodes[4][0], nodes[4][1])
        painter.setPen(Qt.PenStyle.NoPen)
        for x, y in nodes:
            painter.setBrush(self.COLOR_SECONDARY)
            painter.drawEllipse(QPointF(x, y), 2.3, 2.3)

        label = {
            "IDLE": "BIHANSA  •  STANDBY",
            "LISTENING": "LISTENING",
            "THINKING": "PROCESSING",
            "SPEAKING": "SPEAKING",
            "MUTED": "MICROPHONE MUTED",
            "ERROR": "VOICE UNAVAILABLE",
        }[self._state]
        painter.setPen(QColor(255, 179, 226, 220))
        from PyQt6.QtGui import QFont
        painter.setFont(QFont("Consolas", 9))
        painter.drawText(QRectF(0, h - 31, w, 18), Qt.AlignmentFlag.AlignCenter, label)
        painter.end()
