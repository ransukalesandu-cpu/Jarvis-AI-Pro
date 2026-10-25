"""
Central Neural Wireframe Hologram Widget for Jarvis AI Pro.

Renders a voice-reactive 3D parametric neural mesh with continuous rotation,
perspective projection, floating particle flow, and state-reactive morphing
(IDLE, LISTENING, THINKING, SPEAKING, PRIVACY_LOCK).
"""

from __future__ import annotations

import os
import sys
import math
import random
import time
from typing import List, Tuple, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath
from PyQt6.QtWidgets import QWidget

if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    _BASE_CANVAS = QWidget
else:
    try:
        from PyQt6.QtOpenGLWidgets import QOpenGLWidget
        _BASE_CANVAS = QOpenGLWidget
    except Exception:
        _BASE_CANVAS = QWidget


class NeuralWireframeHead(_BASE_CANVAS):
    """
    GPU-accelerated vector 3D wireframe AI visualizer.
    """

    sig_state_changed = pyqtSignal(str)

    # Palette definition
    COLOR_BG = QColor("#080b11")
    COLOR_CYAN = QColor("#00e5ff")
    COLOR_VIOLET = QColor("#7c4dff")
    COLOR_RED = QColor("#ff1744")
    COLOR_GREEN = QColor("#00e676")
    COLOR_AMBER = QColor("#ffab00")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

        # State tracking
        self._state = "IDLE"  # IDLE, LISTENING, THINKING, SPEAKING, PRIVACY_LOCK
        self._audio_energy = 0.0  # 0.0 to 1.0
        self._target_energy = 0.0

        # Animation parameters
        self._rot_x = 0.0
        self._rot_y = 0.0
        self._drift_y = 0.0
        self._start_time = time.time()
        self._glitch_intensity = 0.0

        # Generate 3D Geodesic / Neural Head Mesh geometry
        self._vertices: List[Tuple[float, float, float]] = []
        self._edges: List[Tuple[int, int]] = []
        self._particles: List[dict] = []
        self._build_mesh_geometry()
        self._build_particles()

        # Timer for ~60 FPS animation
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(16)

    def _build_mesh_geometry(self):
        """Build a geodesic neural head / sphere mesh structure."""
        vertices = []
        edges = []

        # Construct UV sphere / geodesic structure
        rings = 10
        sectors = 16
        radius = 1.0

        for r in range(rings + 1):
            v = r / rings
            phi = v * math.pi  # 0 to pi
            for s in range(sectors):
                u = s / sectors
                theta = u * 2.0 * math.pi  # 0 to 2pi

                x = radius * math.sin(phi) * math.cos(theta)
                # Slightly stretch Y axis to evoke a humanoid head profile
                y = radius * math.cos(phi) * 1.15
                z = radius * math.sin(phi) * math.sin(theta)
                vertices.append((x, y, z))

        # Build edge connectivity
        num_vertices = len(vertices)
        for r in range(rings):
            for s in range(sectors):
                first = r * sectors + s
                second = first + sectors
                next_s = (s + 1) % sectors

                # Ring edge
                edges.append((first, r * sectors + next_s))
                # Sector edge
                if second < num_vertices:
                    edges.append((first, second))
                # Diagonal cross-neural link for vector wireframe feel
                if (r + s) % 2 == 0 and (second + next_s) < num_vertices:
                    edges.append((first, r * sectors + sectors + next_s))

        self._vertices = vertices
        self._edges = edges

    def _build_particles(self):
        """Build floating orbital particles for THINKING state."""
        self._particles = []
        for _ in range(40):
            self._particles.append({
                "radius": random.uniform(1.2, 2.2),
                "angle": random.uniform(0, math.pi * 2),
                "speed": random.uniform(0.02, 0.05),
                "y_offset": random.uniform(-0.8, 0.8),
                "size": random.uniform(2.0, 4.5),
            })

    @pyqtSlot(float)
    def set_audio_energy(self, level: float):
        """Thread-safe update of microphone or TTS audio energy [0.0, 1.0]."""
        self._target_energy = max(0.0, min(1.0, float(level)))

    @pyqtSlot(str)
    def set_state(self, state: str):
        """Switch visualizer state."""
        st = str(state or "IDLE").upper()
        if st != self._state:
            self._state = st
            self.sig_state_changed.emit(st)

    def get_state(self) -> str:
        return self._state

    def _step(self):
        """Update physics & animation frame."""
        t = time.time() - self._start_time

        # Smooth audio energy lerp
        self._audio_energy += (self._target_energy - self._audio_energy) * 0.25

        # Rotation rates based on state
        if self._state == "THINKING":
            self._rot_y += 0.04
            self._rot_x += 0.025
        elif self._state == "PRIVACY_LOCK":
            self._rot_y += 0.005
            self._glitch_intensity = random.uniform(0.05, 0.25)
        else:
            self._rot_y += 0.012
            self._rot_x = math.sin(t * 0.8) * 0.15
            self._glitch_intensity = 0.0

        self._drift_y = math.sin(t * 1.5) * 12.0

        # Update orbital particles
        for p in self._particles:
            p["angle"] += p["speed"] * (2.5 if self._state == "THINKING" else 1.0)

        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        if not p.isActive():
            return

        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), self.COLOR_BG)

        W, H = self.width(), self.height()
        cx, cy = W / 2.0, (H / 2.0) + self._drift_y
        base_radius = min(W, H) * 0.28

        # Determine dynamic scale & primary color based on state
        t = time.time() - self._start_time
        scale_mod = 1.0

        if self._state == "IDLE":
            # 0.5 Hz rhythmic breathing pulse
            scale_mod = 1.0 + 0.04 * math.sin(t * math.pi)
            primary_col = self.COLOR_CYAN
            secondary_col = QColor("#00838f")
        elif self._state == "LISTENING":
            # Dynamic outward expansion scaled by RMS energy
            scale_mod = 1.0 + self._audio_energy * 0.45
            primary_col = self.COLOR_CYAN
            secondary_col = self.COLOR_CYAN
        elif self._state == "THINKING":
            scale_mod = 1.05 + 0.08 * math.sin(t * 6.0)
            primary_col = self.COLOR_VIOLET
            secondary_col = QColor("#d500f9")
        elif self._state == "SPEAKING":
            # Waveform synchronized oscillation
            scale_mod = 1.0 + self._audio_energy * 0.35 + 0.05 * math.sin(t * 12.0)
            primary_col = self.COLOR_CYAN
            secondary_col = self.COLOR_VIOLET
        elif self._state == "PRIVACY_LOCK":
            scale_mod = 0.85
            primary_col = self.COLOR_RED
            secondary_col = QColor("#b71c1c")
        else:
            primary_col = self.COLOR_CYAN
            secondary_col = self.COLOR_VIOLET

        # Project 3D vertices to 2D
        rad = base_radius * scale_mod
        projected: List[Tuple[float, float, float]] = []

        cos_y, sin_y = math.cos(self._rot_y), math.sin(self._rot_y)
        cos_x, sin_x = math.cos(self._rot_x), math.sin(self._rot_x)

        for x0, y0, z0 in self._vertices:
            # Apply glitch displacement if locked
            if self._glitch_intensity > 0:
                x0 += random.uniform(-self._glitch_intensity, self._glitch_intensity) * 0.2
                y0 += random.uniform(-self._glitch_intensity, self._glitch_intensity) * 0.2

            # Rotation Y
            x1 = x0 * cos_y + z0 * sin_y
            z1 = -x0 * sin_y + z0 * cos_y

            # Rotation X
            y2 = y0 * cos_x - z1 * sin_x
            z2 = y0 * sin_x + z1 * cos_x

            # Perspective projection
            fov = 3.5
            dist = fov / (fov + z2 + 1.2)
            px = cx + x1 * rad * dist
            py = cy + y2 * rad * dist

            projected.append((px, py, z2))

        # 1. Draw orbital particles (for THINKING state or general aura)
        if self._state == "THINKING" or self._state == "SPEAKING":
            p.setPen(Qt.PenStyle.NoPen)
            particle_col = self.COLOR_VIOLET if self._state == "THINKING" else self.COLOR_CYAN
            for pt in self._particles:
                pr = rad * pt["radius"]
                px = cx + math.cos(pt["angle"]) * pr
                pz = math.sin(pt["angle"]) * pr
                py = cy + pt["y_offset"] * rad * 0.6
                alpha = int(max(40, min(255, 180 + pz * 60)))
                p.setBrush(QBrush(QColor(particle_col.red(), particle_col.green(), particle_col.blue(), alpha)))
                sz = pt["size"] * (1.5 if self._state == "THINKING" else 1.0)
                p.drawEllipse(QPointF(px, py), sz, sz)

        # 2. Draw wireframe edges
        pen_width = 1.8 if self._state in ("LISTENING", "SPEAKING") else 1.2
        p.setPen(QPen(primary_col, pen_width))

        for idx1, idx2 in self._edges:
            x1, y1, z1 = projected[idx1]
            x2, y2, z2 = projected[idx2]

            # Depth fade
            avg_z = (z1 + z2) / 2.0
            alpha = int(max(30, min(255, 160 + avg_z * 80)))
            edge_col = QColor(primary_col.red(), primary_col.green(), primary_col.blue(), alpha)
            p.setPen(QPen(edge_col, pen_width))
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # 3. Draw neural nodes / vertices
        node_radius = 2.5 + (self._audio_energy * 4.0 if self._state in ("LISTENING", "SPEAKING") else 0.0)
        for px, py, z in projected:
            alpha = int(max(50, min(255, 200 + z * 50)))
            node_col = QColor(secondary_col.red(), secondary_col.green(), secondary_col.blue(), alpha)
            p.setBrush(QBrush(node_col))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(px, py), node_radius, node_radius)

        # 4. If PRIVACY_LOCK state, overlay Security Shield & Banner
        if self._state == "PRIVACY_LOCK":
            self._draw_lockdown_overlay(p, W, H, cx, cy)

        p.end()

    def _draw_lockdown_overlay(self, p: QPainter, W: float, H: float, cx: float, cy: float):
        """Draw prominent security lockdown overlay during PRIVACY_LOCK."""
        p.save()

        # Dim background
        p.fillRect(self.rect(), QColor(10, 0, 4, 180))

        # Shield icon
        shield_path = QPainterPath()
        sw, sh = 60.0, 70.0
        shield_path.moveTo(cx, cy - sh / 2.0)
        shield_path.lineTo(cx + sw / 2.0, cy - sh / 3.0)
        shield_path.lineTo(cx + sw / 2.0, cy + sh / 4.0)
        shield_path.lineTo(cx, cy + sh / 2.0)
        shield_path.lineTo(cx - sw / 2.0, cy + sh / 4.0)
        shield_path.lineTo(cx - sw / 2.0, cy - sh / 3.0)
        shield_path.closeSubpath()

        p.setPen(QPen(self.COLOR_RED, 3))
        p.setBrush(QBrush(QColor(183, 28, 28, 120)))
        p.drawPath(shield_path)

        # Lock text
        p.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        p.setPen(QPen(self.COLOR_RED, 1))
        p.drawText(QRectF(0, cy + sh / 2.0 + 15, W, 30), Qt.AlignmentFlag.AlignCenter, "SYSTEM PRIVACY LOCK ENGAGED")

        p.setFont(QFont("Courier New", 9, QFont.Weight.Normal))
        p.setPen(QPen(QColor("#ff8a80"), 1))
        p.drawText(QRectF(0, cy + sh / 2.0 + 45, W, 25), Qt.AlignmentFlag.AlignCenter, "MUTED & BLOCKED — PIN REQUIRED")

        p.restore()
