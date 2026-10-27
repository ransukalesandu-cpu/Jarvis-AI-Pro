"""
Procedural neural wireframe face for the JARVIS holographic HUD.

The default JARVIS visual is a human-like 3D facial surface (not a sphere),
with a triangulated neural mesh, facial feature contours, HUD scan lines and
audio-reactive glow. The existing state, audio-energy and signal interfaces
are preserved for HUDMainWindow / VisualizerBridge compatibility.
"""

from __future__ import annotations

import math
import os
import random
import time
from typing import List, Tuple

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
    """Animated JARVIS-style cyan neural face rendered entirely with vectors."""

    sig_state_changed = pyqtSignal(str)

    COLOR_BG = QColor("#050b13")
    COLOR_CYAN = QColor("#42eaff")
    COLOR_CYAN_HOT = QColor("#c8fbff")
    COLOR_CYAN_DIM = QColor("#087f9c")
    COLOR_VIOLET = QColor("#8b6cff")
    COLOR_RED = QColor("#ff365f")
    COLOR_GREEN = QColor("#00e676")
    COLOR_AMBER = QColor("#ffbf47")

    # Geometry is a fine grid sampled over a parametric human-like face.
    FACE_COLUMNS = 23
    FACE_ROWS = 29

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._state = "IDLE"
        self._audio_energy = 0.0
        self._target_energy = 0.0

        self._rot_x = 0.0
        self._rot_y = 0.0
        self._rot_z = 0.0
        self._start_time = time.monotonic()
        self._glitch_intensity = 0.0
        self._scan_phase = 0.0

        self._vertices: List[Tuple[float, float, float]] = []
        self._edges: List[Tuple[int, int]] = []
        self._particles: List[dict] = []
        self._build_mesh_geometry()
        self._build_particles()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(20)

    @staticmethod
    def _gauss(u: float, v: float, uc: float, vc: float,
               su: float, sv: float) -> float:
        return math.exp(-((u - uc) / su) ** 2 - ((v - vc) / sv) ** 2)

    @classmethod
    def _face_surface(cls, u: float, v: float) -> Tuple[float, float, float]:
        """Return a point on the stylized face surface for normalized u/v in [-1, 1]."""
        # A tapered jaw, broad cheek area and slightly narrower forehead create
        # a recognizable front-view head silhouette without using a portrait.
        jaw_blend = max(0.0, min(1.0, (v + 1.0) / 0.82))
        jaw_blend = jaw_blend * jaw_blend * (3.0 - 2.0 * jaw_blend)
        jaw_width = 0.47 + 0.53 * jaw_blend
        forehead_taper = 1.0 - 0.085 * max(0.0, (v - 0.53) / 0.47)
        half_width = 0.615 * jaw_width * forehead_taper
        x = u * half_width
        y = v * 0.96

        side_rounding = math.sqrt(max(0.0, 1.0 - u * u))
        vertical_rounding = math.sqrt(max(0.0, 1.0 - 0.72 * v * v))
        z = 0.035 + 0.125 * side_rounding * vertical_rounding

        # Cheekbones and temples provide lateral facial volume.
        z += 0.065 * (cls._gauss(u, v, -0.52, -0.12, 0.24, 0.22)
                      + cls._gauss(u, v, 0.52, -0.12, 0.24, 0.22))
        z += 0.028 * (cls._gauss(u, v, -0.80, 0.30, 0.16, 0.35)
                      + cls._gauss(u, v, 0.80, 0.30, 0.16, 0.35))

        # Brow ridges and eye sockets are deliberately different in depth.
        z += 0.055 * (cls._gauss(u, v, -0.34, 0.285, 0.22, 0.075)
                      + cls._gauss(u, v, 0.34, 0.285, 0.22, 0.075))
        z -= 0.050 * (cls._gauss(u, v, -0.34, 0.18, 0.18, 0.105)
                      + cls._gauss(u, v, 0.34, 0.18, 0.18, 0.105))

        # Nose bridge, tip and nostril wings.
        z += 0.090 * cls._gauss(u, v, 0.0, 0.035, 0.078, 0.24)
        z += 0.145 * cls._gauss(u, v, 0.0, -0.135, 0.105, 0.105)
        z += 0.035 * (cls._gauss(u, v, -0.13, -0.16, 0.065, 0.055)
                      + cls._gauss(u, v, 0.13, -0.16, 0.065, 0.055))

        # Philtrum, lips and chin pad finish the lower face.
        z += 0.020 * cls._gauss(u, v, 0.0, -0.285, 0.07, 0.075)
        z += 0.045 * cls._gauss(u, v, 0.0, -0.405, 0.23, 0.075)
        z += 0.060 * cls._gauss(u, v, 0.0, -0.72, 0.27, 0.15)
        return x, y, z

    def _build_mesh_geometry(self):
        """Create connected quads and alternating diagonals over the face surface."""
        vertices: List[Tuple[float, float, float]] = []
        edges: List[Tuple[int, int]] = []
        cols, rows = self.FACE_COLUMNS, self.FACE_ROWS

        for row in range(rows):
            v = -0.985 + 1.97 * row / (rows - 1)
            for col in range(cols):
                u = -0.985 + 1.97 * col / (cols - 1)
                vertices.append(self._face_surface(u, v))

        for row in range(rows):
            for col in range(cols):
                idx = row * cols + col
                if col + 1 < cols:
                    edges.append((idx, idx + 1))
                if row + 1 < rows:
                    edges.append((idx, idx + cols))
                    if col + 1 < cols:
                        # Alternating diagonal links create a neural triangulation.
                        if (row + col) % 2 == 0:
                            edges.append((idx, idx + cols + 1))
                        else:
                            edges.append((idx + 1, idx + cols))
        self._vertices = vertices
        self._edges = edges

    def _build_particles(self):
        """Create deterministic, floating diagnostic particles around the face."""
        rng = random.Random(41)
        self._particles = [
            {
                "radius": rng.uniform(1.0, 2.8),
                "angle": rng.uniform(0.0, math.tau),
                "speed": rng.uniform(0.25, 0.95),
                "orbit": rng.uniform(0.31, 0.48),
                "y": rng.uniform(-0.42, 0.42),
                "phase": rng.uniform(0.0, math.tau),
            }
            for _ in range(54)
        ]

    @pyqtSlot(float)
    def set_audio_energy(self, level: float):
        """Accept normalized microphone/playback energy (0.0–1.0)."""
        try:
            self._target_energy = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            self._target_energy = 0.0

    @pyqtSlot(str)
    def set_state(self, state: str):
        """Switch visualizer state without changing the existing HUD signal contract."""
        st = str(state or "IDLE").upper()
        if st != self._state:
            self._state = st
            self.sig_state_changed.emit(st)

    def get_state(self) -> str:
        return self._state

    def _step(self):
        elapsed = time.monotonic() - self._start_time
        self._audio_energy += (self._target_energy - self._audio_energy) * 0.24

        if self._state == "THINKING":
            self._rot_y += 0.024
            self._rot_x = math.sin(elapsed * 0.8) * 0.10
            self._rot_z = math.sin(elapsed * 0.33) * 0.018
        elif self._state == "PRIVACY_LOCK":
            self._rot_y += 0.004
            self._rot_x = 0.0
            self._rot_z = 0.0
            self._glitch_intensity = random.uniform(0.04, 0.16)
        else:
            self._rot_y = math.sin(elapsed * 0.23) * 0.12
            self._rot_x = math.sin(elapsed * 0.37) * 0.035
            self._rot_z = math.sin(elapsed * 0.19) * 0.012
            self._glitch_intensity = 0.0

        scan_rate = 0.020 if self._state == "SPEAKING" else 0.010
        self._scan_phase = (self._scan_phase + scan_rate + self._audio_energy * 0.008) % 1.0
        for particle in self._particles:
            particle["angle"] += particle["speed"] * (1.8 if self._state == "THINKING" else 1.0) * 0.02
        self.update()

    def _project(self, point: Tuple[float, float, float], cx: float, cy: float,
                 scale: float) -> Tuple[QPointF, float]:
        x, y, z = point
        # Small, temporary jitter gives the privacy lock a controlled signal-glitch effect.
        if self._glitch_intensity > 0.0:
            x += random.uniform(-self._glitch_intensity, self._glitch_intensity) * 0.10
            y += random.uniform(-self._glitch_intensity, self._glitch_intensity) * 0.10

        cyaw, syaw = math.cos(self._rot_y), math.sin(self._rot_y)
        cpitch, spitch = math.cos(self._rot_x), math.sin(self._rot_x)
        croll, sroll = math.cos(self._rot_z), math.sin(self._rot_z)

        xr = x * cyaw + z * syaw
        zr = -x * syaw + z * cyaw
        yr = y * cpitch - zr * spitch
        zr = y * spitch + zr * cpitch
        xr, yr = xr * croll - yr * sroll, xr * sroll + yr * croll

        perspective = 1.0 / max(0.62, 1.0 + zr * 0.14)
        return QPointF(cx + xr * scale * perspective,
                       cy - yr * scale * perspective), zr

    def _project_uv(self, u: float, v: float, cx: float, cy: float,
                    scale: float) -> QPointF:
        pt, _depth = self._project(self._face_surface(u, v), cx, cy, scale)
        return pt

    def _draw_curve(self, painter: QPainter, points: List[Tuple[float, float]],
                    color: QColor, width: float, cx: float, cy: float,
                    scale: float, close: bool = False):
        if len(points) < 2:
            return
        path = QPainterPath()
        for index, (u, v) in enumerate(points):
            pt = self._project_uv(u, v, cx, cy, scale)
            if index == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        if close:
            path.closeSubpath()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)

    def _draw_face_features(self, painter: QPainter, cx: float, cy: float,
                            scale: float, primary: QColor, hot: QColor,
                            elapsed: float):
        """Draw the facial landmarks over the mesh so it reads as a face at a glance."""
        # Outer facial contour.
        outline_left = [(-0.985, -0.78 + i * 1.63 / 40) for i in range(41)]
        outline_right = [(0.985, -0.78 + i * 1.63 / 40) for i in reversed(range(41))]
        self._draw_curve(painter, outline_left + outline_right, primary, 1.7,
                         cx, cy, scale, close=False)

        for eye_center in (-0.34, 0.34):
            eye = [
                (eye_center + 0.205 * math.cos(a),
                 0.18 + 0.070 * math.sin(a) * (0.78 + 0.22 * abs(math.cos(a))))
                for a in [math.tau * i / 48 for i in range(49)]
            ]
            brow = [
                (eye_center + 0.235 * k / 24,
                 0.292 + 0.040 * math.sin(math.pi * k / 24))
                for k in range(25)
            ]
            self._draw_curve(painter, eye, hot, 1.35, cx, cy, scale, close=True)
            self._draw_curve(painter, brow, primary, 1.45, cx, cy, scale)

            # Iris, pupil and a subtle scan pulse keep the eyes visibly synthetic.
            iris_center = self._project_uv(eye_center, 0.18, cx, cy, scale)
            iris_radius = scale * (0.033 + 0.004 * self._audio_energy)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(hot, 1.0))
            painter.drawEllipse(iris_center, iris_radius, iris_radius * 0.82)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(hot.red(), hot.green(), hot.blue(), 220))
            pupil_size = max(1.4, scale * 0.010)
            painter.drawEllipse(iris_center, pupil_size, pupil_size)

        # Nose bridge, tip and small wings.
        nose = [(0.0, 0.30), (-0.018, 0.10), (-0.045, -0.065),
                (-0.105, -0.16), (-0.070, -0.195), (0.0, -0.205),
                (0.070, -0.195), (0.105, -0.16), (0.045, -0.065),
                (0.018, 0.10), (0.0, 0.30)]
        self._draw_curve(painter, nose, hot, 1.20, cx, cy, scale)
        for side in (-1, 1):
            nostril = [(side * 0.055, -0.172), (side * 0.095, -0.185),
                       (side * 0.135, -0.166)]
            self._draw_curve(painter, nostril, primary, 1.0, cx, cy, scale)

        # Upper/lower lip and a live, audio-reactive mouth opening.
        energy = self._audio_energy if self._state == "SPEAKING" else self._audio_energy * 0.10
        mouth_open = min(0.105, energy * (0.045 + 0.060 * (0.5 + 0.5 * math.sin(elapsed * 16.0))))
        upper_lip = [
            (0.225 * math.cos(math.pi * i / 36),
             -0.395 + 0.025 * math.sin(math.pi * i / 36)
             + 0.009 * math.sin(math.pi * i / 18))
            for i in range(37)
        ]
        lower_lip = [
            (0.225 * math.cos(math.pi + math.pi * i / 36),
             -0.395 - mouth_open * math.sin(math.pi * i / 36))
            for i in range(37)
        ]
        self._draw_curve(painter, upper_lip, hot, 1.25, cx, cy, scale)
        self._draw_curve(painter, lower_lip, primary, 1.1, cx, cy, scale)

        if mouth_open > 0.010:
            mouth_shape = [
                (0.185 * math.cos(a), -0.397 + mouth_open * math.sin(a))
                for a in [math.tau * i / 32 for i in range(33)]
            ]
            self._draw_curve(painter, mouth_shape,
                             QColor(primary.red(), primary.green(), primary.blue(), 190),
                             0.95, cx, cy, scale, close=True)

        # Quiet center axis and cheek/temple reference traces mimic technical facial mapping.
        guide = QColor(primary.red(), primary.green(), primary.blue(), 70)
        self._draw_curve(painter, [(0.0, 0.78), (0.0, 0.38), (0.0, 0.28)],
                         guide, 0.65, cx, cy, scale)
        for side in (-1, 1):
            cheek = [(side * 0.37, -0.04), (side * 0.53, -0.13),
                     (side * 0.62, -0.28), (side * 0.45, -0.43)]
            self._draw_curve(painter, cheek, guide, 0.8, cx, cy, scale)

    def _draw_hud_frame(self, painter: QPainter, width: float, height: float,
                        cx: float, cy: float, scale: float, primary: QColor,
                        elapsed: float):
        """Draw restrained technical brackets, orbit arcs and the scanning beam."""
        if width < 1 or height < 1:
            return
        size = min(width, height)
        faint = QColor(primary.red(), primary.green(), primary.blue(), 46)
        soft = QColor(primary.red(), primary.green(), primary.blue(), 82)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(faint, 0.8))
        painter.drawEllipse(QPointF(cx, cy - height * 0.015), size * 0.395, size * 0.425)
        rect = QRectF(cx - size * 0.355, cy - size * 0.445, size * 0.710, size * 0.875)
        painter.setPen(QPen(soft, 0.85, Qt.PenStyle.DashLine))
        painter.drawArc(rect, int((elapsed * 22 % 360) * 16), 72 * 16)
        painter.drawArc(rect.adjusted(8, 8, -8, -8),
                        int((-elapsed * 29 % 360) * 16), 52 * 16)

        # Corner brackets mark the face scan envelope.
        left, right = width * 0.15, width * 0.85
        top, bottom = height * 0.075, height * 0.845
        bracket = min(18.0, size * 0.055)
        painter.setPen(QPen(primary, 1.0))
        for x, y, sx, sy in (
            (left, top, 1, 1), (right, top, -1, 1),
            (left, bottom, 1, -1), (right, bottom, -1, -1),
        ):
            painter.drawLine(QPointF(x, y), QPointF(x + sx * bracket, y))
            painter.drawLine(QPointF(x, y), QPointF(x, y + sy * bracket))

        # Very light crosshair ticks add a HUD readout feel without obscuring the face.
        painter.setPen(QPen(faint, 0.75))
        for x in (width * 0.205, width * 0.795):
            for factor in (0.23, 0.35, 0.47, 0.59, 0.71):
                y = height * factor
                painter.drawLine(QPointF(x, y), QPointF(x + (5 if x < cx else -5), y))

        scan_y = height * 0.085 + self._scan_phase * height * 0.74
        scan_alpha = 72 if self._state != "SPEAKING" else 125
        scan_color = QColor(primary.red(), primary.green(), primary.blue(), scan_alpha)
        painter.setPen(QPen(scan_color, 1.0))
        painter.drawLine(QPointF(width * 0.18, scan_y), QPointF(width * 0.82, scan_y))
        painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 30), 3.0))
        painter.drawLine(QPointF(width * 0.18, scan_y), QPointF(width * 0.82, scan_y))

    def paintEvent(self, event):
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        # No opaque backing fill: the room/task cards remain visible through the emissive mesh.

        width, height = float(self.width()), float(self.height())
        cx, cy = width * 0.5, height * 0.455
        elapsed = time.monotonic() - self._start_time

        if self._state == "THINKING":
            pulse = 1.0 + 0.018 * math.sin(elapsed * 5.6)
            primary, secondary = self.COLOR_VIOLET, QColor("#d2c5ff")
        elif self._state == "PRIVACY_LOCK":
            pulse = 0.985
            primary, secondary = self.COLOR_RED, QColor("#ff9bad")
        elif self._state == "LISTENING":
            pulse = 1.0 + self._audio_energy * 0.055
            primary, secondary = self.COLOR_CYAN, self.COLOR_CYAN_HOT
        elif self._state == "SPEAKING":
            pulse = 1.0 + self._audio_energy * 0.035 + 0.012 * math.sin(elapsed * 12.0)
            primary, secondary = self.COLOR_CYAN, self.COLOR_CYAN_HOT
        else:
            pulse = 1.0 + 0.012 * math.sin(elapsed * 1.4)
            primary, secondary = self.COLOR_CYAN, self.COLOR_CYAN_DIM

        scale = min(width, height) * 0.48 * pulse
        self._draw_hud_frame(painter, width, height, cx, cy, scale, primary, elapsed)

        # Orbital data particles are kept subtle; thinking/speaking increases their activity.
        if self._state in ("THINKING", "SPEAKING"):
            painter.setPen(Qt.PenStyle.NoPen)
            for particle in self._particles:
                orbit = min(width, height) * particle["orbit"]
                angle = particle["angle"] + particle["phase"]
                px = cx + math.cos(angle) * orbit
                py = cy + math.sin(angle) * orbit * 0.72 + particle["y"] * min(width, height) * 0.20
                alpha = int(36 + 95 * (0.5 + 0.5 * math.sin(elapsed * 2.0 + particle["phase"])))
                color = self.COLOR_VIOLET if self._state == "THINKING" else self.COLOR_CYAN
                painter.setBrush(QColor(color.red(), color.green(), color.blue(), alpha))
                radius = particle["radius"] * (1.35 if self._state == "THINKING" else 1.0)
                painter.drawEllipse(QPointF(px, py), radius, radius)

        projected: List[Tuple[QPointF, float]] = [
            self._project(vertex, cx, cy, scale) for vertex in self._vertices
        ]

        # Three-dimensional neural mesh with perspective-based depth fading.
        base_alpha = 118 if self._state == "IDLE" else 148
        if self._state == "LISTENING":
            base_alpha = 150 + int(self._audio_energy * 60)
        elif self._state == "SPEAKING":
            base_alpha = 148 + int(self._audio_energy * 75)
        for idx1, idx2 in self._edges:
            p1, z1 = projected[idx1]
            p2, z2 = projected[idx2]
            depth_alpha = int(max(35, min(225, base_alpha + (z1 + z2) * 27)))
            edge = QColor(primary.red(), primary.green(), primary.blue(), depth_alpha)
            painter.setPen(QPen(edge, 0.72 if self._state == "IDLE" else 0.88))
            painter.drawLine(p1, p2)

        # Pulsing neural nodes highlight the mesh without turning it into a dotted sphere.
        painter.setPen(Qt.PenStyle.NoPen)
        columns = self.FACE_COLUMNS
        for index, (point, depth) in enumerate(projected):
            row, col = divmod(index, columns)
            if row % 2 or col % 2:
                continue
            phase = elapsed * 2.0 + row * 0.39 + col * 0.52
            pulse_node = 0.5 + 0.5 * math.sin(phase)
            alpha = int(80 + pulse_node * 130)
            if self._state in ("LISTENING", "SPEAKING"):
                alpha = min(255, alpha + int(self._audio_energy * 45))
            color = QColor(secondary.red(), secondary.green(), secondary.blue(), alpha)
            painter.setBrush(color)
            radius = 1.0 + pulse_node * 1.05 + self._audio_energy * (
                1.25 if self._state in ("LISTENING", "SPEAKING") else 0.35
            )
            painter.drawEllipse(point, radius, radius)

        self._draw_face_features(painter, cx, cy, scale, primary, secondary, elapsed)

        # Subtle audio pulse rings near the temples.
        if self._state in ("LISTENING", "SPEAKING") and self._audio_energy > 0.035:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            glow_alpha = int(40 + self._audio_energy * 100)
            painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), glow_alpha), 1.0))
            ring = scale * (0.77 + self._audio_energy * 0.10)
            painter.drawArc(QRectF(cx - ring, cy - ring * 0.55, ring * 2, ring * 1.1),
                            28 * 16, 64 * 16)
            painter.drawArc(QRectF(cx - ring, cy - ring * 0.55, ring * 2, ring * 1.1),
                            208 * 16, 64 * 16)

        if self._state == "PRIVACY_LOCK":
            self._draw_lockdown_overlay(painter, width, height, cx, cy)

        # State indicators remain explicit and compatible with the existing HUD.
        painter.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        painter.setPen(QPen(primary, 1))
        label = {
            "LISTENING": "J.A.R.V.I.S.  //  LISTENING",
            "THINKING": "J.A.R.V.I.S.  //  PROCESSING",
            "SPEAKING": "J.A.R.V.I.S.  //  SPEAKING",
            "PRIVACY_LOCK": "J.A.R.V.I.S.  //  PRIVACY LOCK",
        }.get(self._state, "J.A.R.V.I.S.  //  NEURAL LINK ONLINE")
        painter.drawText(QRectF(0, height * 0.895, width, 18),
                         Qt.AlignmentFlag.AlignCenter, label)
        painter.setFont(QFont("Courier New", 7, QFont.Weight.Normal))
        painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 130), 1))
        painter.drawText(QRectF(0, height * 0.935, width, 16),
                         Qt.AlignmentFlag.AlignCenter, "HOLOGRAPHIC FACE MESH  /  LIVE SIGNAL")

        painter.end()

    def _draw_lockdown_overlay(self, painter: QPainter, width: float, height: float,
                               cx: float, cy: float):
        """Display a clear security-lock overlay while preserving the red face state."""
        painter.save()
        painter.fillRect(self.rect(), QColor(10, 0, 4, 150))

        shield = QPainterPath()
        sw, sh = min(64.0, width * 0.20), min(72.0, height * 0.23)
        shield.moveTo(cx, cy - sh / 2.0)
        shield.lineTo(cx + sw / 2.0, cy - sh / 3.0)
        shield.lineTo(cx + sw / 2.0, cy + sh / 4.0)
        shield.lineTo(cx, cy + sh / 2.0)
        shield.lineTo(cx - sw / 2.0, cy + sh / 4.0)
        shield.lineTo(cx - sw / 2.0, cy - sh / 3.0)
        shield.closeSubpath()

        painter.setPen(QPen(self.COLOR_RED, 2.5))
        painter.setBrush(QBrush(QColor(183, 28, 58, 120)))
        painter.drawPath(shield)

        painter.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        painter.setPen(QPen(self.COLOR_RED, 1))
        painter.drawText(QRectF(0, cy + sh / 2.0 + 12, width, 25),
                         Qt.AlignmentFlag.AlignCenter, "SYSTEM PRIVACY LOCK ENGAGED")
        painter.setFont(QFont("Courier New", 8, QFont.Weight.Normal))
        painter.setPen(QPen(QColor("#ff9bad"), 1))
        painter.drawText(QRectF(0, cy + sh / 2.0 + 35, width, 22),
                         Qt.AlignmentFlag.AlignCenter, "MIC MUTED  /  PIN REQUIRED")
        painter.restore()
