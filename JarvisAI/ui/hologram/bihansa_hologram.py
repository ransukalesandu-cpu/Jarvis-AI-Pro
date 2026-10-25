"""Bihansa Mode: opt-in portrait-based neural hologram visualizer.

Constructs a landmark-aligned 2.5D neural face mesh overlaid on the reference portrait.
Preserves Bihansa's exact facial likeness (eye shape, nose, lip contours, jawline, chin)
using normalized feature landmark coordinates aligned to bihansa_reference.png.
"""

from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Dict, List, Tuple

from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QBrush
from PyQt6.QtWidgets import QWidget


# Feature landmark coordinates normalized relative to the source reference portrait (1145x1374)
LANDMARK_GROUPS: Dict[str, List[Tuple[float, float, float]]] = {
    # (x, y, z_depth)
    "jaw": [
        (0.330, 0.360, 0.10), (0.335, 0.410, 0.15), (0.350, 0.460, 0.22),
        (0.380, 0.505, 0.30), (0.430, 0.535, 0.38), (0.492, 0.548, 0.42), # Chin tip
        (0.555, 0.532, 0.38), (0.605, 0.495, 0.30), (0.635, 0.445, 0.22),
        (0.650, 0.390, 0.15), (0.655, 0.340, 0.10)
    ],
    "lbrow": [
        (0.370, 0.330, 0.25), (0.395, 0.318, 0.30), (0.425, 0.315, 0.35),
        (0.455, 0.320, 0.38), (0.475, 0.328, 0.39)
    ],
    "rbrow": [
        (0.510, 0.325, 0.39), (0.535, 0.312, 0.38), (0.565, 0.308, 0.35),
        (0.595, 0.312, 0.30), (0.620, 0.325, 0.25)
    ],
    "leye": [
        (0.390, 0.348, 0.32), (0.410, 0.338, 0.34), (0.430, 0.338, 0.35),
        (0.450, 0.348, 0.34), (0.430, 0.358, 0.33), (0.410, 0.358, 0.33)
    ],
    "reye": [
        (0.530, 0.342, 0.34), (0.550, 0.328, 0.35), (0.570, 0.328, 0.34),
        (0.590, 0.332, 0.32), (0.570, 0.342, 0.33), (0.550, 0.342, 0.33)
    ],
    "nose_bridge": [
        (0.492, 0.328, 0.40), (0.492, 0.355, 0.45), (0.492, 0.385, 0.50), (0.492, 0.412, 0.55)
    ],
    "nose_tip": [
        (0.465, 0.420, 0.48), (0.480, 0.426, 0.54), (0.492, 0.428, 0.58),
        (0.505, 0.426, 0.54), (0.520, 0.418, 0.48)
    ],
    "mouth_outer": [
        (0.435, 0.468, 0.35), (0.460, 0.458, 0.38), (0.492, 0.458, 0.42), # Upper outer
        (0.525, 0.455, 0.38), (0.550, 0.462, 0.35),
        (0.525, 0.478, 0.38), (0.492, 0.482, 0.42), (0.460, 0.478, 0.38)  # Lower outer
    ],
    "mouth_inner": [
        (0.445, 0.468, 0.36), (0.470, 0.465, 0.39), (0.492, 0.465, 0.41),
        (0.515, 0.463, 0.39), (0.540, 0.463, 0.36),
        (0.515, 0.470, 0.39), (0.492, 0.472, 0.41), (0.470, 0.470, 0.39)
    ],
    "forehead": [
        (0.350, 0.260, 0.18), (0.410, 0.230, 0.25), (0.492, 0.220, 0.30),
        (0.570, 0.220, 0.25), (0.630, 0.240, 0.18)
    ],
    "cheeks": [
        (0.360, 0.420, 0.22), (0.625, 0.405, 0.22)
    ]
}


class BihansaHologramWidget(QWidget):
    """Animated pink neural hologram visualizer with landmark-aligned 2.5D face mesh."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self._state = "IDLE"
        self._effects_enabled = True
        self._voice_reactive = True
        self._energy = 0.0
        self._target_energy = 0.0
        self._current_viseme = ""
        self._started = time.monotonic()
        self._scan = 0.0
        self._particles = [
            (random.random(), random.random(), random.uniform(0.7, 2.2),
             random.uniform(0.15, 0.8), random.random() * math.tau)
            for _ in range(70)
        ]

        assets_dir = Path(__file__).resolve().parents[2] / "assets"
        self._portrait_path = assets_dir / "bihansa_reference.png"
        self._portrait = QPixmap(str(self._portrait_path))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state: str):
        self._state = str(state or "IDLE").upper()
        self.update()

    def get_state(self) -> str:
        return self._state

    def set_effects_enabled(self, enabled: bool):
        self._effects_enabled = bool(enabled)
        self.update()

    def set_voice_reactive(self, enabled: bool):
        self._voice_reactive = bool(enabled)
        if not self._voice_reactive:
            self._energy = 0.0
            self._target_energy = 0.0
        self.update()

    def set_audio_energy(self, level: float):
        try:
            self._target_energy = max(0.0, min(1.0, float(level))) if self._voice_reactive else 0.0
        except (TypeError, ValueError):
            self._target_energy = 0.0

    def set_viseme(self, viseme: str):
        """Extension point for phoneme/viseme driven audio sync."""
        self._current_viseme = str(viseme or "").lower()
        self.update()

    def _tick(self):
        self._energy += (self._target_energy - self._energy) * 0.22
        self._scan = (self._scan + (0.012 if self._state == "SPEAKING" else 0.006)) % 1.0
        self.update()

    def _project_25d(self, pt: Tuple[float, float, float], rect: QRectF, yaw: float, pitch: float) -> QPointF:
        """Projects a normalized (x, y, z) landmark into 2.5D widget coordinates."""
        nx, ny, nz = pt

        # Apply 2.5D parallax shift based on depth z
        dx = yaw * (nz - 0.3) * 0.03
        dy = pitch * (nz - 0.3) * 0.02

        px = rect.x() + (nx + dx) * rect.width()
        py = rect.y() + (ny + dy) * rect.height()
        return QPointF(px, py)

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

        # Subtle 2.5D head animation oscillation
        yaw = math.sin(t * 1.2) * 0.8 if self._effects_enabled else 0.0
        pitch = math.cos(t * 0.9) * 0.5 if self._effects_enabled else 0.0

        # Radial glow rings & HUD arcs
        if self._effects_enabled:
            p.setPen(Qt.PenStyle.NoPen)
            for radius, alpha in ((min(w, h) * .39, 12), (min(w, h) * .32, 10)):
                p.setBrush(QColor(255, 45, 190, alpha))
                p.drawEllipse(QPointF(cx, cy), radius, radius * 1.12)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 79, 200, 150), 1.1))
            p.drawEllipse(QPointF(cx, cy), min(w, h) * .37, min(w, h) * .43)
            p.setPen(QPen(QColor(255, 155, 232, 95), 1, Qt.PenStyle.DashLine))
            p.drawEllipse(QPointF(cx, cy), min(w, h) * .42, min(w, h) * .47)
            arc = QRectF(cx - min(w, h) * .43, cy - min(w, h) * .45,
                         min(w, h) * .86, min(w, h) * .90)
            p.setPen(QPen(hot, 2.0))
            p.drawArc(arc, int((t * 24 % 360) * 16), 112 * 16)
            p.setPen(QPen(pink, 1.5))
            p.drawArc(arc.adjusted(9, 9, -9, -9), int((-t * 31 % 360) * 16), 72 * 16)

        # Portrait dimensions & rect
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
            face_rect = QRectF(px, py, scaled.width(), scaled.height())

            # Subtle pink halo behind portrait frame
            p.setPen(QPen(QColor(255, 79, 200, 130), 2))
            p.setBrush(QColor(30, 7, 31, 190))
            p.drawRoundedRect(target, 18, 18)
            p.drawPixmap(int(px), int(py), scaled)

            p.save()
            p.setClipRect(face_rect)
            if self._effects_enabled:
                p.fillRect(face_rect, QColor(255, 45, 190, 20))
                scan_y = py + self._scan * scaled.height()
                p.setPen(QPen(QColor(255, 155, 232, 135), 1.2))
                p.drawLine(QPointF(px, scan_y), QPointF(px + scaled.width(), scan_y))
                p.setPen(QPen(QColor(255, 105, 220, 18), 1))
                for yy in range(int(py), int(py + scaled.height()), 6):
                    p.drawLine(int(px), yy, int(px + scaled.width()), yy)

            # Draw landmark-aligned 2.5D facial wireframe mesh
            if self._effects_enabled:
                self._draw_neural_face_mesh(p, face_rect, yaw, pitch)

            p.restore()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(hot, 1.2))
            p.drawRoundedRect(target, 18, 18)
        else:
            # Fallback when image is missing
            p.setPen(QPen(pink, 1.5))
            p.drawRoundedRect(target, 18, 18)
            fallback_rect = QRectF(margin_x, top, portrait_w, portrait_h)
            if self._effects_enabled:
                self._draw_neural_face_mesh(p, fallback_rect, yaw, pitch)
            p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
            p.setPen(QPen(hot, 1))
            p.drawText(target, Qt.AlignmentFlag.AlignCenter,
                       "BIHANSA REFERENCE IMAGE NOT FOUND\n[FALLBACK NEURAL MESH ACTIVE]")

        # Neural particles drift around portrait
        p.setPen(Qt.PenStyle.NoPen)
        for nx, ny, size, speed, phase in (self._particles if self._effects_enabled else []):
            drift = math.sin(t * speed + phase) * 0.018
            x = (nx + drift) * w
            y = (ny + math.cos(t * speed + phase) * .012) * h
            alpha = int(85 + 140 * (0.5 + 0.5 * math.sin(t * 1.8 + phase)))
            p.setBrush(QColor(255, 105, 220, alpha))
            p.drawEllipse(QPointF(x, y), size + self._energy, size + self._energy)

        # Status text footer
        p.setPen(QPen(cyan if self._state == "LISTENING" else hot, 1))
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        label = "BIHANSA // LISTENING" if self._state == "LISTENING" else (
            "BIHANSA // SPEAKING" if self._state == "SPEAKING" else
            "BIHANSA // NEURAL LINK")
        p.drawText(QRectF(0, h * .88, w, 22), Qt.AlignmentFlag.AlignCenter, label)
        p.setPen(QPen(QColor(255, 79, 200, 170), 1))
        p.drawText(QRectF(0, h * .93, w, 18), Qt.AlignmentFlag.AlignCenter,
                   "2.5D LANDMARK NEURAL HOLOGRAM  •  " + self._state)
        p.end()

    def _draw_neural_face_mesh(self, p: QPainter, rect: QRectF, yaw: float, pitch: float):
        """Draws feature-aligned wireframe and nodes across eyes, nose, lips, jawline, and forehead."""
        # Pens and brushes
        wire_pen = QPen(QColor(255, 125, 225, 110), 0.9)
        feature_pen = QPen(QColor(255, 180, 240, 160), 1.2)
        node_brush = QBrush(QColor(255, 210, 250, 190))
        eye_pupil_brush = QBrush(QColor(103, 234, 255, 220))

        # Project landmark points
        projected: Dict[str, List[QPointF]] = {}
        for group_name, pts in LANDMARK_GROUPS.items():
            proj_pts = []
            for pt in pts:
                nx, ny, nz = pt
                # Audio reactivity displacement on lips
                if "mouth" in group_name and ("lower" in group_name or ny > 0.465):
                    disp = self._energy * 0.018
                    if self._current_viseme in ("a", "o", "u", "open"):
                        disp += 0.012
                    ny = ny + disp
                proj_pts.append(self._project_25d((nx, ny, nz), rect, yaw, pitch))
            projected[group_name] = proj_pts

        # 1. Jawline contour path
        p.setPen(feature_pen)
        jaw_pts = projected["jaw"]
        for i in range(len(jaw_pts) - 1):
            p.drawLine(jaw_pts[i], jaw_pts[i + 1])

        # 2. Eyebrows
        for brow_key in ("lbrow", "rbrow"):
            b_pts = projected[brow_key]
            for i in range(len(b_pts) - 1):
                p.drawLine(b_pts[i], b_pts[i + 1])

        # 3. Eye contours & Pupil center highlight
        for eye_key in ("leye", "reye"):
            e_pts = projected[eye_key]
            for i in range(len(e_pts)):
                p.drawLine(e_pts[i], e_pts[(i + 1) % len(e_pts)])
            # Pupil highlight center
            ecx = sum(pt.x() for pt in e_pts) / len(e_pts)
            ecy = sum(pt.y() for pt in e_pts) / len(e_pts)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(eye_pupil_brush)
            p.drawEllipse(QPointF(ecx, ecy), 2.5 + self._energy * 1.5, 2.5 + self._energy * 1.5)

        # 4. Nose bridge and tip
        p.setPen(wire_pen)
        nb_pts = projected["nose_bridge"]
        for i in range(len(nb_pts) - 1):
            p.drawLine(nb_pts[i], nb_pts[i + 1])
        nt_pts = projected["nose_tip"]
        for i in range(len(nt_pts) - 1):
            p.drawLine(nt_pts[i], nt_pts[i + 1])
        p.drawLine(nb_pts[-1], nt_pts[2]) # Connect bridge to tip center

        # 5. Lips outer and inner
        p.setPen(feature_pen)
        mo_pts = projected["mouth_outer"]
        for i in range(len(mo_pts)):
            p.drawLine(mo_pts[i], mo_pts[(i + 1) % len(mo_pts)])
        mi_pts = projected["mouth_inner"]
        for i in range(len(mi_pts)):
            p.drawLine(mi_pts[i], mi_pts[(i + 1) % len(mi_pts)])

        # 6. Connecting neural mesh lines (Cheek, Nose-to-Eye, Jaw-to-Cheek)
        p.setPen(wire_pen)
        # Connect inner eye corners to nose bridge top
        p.drawLine(projected["leye"][3], nb_pts[0])
        p.drawLine(projected["reye"][0], nb_pts[0])
        # Connect outer eye corners to cheeks
        p.drawLine(projected["leye"][0], projected["cheeks"][0])
        p.drawLine(projected["reye"][3], projected["cheeks"][1])
        # Connect nose tip to lip corners
        p.drawLine(nt_pts[0], mo_pts[0])
        p.drawLine(nt_pts[4], mo_pts[4])
        # Connect chin to mouth center lower
        p.drawLine(jaw_pts[5], mo_pts[6])

        # 7. Draw feature node dots
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(node_brush)
        for g_pts in projected.values():
            for pt in g_pts:
                p.drawEllipse(pt, 1.6, 1.6)
