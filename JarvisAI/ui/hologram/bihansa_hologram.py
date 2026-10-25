"""Bihansa 3D Neural Face: opt-in portrait-derived 3D-style neural hologram visualizer.

Constructs a facial-landmark-aligned triangulated wireframe mesh over the source
portrait reference with 3D perspective projection, yaw/pitch/roll illusion,
audio-reactive mouth motion, scan lines, glowing nodes, and an extension interface
for future phoneme/viseme-based lip sync.
"""
from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget


# ---------------------------------------------------------------------------
# Facial Landmark Mesh Data Aligned to Bihansa Reference Portrait
# (Normalized [-1, 1] relative to face center, with depth Z [-0.5, 0.5])
# ---------------------------------------------------------------------------
# Key landmark point definitions:
# Jawline/Contour: 0..16
# Right Eyebrow: 17..21, Left Eyebrow: 22..26
# Nose Bridge & Tip: 27..35
# Right Eye: 36..41, Left Eye: 42..47
# Outer Lips: 48..59, Inner Lips: 60..67
# Forehead/Hairline Contour: 68..75
# Cheek nodes: 76..81

BIHANSA_LANDMARKS_3D: List[Tuple[float, float, float]] = [
    # --- Jawline & Face Oval (0 to 16) ---
    (-0.72, -0.70, -0.30), (-0.70, -0.45, -0.25), (-0.68, -0.20, -0.20),
    (-0.64,  0.05, -0.15), (-0.58,  0.30, -0.10), (-0.48,  0.55, -0.05),
    (-0.32,  0.78,  0.05), (-0.16,  0.92,  0.12), ( 0.00,  0.98,  0.15), # Chin
    ( 0.16,  0.92,  0.12), ( 0.32,  0.78,  0.05), ( 0.48,  0.55, -0.05),
    ( 0.58,  0.30, -0.10), ( 0.64,  0.05, -0.15), ( 0.68, -0.20, -0.20),
    ( 0.70, -0.45, -0.25), ( 0.72, -0.70, -0.30),

    # --- Eyebrows (17 to 26) ---
    # Right eyebrow (17..21)
    (-0.52, -0.42, 0.15), (-0.42, -0.48, 0.22), (-0.30, -0.49, 0.25),
    (-0.18, -0.46, 0.24), (-0.08, -0.40, 0.20),
    # Left eyebrow (22..26)
    ( 0.08, -0.40, 0.20), ( 0.18, -0.46, 0.24), ( 0.30, -0.49, 0.25),
    ( 0.42, -0.48, 0.22), ( 0.52, -0.42, 0.15),

    # --- Nose Bridge & Nostrils (27 to 35) ---
    ( 0.00, -0.35, 0.22), ( 0.00, -0.22, 0.28), ( 0.00, -0.08, 0.35), ( 0.00,  0.06, 0.42), # Nose bridge
    (-0.16,  0.12, 0.30), (-0.08,  0.16, 0.38), ( 0.00,  0.18, 0.42), # Tip/Nostril
    ( 0.08,  0.16, 0.38), ( 0.16,  0.12, 0.30),

    # --- Right Eye (36 to 41) ---
    (-0.45, -0.28, 0.18), (-0.36, -0.34, 0.22), (-0.24, -0.33, 0.22),
    (-0.16, -0.27, 0.18), (-0.24, -0.22, 0.16), (-0.36, -0.23, 0.16),

    # --- Left Eye (42 to 47) ---
    ( 0.16, -0.27, 0.18), ( 0.24, -0.33, 0.22), ( 0.36, -0.34, 0.22),
    ( 0.45, -0.28, 0.18), ( 0.36, -0.23, 0.16), ( 0.24, -0.22, 0.16),

    # --- Outer Lips (48 to 59) ---
    (-0.28,  0.35, 0.25), (-0.18,  0.30, 0.30), (-0.08,  0.28, 0.33),
    ( 0.00,  0.29, 0.34), ( 0.08,  0.28, 0.33), ( 0.18,  0.30, 0.30),
    ( 0.28,  0.35, 0.25), ( 0.18,  0.46, 0.28), ( 0.08,  0.50, 0.30),
    ( 0.00,  0.51, 0.31), (-0.08,  0.50, 0.30), (-0.18,  0.46, 0.28),

    # --- Inner Lips (60 to 67) ---
    (-0.22,  0.36, 0.26), (-0.08,  0.34, 0.31), ( 0.00,  0.35, 0.32),
    ( 0.08,  0.34, 0.31), ( 0.22,  0.36, 0.26), ( 0.08,  0.42, 0.29),
    ( 0.00,  0.44, 0.30), (-0.08,  0.42, 0.29),

    # --- Forehead & Hairline Contour (68 to 75) ---
    (-0.68, -0.85, -0.25), (-0.48, -0.92, -0.10), (-0.24, -0.96,  0.05),
    ( 0.00, -0.98,  0.10), ( 0.24, -0.96,  0.05), ( 0.48, -0.92, -0.10),
    ( 0.68, -0.85, -0.25), ( 0.00, -0.65,  0.12),

    # --- Cheeks & Mid-Face Anchor Nodes (76 to 81) ---
    (-0.48, -0.05, 0.05), (-0.38,  0.15, 0.12), (-0.26,  0.25, 0.18),
    ( 0.26,  0.25, 0.18), ( 0.38,  0.15, 0.12), ( 0.48, -0.05, 0.05),
]

# Triangulation indices linking landmark nodes into structural facial mesh
BIHANSA_MESH_EDGES: List[Tuple[int, int]] = [
    # Jawline
    (0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,7),(7,8),(8,9),(9,10),(10,11),(11,12),(12,13),(13,14),(14,15),(15,16),
    # Hairline & Forehead
    (16,74),(74,73),(73,72),(72,71),(71,70),(70,69),(69,68),(68,0),
    (68,17),(69,18),(70,19),(71,75),(72,24),(73,25),(74,26),
    (75,19),(75,20),(75,21),(75,22),(75,23),(75,24),
    # Eyebrows
    (17,18),(18,19),(19,20),(20,21),(22,23),(23,24),(24,25),(25,26),
    # Right Eye
    (36,37),(37,38),(38,39),(39,40),(40,41),(41,36),(36,38),(39,41),
    # Left Eye
    (42,43),(43,44),(44,45),(45,46),(46,47),(47,42),(42,44),(45,47),
    # Eyebrow to Eye links
    (17,36),(18,37),(19,38),(21,39),(22,42),(24,43),(25,44),(26,45),
    # Nose
    (27,28),(28,29),(29,30),(30,33),(31,32),(32,33),(33,34),(34,35),
    (27,21),(27,22),(27,39),(27,42),
    (28,39),(28,42),(29,76),(29,81),(30,31),(30,35),
    # Cheeks
    (36,76),(76,3),(76,4),(76,31),(76,48),
    (45,81),(81,13),(81,12),(81,35),(81,54),
    (76,77),(77,78),(78,48),(81,80),(80,79),(79,54),
    # Outer Lips
    (48,49),(49,50),(50,51),(51,52),(52,53),(53,54),(54,55),(55,56),(56,57),(57,58),(58,59),(59,48),
    # Inner Lips
    (60,61),(61,62),(62,63),(63,64),(64,65),(65,66),(66,67),(67,60),
    # Lips to Nose & Chin links
    (31,49),(32,50),(33,51),(34,52),(35,53),
    (57,8),(58,7),(59,6),(55,9),(56,10),
    (48,60),(51,62),(54,64),(57,66),
]


class BihansaHologramWidget(QWidget):
    """3D-style portrait-derived neural hologram visualizer for Bihansa mode."""

    sig_viseme_changed = pyqtSignal(str, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)

        self._state = "IDLE"
        self._effects_enabled = True
        self._voice_reactive = True
        self._audio_energy = 0.0
        self._target_energy = 0.0

        # Animation pose parameters (Yaw, Pitch, Roll in radians)
        self._yaw = 0.0
        self._pitch = 0.0
        self._roll = 0.0
        self._breath_scale = 1.0
        self._scan = 0.0
        self._start_time = time.monotonic()

        # Phoneme / Viseme blend weights for future lip-sync architecture
        self._viseme_weights: Dict[str, float] = {
            "aa": 0.0, "ee": 0.0, "oh": 0.0, "ou": 0.0, "ch": 0.0, "m": 0.0
        }

        # Background orbital particles
        self._particles = [
            {
                "x": random.uniform(-1.2, 1.2),
                "y": random.uniform(-1.2, 1.2),
                "z": random.uniform(-0.8, 0.8),
                "speed": random.uniform(0.3, 1.2),
                "size": random.uniform(1.8, 3.8),
                "phase": random.uniform(0, math.tau),
            }
            for _ in range(60)
        ]

        # Load portrait reference asset safely regardless of current working directory
        assets_dir = Path(__file__).resolve().parents[2] / "assets"
        self._portrait_path = assets_dir / "bihansa_reference.png"
        self._portrait = QPixmap(str(self._portrait_path))

        # Render loop timer (~30 FPS for smooth, efficient UI response)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # -----------------------------------------------------------------------
    # Control API
    # -----------------------------------------------------------------------
    @pyqtSlot(str)
    def set_state(self, state: str):
        self._state = str(state or "IDLE").upper()
        self.update()

    def get_state(self) -> str:
        return self._state

    @pyqtSlot(bool)
    def set_effects_enabled(self, enabled: bool):
        self._effects_enabled = bool(enabled)
        self.update()

    @pyqtSlot(bool)
    def set_voice_reactive(self, enabled: bool):
        self._voice_reactive = bool(enabled)
        if not self._voice_reactive:
            self._target_energy = 0.0
            self._audio_energy = 0.0
        self.update()

    @pyqtSlot(float)
    def set_audio_energy(self, level: float):
        try:
            self._target_energy = max(0.0, min(1.0, float(level))) if self._voice_reactive else 0.0
        except (TypeError, ValueError):
            self._target_energy = 0.0

    @pyqtSlot(str, float)
    def set_viseme(self, viseme_id: str, weight: float = 1.0):
        """Phoneme/viseme extension point for future voice-driven lip sync."""
        vid = str(viseme_id or "").lower()
        if vid in self._viseme_weights:
            self._viseme_weights[vid] = max(0.0, min(1.0, float(weight)))
            self.sig_viseme_changed.emit(vid, self._viseme_weights[vid])
            self.update()

    # -----------------------------------------------------------------------
    # Tick Update Loop
    # -----------------------------------------------------------------------
    def _tick(self):
        t = time.monotonic() - self._start_time

        # Audio energy smooth lerp
        self._audio_energy += (self._target_energy - self._audio_energy) * 0.22

        # 3D Yaw/Pitch/Roll restrained movement illusion
        if self._state == "THINKING":
            self._yaw = math.sin(t * 1.8) * 0.18
            self._pitch = math.cos(t * 1.4) * 0.12
            self._roll = math.sin(t * 0.9) * 0.05
        elif self._state == "SPEAKING":
            self._yaw = math.sin(t * 1.2) * 0.10
            self._pitch = math.sin(t * 2.1) * 0.08 + self._audio_energy * 0.05
            self._roll = math.cos(t * 0.8) * 0.04
        else:
            # Idle gentle motion
            self._yaw = math.sin(t * 0.6) * 0.08
            self._pitch = math.cos(t * 0.5) * 0.05
            self._roll = math.sin(t * 0.3) * 0.02

        # Breathing scale mod
        self._breath_scale = 1.0 + 0.03 * math.sin(t * 1.2) + (self._audio_energy * 0.08)

        # Scan line progression
        self._scan = (self._scan + (0.015 if self._state == "SPEAKING" else 0.007)) % 1.0

        self.update()

    # -----------------------------------------------------------------------
    # Render Paint Event
    # -----------------------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        if not p.isActive():
            return

        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        t = time.monotonic() - self._start_time

        # Dark sleek background
        p.fillRect(self.rect(), QColor("#0e0512"))

        cx, cy = w / 2.0, h * 0.44
        face_box_size = min(w, h) * 0.42

        # --- 1. Background Orbital Rings & Neural Glow ---
        if self._effects_enabled:
            self._draw_holographic_aura(p, cx, cy, min(w, h), t)

        # --- 2. Portrait Reference Base ---
        margin_x = w * 0.12
        top_y = h * 0.06
        portrait_w = w - 2 * margin_x
        portrait_h = h * 0.78
        target_rect = QRectF(margin_x, top_y, portrait_w, portrait_h)

        if not self._portrait.isNull():
            scaled_p = self._portrait.scaled(
                int(portrait_w), int(portrait_h),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            px = (w - scaled_p.width()) / 2.0
            py = top_y + (portrait_h - scaled_p.height()) / 2.0
            p_rect = QRectF(px, py, scaled_p.width(), scaled_p.height())

            p.setPen(QPen(QColor(255, 79, 200, 140), 1.5))
            p.setBrush(QColor(20, 5, 22, 190))
            p.drawRoundedRect(target_rect, 16, 16)

            p.drawPixmap(int(px), int(py), scaled_p)

            # Holographic scan overlay & subtle tint
            p.save()
            p.setClipRect(p_rect)
            if self._effects_enabled:
                p.fillRect(p_rect, QColor(255, 45, 190, 20))
                scan_y = py + self._scan * scaled_p.height()
                p.setPen(QPen(QColor(255, 175, 238, 160), 1.5))
                p.drawLine(QPointF(px, scan_y), QPointF(px + scaled_p.width(), scan_y))
            p.restore()
        else:
            # Fallback if image asset missing
            p.setPen(QPen(QColor("#ff4fc8"), 1.5))
            p.setBrush(QColor(20, 5, 22, 190))
            p.drawRoundedRect(target_rect, 16, 16)
            p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            p.drawText(target_rect, Qt.AlignmentFlag.AlignCenter, "BIHANSA REFERENCE PORTRAIT NOT FOUND")

        # --- 3. Landmark-Aligned 3D Triangulated Mesh Overlay ---
        if self._effects_enabled:
            self._draw_3d_face_mesh(p, cx, cy, face_box_size * self._breath_scale)

        # --- 4. Floating Neural Particles ---
        if self._effects_enabled:
            self._draw_particles(p, w, h, t)

        # --- 5. Status Footer Banner ---
        self._draw_status_banner(p, w, h)

        p.end()

    # -----------------------------------------------------------------------
    # Helper Render Routines
    # -----------------------------------------------------------------------
    def _draw_holographic_aura(self, p: QPainter, cx: float, cy: float, sz: float, t: float):
        hot = QColor("#ff9be8")
        pink = QColor("#ff4fc8")

        p.setPen(Qt.PenStyle.NoPen)
        for r_factor, alpha in ((0.42, 12), (0.35, 16)):
            p.setBrush(QColor(255, 45, 190, alpha))
            p.drawEllipse(QPointF(cx, cy), sz * r_factor, sz * r_factor * 1.1)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 79, 200, 110), 1.0))
        p.drawEllipse(QPointF(cx, cy), sz * 0.40, sz * 0.45)

        arc_rect = QRectF(cx - sz * 0.44, cy - sz * 0.48, sz * 0.88, sz * 0.96)
        p.setPen(QPen(hot, 2.0))
        p.drawArc(arc_rect, int((t * 22 % 360) * 16), 110 * 16)

        p.setPen(QPen(pink, 1.2, Qt.PenStyle.DashLine))
        p.drawArc(arc_rect.adjusted(10, 10, -10, -10), int((-t * 28 % 360) * 16), 80 * 16)

    def _draw_3d_face_mesh(self, p: QPainter, cx: float, cy: float, scale: float):
        """Projects 3D face landmarks with yaw/pitch/roll into 2D canvas coordinates."""
        cos_y, sin_y = math.cos(self._yaw), math.sin(self._yaw)
        cos_p, sin_p = math.cos(self._pitch), math.sin(self._pitch)
        cos_r, sin_r = math.cos(self._roll), math.sin(self._roll)

        # Compute dynamic mouth displacement (audio reactive energy + viseme blend)
        mouth_open_y = self._audio_energy * 0.18
        if self._viseme_weights["aa"] > 0:
            mouth_open_y += self._viseme_weights["aa"] * 0.22
        if self._viseme_weights["oh"] > 0:
            mouth_open_y += self._viseme_weights["oh"] * 0.18

        projected_pts: List[Tuple[float, float, float]] = []

        for idx, (x0, y0, z0) in enumerate(BIHANSA_LANDMARKS_3D):
            # Apply mouth deformation to lower lip and chin landmarks (indices 7..10, 55..59, 65..67)
            if idx in (7, 8, 9, 10, 55, 56, 57, 58, 59, 65, 66, 67):
                y0 = y0 + mouth_open_y

            # 3D Rotations
            # Yaw (around Y)
            x1 = x0 * cos_y + z0 * sin_y
            z1 = -x0 * sin_y + z0 * cos_y

            # Pitch (around X)
            y2 = y0 * cos_p - z1 * sin_p
            z2 = y0 * sin_p + z1 * cos_p

            # Roll (around Z)
            x3 = x1 * cos_r - y2 * sin_r
            y3 = x1 * sin_r + y2 * cos_r

            # Perspective projection
            fov = 3.2
            dist = fov / (fov + z2 + 0.4)
            px = cx + x3 * scale * dist
            py = cy + y3 * scale * dist

            projected_pts.append((px, py, z2))

        # Render Wireframe Mesh Edges
        primary_col = QColor("#ff6fe2") if self._state != "LISTENING" else QColor("#67eaff")
        edge_pen_width = 1.4 if self._state in ("SPEAKING", "LISTENING") else 1.0

        for i1, i2 in BIHANSA_MESH_EDGES:
            if i1 < len(projected_pts) and i2 < len(projected_pts):
                x1, y1, z1 = projected_pts[i1]
                x2, y2, z2 = projected_pts[i2]

                avg_z = (z1 + z2) / 2.0
                alpha = int(max(40, min(255, 170 + avg_z * 110)))
                p.setPen(QPen(QColor(primary_col.red(), primary_col.green(), primary_col.blue(), alpha), edge_pen_width))
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Render Glowing Landmark Nodes
        node_radius = 2.0 + (self._audio_energy * 3.0 if self._state in ("SPEAKING", "LISTENING") else 0.0)
        p.setPen(Qt.PenStyle.NoPen)
        for px, py, z in projected_pts:
            alpha = int(max(60, min(255, 190 + z * 90)))
            node_col = QColor(255, 185, 240, alpha) if self._state != "LISTENING" else QColor(103, 234, 255, alpha)
            p.setBrush(QBrush(node_col))
            p.drawEllipse(QPointF(px, py), node_radius, node_radius)

    def _draw_particles(self, p: QPainter, w: float, h: float, t: float):
        p.setPen(Qt.PenStyle.NoPen)
        for pt in self._particles:
            drift_x = math.sin(t * pt["speed"] + pt["phase"]) * 0.02
            drift_y = math.cos(t * pt["speed"] + pt["phase"]) * 0.02
            px = (pt["x"] + drift_x + 1.0) * 0.5 * w
            py = (pt["y"] + drift_y + 1.0) * 0.5 * h

            alpha = int(90 + 130 * (0.5 + 0.5 * math.sin(t * 2.0 + pt["phase"])))
            p.setBrush(QColor(255, 115, 225, alpha))
            sz = pt["size"] + (self._audio_energy * 2.0)
            p.drawEllipse(QPointF(px, py), sz, sz)

    def _draw_status_banner(self, p: QPainter, w: float, h: float):
        cyan = QColor("#67eaff")
        hot = QColor("#ff9be8")

        p.setPen(QPen(cyan if self._state == "LISTENING" else hot, 1))
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))

        label = (
            "BIHANSA // LISTENING" if self._state == "LISTENING" else
            "BIHANSA // SPEAKING" if self._state == "SPEAKING" else
            "BIHANSA // THINKING" if self._state == "THINKING" else
            "BIHANSA // 3D NEURAL LINK"
        )
        p.drawText(QRectF(0, h * 0.88, w, 20), Qt.AlignmentFlag.AlignCenter, label)

        p.setPen(QPen(QColor(255, 115, 225, 180), 1))
        p.setFont(QFont("Courier New", 8, QFont.Weight.Normal))
        p.drawText(QRectF(0, h * 0.93, w, 18), Qt.AlignmentFlag.AlignCenter,
                   "PORTRAIT-ALIGNED 3D WIREFRAME MESH  •  " + self._state)
