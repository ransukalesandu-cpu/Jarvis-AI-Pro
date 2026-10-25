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
    (-0.810000, -0.125000, 0.100000),
    (-0.794375, 0.031250, 0.131250),
    (-0.766250, 0.187500, 0.167500),
    (-0.719375, 0.343750, 0.211250),
    (-0.635000, 0.487500, 0.260000),
    (-0.528750, 0.618750, 0.310000),
    (-0.372500, 0.712500, 0.360000),
    (-0.193750, 0.774375, 0.395000),
    (0.000000, 0.815000, 0.420000),
    (0.196875, 0.765000, 0.395000),
    (0.377500, 0.688750, 0.360000),
    (0.533750, 0.573125, 0.310000),
    (0.640000, 0.425000, 0.260000),
    (0.724375, 0.265625, 0.211250),
    (0.771250, 0.093750, 0.167500),
    (0.799375, -0.068750, 0.131250),
    (0.815000, -0.225000, 0.100000),
    (-0.610000, -0.275000, 0.250000),
    (-0.485000, -0.335000, 0.300000),
    (-0.335000, -0.350000, 0.350000),
    (-0.185000, -0.325000, 0.380000),
    (-0.085000, -0.285000, 0.390000),
    (0.090000, -0.300000, 0.390000),
    (0.215000, -0.365000, 0.380000),
    (0.365000, -0.385000, 0.350000),
    (0.515000, -0.365000, 0.300000),
    (0.640000, -0.300000, 0.250000),
    (0.000000, -0.285000, 0.400000),
    (0.000000, -0.150000, 0.450000),
    (0.000000, 0.000000, 0.500000),
    (0.000000, 0.135000, 0.550000),
    (-0.135000, 0.175000, 0.480000),
    (-0.060000, 0.205000, 0.540000),
    (0.000000, 0.215000, 0.580000),
    (0.065000, 0.205000, 0.540000),
    (0.140000, 0.165000, 0.480000),
    (-0.510000, -0.185000, 0.320000),
    (-0.410000, -0.235000, 0.340000),
    (-0.310000, -0.235000, 0.350000),
    (-0.210000, -0.185000, 0.340000),
    (-0.310000, -0.135000, 0.330000),
    (-0.410000, -0.135000, 0.330000),
    (0.190000, -0.215000, 0.340000),
    (0.290000, -0.285000, 0.350000),
    (0.390000, -0.285000, 0.340000),
    (0.490000, -0.265000, 0.320000),
    (0.390000, -0.215000, 0.330000),
    (0.290000, -0.215000, 0.330000),
    (-0.285000, 0.415000, 0.350000),
    (-0.201667, 0.381667, 0.370000),
    (-0.106667, 0.365000, 0.393333),
    (0.000000, 0.365000, 0.420000),
    (0.110000, 0.355000, 0.393333),
    (0.206667, 0.361667, 0.370000),
    (0.290000, 0.385000, 0.350000),
    (0.206667, 0.438333, 0.370000),
    (0.110000, 0.471667, 0.393333),
    (0.000000, 0.485000, 0.420000),
    (-0.106667, 0.471667, 0.393333),
    (-0.201667, 0.448333, 0.370000),
    (-0.235000, 0.415000, 0.360000),
    (-0.110000, 0.400000, 0.390000),
    (0.000000, 0.400000, 0.410000),
    (0.115000, 0.390000, 0.390000),
    (0.240000, 0.390000, 0.360000),
    (0.115000, 0.425000, 0.390000),
    (0.000000, 0.435000, 0.410000),
    (-0.110000, 0.425000, 0.390000),
    (-0.710000, -0.625000, 0.180000),
    (-0.510000, -0.725000, 0.226667),
    (-0.273333, -0.791667, 0.266667),
    (0.000000, -0.825000, 0.300000),
    (0.260000, -0.825000, 0.266667),
    (0.490000, -0.791667, 0.226667),
    (0.690000, -0.725000, 0.180000),
    (0.000000, -0.500000, 0.300000),
    (-0.660000, 0.175000, 0.220000),
    (-0.510000, 0.265000, 0.280000),
    (-0.385000, 0.350000, 0.320000),
    (0.415000, 0.335000, 0.320000),
    (0.540000, 0.225000, 0.280000),
    (0.665000, 0.100000, 0.220000),
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

# Surface patches join eye, nose, cheek and chin contours into triangles.
BIHANSA_MESH_TRIANGLES = (
    (17, 18, 36), (18, 36, 37), (18, 19, 37), (19, 37, 38),
    (19, 20, 38), (20, 21, 39), (20, 38, 39),
    (22, 23, 42), (23, 42, 43), (23, 24, 43), (24, 25, 44),
    (24, 43, 44), (25, 26, 45), (25, 44, 45),
    (39, 27, 28), (42, 27, 28), (39, 28, 29), (42, 28, 29),
    (40, 39, 31), (39, 29, 31), (29, 30, 31), (30, 31, 33),
    (47, 42, 35), (42, 29, 35), (29, 30, 35), (30, 33, 35),
    (36, 41, 76), (41, 40, 76), (40, 31, 76),
    (45, 46, 81), (46, 47, 81), (47, 35, 81),
    (76, 31, 77), (31, 48, 77), (77, 48, 78),
    (81, 35, 80), (35, 54, 80), (80, 54, 79),
    (3, 4, 76), (4, 5, 48), (4, 48, 76), (5, 6, 48),
    (13, 12, 81), (12, 11, 54), (12, 54, 81), (11, 10, 54),
    (6, 7, 59), (6, 48, 59), (7, 8, 58), (7, 58, 59),
    (8, 57, 58), (8, 9, 57), (9, 55, 57), (9, 10, 55), (10, 54, 55),
)
BIHANSA_MESH_EDGES = sorted(set(
    tuple(sorted(edge)) for edge in BIHANSA_MESH_EDGES
) | {
    tuple(sorted((triangle[i], triangle[(i + 1) % 3])))
    for triangle in BIHANSA_MESH_TRIANGLES for i in range(3)
})



class BihansaHologramWidget(QWidget):
    """3D-style portrait-derived neural hologram visualizer for Bihansa mode."""

    sig_viseme_changed = pyqtSignal(str, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)

        self._reduced_motion = False
        self._glow_intensity = 1.0
        self._animation_speed = 1.0
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
    def set_reduced_motion(self, enabled: bool):
        self._reduced_motion = bool(enabled)
        self._tick()

    def set_glow_intensity(self, intensity: float):
        self._glow_intensity = max(0.0, min(1.5, float(intensity)))
        self.update()

    def set_animation_speed(self, speed: float):
        self._animation_speed = max(0.0, min(2.0, float(speed)))
        self.update()

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
        t = 0.0 if self._reduced_motion else (time.monotonic() - self._start_time) * self._animation_speed

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
        if self._reduced_motion or self._animation_speed == 0:
            self._yaw = self._pitch = self._roll = 0.0
            self._breath_scale = 1.0
        else:
            self._scan = (self._scan + self._animation_speed * (0.015 if self._state == "SPEAKING" else 0.007)) % 1.0

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
        t = 0.0 if self._reduced_motion else (time.monotonic() - self._start_time) * self._animation_speed

        # Dark sleek background
        p.fillRect(self.rect(), QColor("#0e0512"))

        cx, cy = w / 2.0, h * 0.44

        # --- 1. Background Orbital Rings & Neural Glow ---
        if self._effects_enabled:
            self._draw_holographic_aura(p, cx, cy, min(w, h), t)

        # --- 2. Portrait Reference Base ---
        margin_x = w * 0.12
        top_y = h * 0.06
        portrait_w = w - 2 * margin_x
        portrait_h = h * 0.78
        target_rect = QRectF(margin_x, top_y, portrait_w, portrait_h)

        p_rect = target_rect
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
            p.save()
            p.setClipRect(p_rect)
            p.setOpacity(min(1.0, self._glow_intensity))
            self._draw_3d_face_mesh(p, p_rect)
            p.restore()

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

    def _project_face_mesh(self, rect: QRectF) -> List[Tuple[float, float, float]]:
        """Project the mesh into the exact fitted portrait rectangle."""
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
            # Normalize perspective against the rest pose so landmarks match
            # the portrait at zero rotation; animation adds restrained parallax.
            rest_dist = fov / (fov + z0 + 0.4)
            perspective = dist / rest_dist
            px = rect.x() + (0.492 + x3 * 0.2 * perspective * self._breath_scale) * rect.width()
            py = rect.y() + (0.385 + y3 * 0.2 * perspective * self._breath_scale) * rect.height()

            projected_pts.append((px, py, z2))

        return projected_pts

    def _draw_3d_face_mesh(self, p: QPainter, rect: QRectF):
        projected_pts = self._project_face_mesh(rect)
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
