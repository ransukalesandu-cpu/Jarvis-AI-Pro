"""Floating holographic orb for JARVIS AI Pro.

Standalone QPainter widget. It sits beneath the neural wireframe face and
gives LISTENING / THINKING / SPEAKING a lightweight, state-distinct visual
treatment: rotating data rings, a pulsing core and a thin dust of orbiting
particles. It shares its colour identity with the face through
``core.hologram_theme`` so JARVIS (copper) and Bihansa (pink) just swap
palettes, and it exposes the same ``set_state`` / ``set_audio_energy`` /
``set_performance_budget`` surface as ``NeuralWireframeHead`` so it can be
driven from the same signals without any persona-specific glue code.

This widget is fully standalone: it can be dropped into any layout on its
own. ``hologram_panel.py`` additionally uses it as part of a combined face +
orb + reactor assembly.
"""

from __future__ import annotations

import math
import random
import time
from typing import List

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from core.hologram_theme import JARVIS_PALETTE, ThemePalette


class HolographicOrb(QWidget):
    """Small voice-reactive orb that floats beneath the hologram face."""

    sig_state_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(64, 64)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self._palette: ThemePalette = JARVIS_PALETTE
        self._state = "IDLE"
        self._audio_energy = 0.0
        self._target_energy = 0.0
        self._rotation = 0.0
        self._reduced_motion = False
        self._particle_budget = 1.0
        self._glow_scale = 1.0
        self._frame_interval = 33
        self._start_time = time.time()

        self._particles: List[dict] = []
        self._build_particles()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(self._frame_interval)

    # ── geometry ────────────────────────────────────────────────────────────
    def _build_particles(self):
        self._particles = []
        for _ in range(16):
            self._particles.append({
                "radius": random.uniform(0.78, 1.15),
                "angle": random.uniform(0, math.pi * 2),
                "speed": random.uniform(0.015, 0.04),
                "size": random.uniform(1.2, 2.6),
            })

    # ── public API (mirrors NeuralWireframeHead) ───────────────────────────
    @pyqtSlot(float)
    def set_audio_energy(self, level: float):
        try:
            self._target_energy = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            self._target_energy = 0.0

    @pyqtSlot(str)
    def set_state(self, state: str):
        st = str(state or "IDLE").upper()
        if st == "LOCKDOWN":
            st = "PRIVACY_LOCK"
        if st != self._state:
            self._state = st
            self.sig_state_changed.emit(st)
            self.update()

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
        self._particle_budget = max(0.0, min(1.0, float(particle_scale)))
        self._glow_scale = max(0.2, min(1.0, float(glow_scale)))

    def anchor_point(self) -> QPointF:
        """Right-hand connection point, used to wire up the heart reactor."""
        return QPointF(self.width() * 0.84, self.height() * 0.52)

    def top_anchor_point(self) -> QPointF:
        """Top connection point, used to wire up to the face above it."""
        return QPointF(self.width() * 0.5, self.height() * 0.1)

    # ── animation ───────────────────────────────────────────────────────────
    def _step(self):
        self._audio_energy += (self._target_energy - self._audio_energy) * 0.25
        if not self._reduced_motion:
            spin = {"THINKING": 0.05, "SPEAKING": 0.03, "LISTENING": 0.022}.get(self._state, 0.012)
            self._rotation = (self._rotation + spin) % (math.pi * 2)
            boost = 2.0 if self._state == "THINKING" else 1.0
            for particle in self._particles:
                particle["angle"] += particle["speed"] * boost
        self.update()

    # ── painting ────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Source composition with an explicit zero-alpha fill clears the
        # widget to true transparency on every frame, regardless of whether
        # the underlying platform backing store was opaque last frame.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        radius = min(w, h) * 0.30
        t = time.time() - self._start_time
        palette = self._palette
        primary = QColor(*palette.primary)
        secondary = QColor(*palette.secondary)
        accent = QColor(*palette.accent)

        pulse = 1.0
        ring_alpha = 90
        core_colour = secondary
        if self._state == "IDLE":
            pulse = 1.0 + (0.0 if self._reduced_motion else 0.05 * math.sin(t * 1.6))
        elif self._state == "LISTENING":
            pulse = 1.0 + self._audio_energy * 0.35
            ring_alpha = 120 + int(80 * self._audio_energy)
        elif self._state == "THINKING":
            pulse = 1.05 + (0.0 if self._reduced_motion else 0.06 * math.sin(t * 5.0))
            ring_alpha = 150
            core_colour = secondary
        elif self._state == "SPEAKING":
            pulse = 1.0 + self._audio_energy * 0.45
            ring_alpha = 130 + int(100 * self._audio_energy)
            core_colour = accent
        elif self._state == "PRIVACY_LOCK":
            pulse = 0.82
            core_colour = QColor("#ff1744")
            ring_alpha = 60
        elif self._state in ("ERROR", "DISCONNECTED"):
            pulse = 0.9
            core_colour = QColor("#ff6b6b")
            ring_alpha = 60

        core_radius = radius * pulse

        # 1. Soft outer bloom.
        halo = QRadialGradient(QPointF(cx, cy), core_radius * 2.1)
        alpha = int(70 * self._glow_scale)
        halo.setColorAt(0.0, QColor(primary.red(), primary.green(), primary.blue(), alpha))
        halo.setColorAt(0.6, QColor(primary.red(), primary.green(), primary.blue(), alpha // 3))
        halo.setColorAt(1.0, QColor(primary.red(), primary.green(), primary.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QPointF(cx, cy), core_radius * 2.1, core_radius * 2.1)

        # 2. Orbiting dust.
        visible = int(len(self._particles) * self._particle_budget)
        if visible and self._state != "PRIVACY_LOCK":
            painter.setPen(Qt.PenStyle.NoPen)
            for particle in self._particles[:visible]:
                pr = core_radius * particle["radius"] * 1.5
                px = cx + math.cos(particle["angle"]) * pr
                py = cy + math.sin(particle["angle"]) * pr * 0.55
                painter.setBrush(QColor(secondary.red(), secondary.green(), secondary.blue(), 150))
                painter.drawEllipse(QPointF(px, py), particle["size"], particle["size"])

        # 3. Rotating data rings — two counter-rotating broken ellipses so
        # THINKING reads as "processing" without needing any text.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i, ratio in enumerate((1.0, 0.72)):
            pen = QPen(QColor(secondary.red(), secondary.green(), secondary.blue(), ring_alpha))
            pen.setWidthF(1.4)
            painter.setPen(pen)
            span = 110 * 16
            start = int((self._rotation * (1 if i == 0 else -1.4)) * 180 / math.pi * 16)
            rect = QRectF(cx - core_radius * ratio, cy - core_radius * ratio,
                          core_radius * ratio * 2, core_radius * ratio * 2)
            painter.drawArc(rect, start, span)
            painter.drawArc(rect, start + 180 * 16, span)

        # 4. Glowing core.
        core_grad = QRadialGradient(QPointF(cx, cy), core_radius)
        core_grad.setColorAt(0.0, QColor(255, 250, 240, 235))
        core_grad.setColorAt(0.35, QColor(core_colour.red(), core_colour.green(), core_colour.blue(), 220))
        core_grad.setColorAt(1.0, QColor(core_colour.red(), core_colour.green(), core_colour.blue(), 30))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(core_grad)
        painter.drawEllipse(QPointF(cx, cy), core_radius * 0.62, core_radius * 0.62)

        painter.end()
