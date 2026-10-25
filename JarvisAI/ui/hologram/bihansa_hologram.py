"""Bihansa Mode: opt-in portrait-based neural hologram visualizer.

The portrait remains a 2D reference image; Qt paints a holographic treatment
around it. This does not synthesize a true 3D model or alter the source image.
"""
from __future__ import annotations

import math
import random
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt6.QtGui import QColor, QBrush, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget


class BihansaHologramWidget(QWidget):
    """Animated pink neural hologram using the locally bundled portrait."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self._state = "IDLE"
        self._energy = 0.0
        self._target_energy = 0.0
        self._started = time.monotonic()
        self._scan = 0.0
        self._particles = [
            (random.random(), random.random(), random.uniform(0.7, 2.2),
             random.uniform(0.15, 0.8), random.random() * math.tau)
            for _ in range(70)
        ]
        # Works when launched from a different current working directory.
        assets_dir = Path(__file__).resolve().parents[2] / "assets"
        self._portrait_path = assets_dir / "bihansa_reference.png"
        self._portrait = QPixmap(str(self._portrait_path))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state: str):
        self._state = str(state or "IDLE").upper()
        self.update()

    def set_audio_energy(self, level: float):
        try:
            self._target_energy = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            self._target_energy = 0.0

    def _tick(self):
        self._energy += (self._target_energy - self._energy) * 0.22
        self._scan = (self._scan + (0.012 if self._state == "SPEAKING" else 0.006)) % 1.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#100613"))
        t = time.monotonic() - self._started
        cx, cy = w / 2.0, h * 0.46
        pink = QColor("#ff4fc8")
        hot = QColor("#ff9be8")
        cyan = QColor("#67eaff")

        # Soft radial-looking glow, orbital rings and HUD arcs.
        p.setPen(Qt.PenStyle.NoPen)
        for radius, alpha in ((min(w, h) * .39, 12), (min(w, h) * .32, 10)):
            p.setBrush(QColor(255, 45, 190, alpha))
            p.drawEllipse(QPointF(cx, cy), radius, radius * 1.12)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 79, 200, 150), 1.1))
        p.drawEllipse(QPointF(cx, cy), min(w, h) * .37, min(w, h) * .43)
        p.setPen(QPen(QColor(255, 155, 232, 95), 1, Qt.PenStyle.DashLine))
        p.drawEllipse(QPointF(cx, cy), min(w, h) * .42, min(w, h) * .47)
        arc = QRectF(cx - min(w, h)*.43, cy - min(w, h)*.45,
                     min(w, h)*.86, min(w, h)*.90)
        p.setPen(QPen(hot, 2.0))
        p.drawArc(arc, int((t * 24 % 360) * 16), 112 * 16)
        p.setPen(QPen(pink, 1.5))
        p.drawArc(arc.adjusted(9, 9, -9, -9), int((-t * 31 % 360) * 16), 72 * 16)

        # Portrait is scaled with aspect ratio preserved and softly clipped.
        margin_x = w * .12
        top = h * .055
        portrait_w = w - 2 * margin_x
        portrait_h = h * .80
        target = QRectF(margin_x, top, portrait_w, portrait_h)
        if not self._portrait.isNull():
            scaled = self._portrait.scaled(
                int(portrait_w), int(portrait_h),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            px = (w - scaled.width()) / 2
            py = top + (portrait_h - scaled.height()) / 2
            # A subtle pink halo behind the portrait frame.
            p.setPen(QPen(QColor(255, 79, 200, 130), 2))
            p.setBrush(QColor(30, 7, 31, 190))
            p.drawRoundedRect(target, 18, 18)
            p.drawPixmap(int(px), int(py), scaled)
            # Light hologram tint and fine horizontal scan lines, not face replacement.
            p.save()
            p.setClipRect(QRectF(px, py, scaled.width(), scaled.height()))
            p.fillRect(QRectF(px, py, scaled.width(), scaled.height()),
                       QColor(255, 45, 190, 24))
            scan_y = py + self._scan * scaled.height()
            p.setPen(QPen(QColor(255, 155, 232, 135), 1.2))
            p.drawLine(QPointF(px, scan_y), QPointF(px + scaled.width(), scan_y))
            p.setPen(QPen(QColor(255, 105, 220, 24), 1))
            for yy in range(int(py), int(py + scaled.height()), 5):
                p.drawLine(int(px), yy, int(px + scaled.width()), yy)
            p.restore()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(hot, 1.2))
            p.drawRoundedRect(target, 18, 18)
        else:
            p.setPen(QPen(pink, 1.5))
            p.drawRoundedRect(target, 18, 18)
            p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
            p.drawText(target, Qt.AlignmentFlag.AlignCenter,
                       "BIHANSA REFERENCE IMAGE NOT FOUND")

        # Neural particles drift around the portrait.
        p.setPen(Qt.PenStyle.NoPen)
        for nx, ny, size, speed, phase in self._particles:
            drift = math.sin(t * speed + phase) * 0.018
            x = (nx + drift) * w
            y = (ny + math.cos(t * speed + phase) * .012) * h
            alpha = int(85 + 140 * (0.5 + 0.5 * math.sin(t * 1.8 + phase)))
            p.setBrush(QColor(255, 105, 220, alpha))
            p.drawEllipse(QPointF(x, y), size + self._energy, size + self._energy)
        # Small network links near the outer edge of the portrait.
        p.setPen(QPen(QColor(255, 105, 220, 75), 0.8))
        for i in range(0, len(self._particles) - 5, 5):
            a, b = self._particles[i], self._particles[i + 5]
            p.drawLine(QPointF(a[0] * w, a[1] * h),
                       QPointF(b[0] * w, b[1] * h))

        p.setPen(QPen(cyan if self._state == "LISTENING" else hot, 1))
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        label = "BIHANSA // LISTENING" if self._state == "LISTENING" else (
            "BIHANSA // SPEAKING" if self._state == "SPEAKING" else
            "BIHANSA // NEURAL LINK")
        p.drawText(QRectF(0, h * .88, w, 22), Qt.AlignmentFlag.AlignCenter, label)
        p.setPen(QPen(QColor(255, 79, 200, 170), 1))
        p.drawText(QRectF(0, h * .93, w, 18), Qt.AlignmentFlag.AlignCenter,
                   "REFERENCE-BASED HOLOGRAM  •  " + self._state)
        p.end()
