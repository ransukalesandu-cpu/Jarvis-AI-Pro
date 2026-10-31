"""Image-free procedural neural face hologram for JARVIS AI Pro.

The face geometry is generated from mathematical surface functions at runtime.
No portrait, texture, model download, or external image asset is required.
"""
from __future__ import annotations

import math
import random
import time
from typing import Dict, List, Tuple

from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget


class BihansaHologramWidget(QWidget):
    """Procedurally generated pink neural face with audio-reactive mouth motion."""

    sig_viseme_changed = pyqtSignal(str, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        # Keep the animated Bihansa hologram transparent over the existing HUD.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._reduced_motion = False
        self._glow_intensity = 1.0
        self._animation_speed = 1.0
        self._state = "IDLE"
        self._effects_enabled = True
        self._voice_reactive = True
        self._audio_energy = 0.0
        self._target_energy = 0.0
        self._yaw = self._pitch = self._roll = 0.0
        self._breath_scale = 1.0
        self._scan = 0.0
        self._start_time = time.monotonic()
        self._blink = 0.0
        self._next_blink = 2.7
        self._viseme_weights: Dict[str, float] = {
            "aa": 0.0, "ee": 0.0, "oh": 0.0, "ou": 0.0, "ch": 0.0, "m": 0.0
        }
        rng = random.Random(17)
        self._particles = [
            (rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0),
             rng.uniform(0.7, 2.2), rng.uniform(0.2, 1.0), rng.random() * math.tau)
            for _ in range(74)
        ]
        self._frame_interval = 33
        self._particle_budget = 1.0
        self._performance_glow_scale = 1.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self._frame_interval)

    def _visible_particle_count(self) -> int:
        """Return the particle count allowed by the current responsive budget."""
        return max(0, min(len(self._particles), int(round(len(self._particles) * self._particle_budget))))

    def set_performance_budget(
        self, frame_interval_ms: int, particle_scale: float, glow_scale: float
    ) -> None:
        """Adapt animation cadence and visual effects to the available HUD space."""
        interval = max(16, min(200, int(frame_interval_ms)))
        if interval != self._frame_interval:
            self._frame_interval = interval
            self._timer.setInterval(interval)
        self._particle_budget = max(0.0, min(1.0, float(particle_scale)))
        self._performance_glow_scale = max(0.2, min(1.0, float(glow_scale)))
        self.update()

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
            self._target_energy = self._audio_energy = 0.0
        self.update()

    @pyqtSlot(float)
    def set_audio_energy(self, level: float):
        """Feed normalized playback/microphone energy (0.0–1.0) from the HUD bridge."""
        try:
            self._target_energy = max(0.0, min(1.0, float(level))) if self._voice_reactive else 0.0
        except (TypeError, ValueError):
            self._target_energy = 0.0

    @pyqtSlot(str, float)
    def set_viseme(self, viseme_id: str, weight: float = 1.0):
        """Optional phoneme/viseme input for more precise lip-sync integrations."""
        vid = str(viseme_id or "").lower()
        if vid in self._viseme_weights:
            self._viseme_weights[vid] = max(0.0, min(1.0, float(weight)))
            self.sig_viseme_changed.emit(vid, self._viseme_weights[vid])
            self.update()

    def _tick(self):
        elapsed = time.monotonic() - self._start_time
        t = 0.0 if self._reduced_motion else elapsed * self._animation_speed
        self._audio_energy += (self._target_energy - self._audio_energy) * 0.24
        if self._state == "THINKING":
            self._yaw, self._pitch, self._roll = math.sin(t * 1.4) * .16, math.cos(t * 1.1) * .08, math.sin(t * .8) * .035
        elif self._state == "SPEAKING":
            self._yaw, self._pitch, self._roll = math.sin(t * .9) * .08, math.sin(t * 1.7) * .045, math.cos(t * .65) * .025
        else:
            self._yaw, self._pitch, self._roll = math.sin(t * .42) * .055, math.cos(t * .37) * .035, math.sin(t * .25) * .015
        self._breath_scale = 1.0 if self._reduced_motion else 1.0 + .012 * math.sin(t * 1.3) + self._audio_energy * .018
        if not self._reduced_motion and elapsed > self._next_blink:
            self._blink = max(0.0, 1.0 - (elapsed - self._next_blink) / .16)
            if elapsed > self._next_blink + .16:
                self._next_blink = elapsed + random.uniform(2.0, 4.5)
                self._blink = 0.0
        if not self._reduced_motion and self._animation_speed > 0:
            self._scan = (self._scan + self._animation_speed * (.018 if self._state == "SPEAKING" else .008)) % 1.0
        self.update()

    def _mouth_open(self) -> float:
        viseme = max(self._viseme_weights["aa"] * .9,
                     self._viseme_weights["oh"] * .72,
                     self._viseme_weights["ou"] * .55,
                     self._viseme_weights["ee"] * .28)
        # Playback energy animates the jaw even if explicit phoneme timing is unavailable.
        speaking = self._state == "SPEAKING"
        energy = self._audio_energy * (0.72 if speaking else 0.08)
        pulse = (0.5 + 0.5 * math.sin((time.monotonic() - self._start_time) * 18.0)) if speaking else 0.0
        return min(0.34, max(viseme, energy * (0.35 + pulse * 0.65)))

    @staticmethod
    def _face_surface(u: float, v: float, t: float, mouth_open: float) -> Tuple[float, float, float]:
        """Procedural feminine face surface; no portrait or texture is sampled."""
        # v=-1 chin, v=+1 forehead. Width profile makes the jaw/chin visibly taper.
        profile = (
            (0.30 * math.exp(-((v + .92) / .16) ** 2)) +
            (0.57 * math.exp(-((v + .62) / .29) ** 2)) +
            (0.96 * math.exp(-((v + .12) / .62) ** 2)) +
            (0.80 * math.exp(-((v - .60) / .42) ** 2))
        )
        width = 0.57 * min(1.0, profile)
        x = u * width
        y = v * 0.88
        edge_rounding = math.sqrt(max(0.0, 1.0 - u * u))
        vertical_rounding = math.sqrt(max(0.0, 1.0 - v * v * .70))
        z = 0.055 + 0.15 * edge_rounding * vertical_rounding
        gauss = lambda a, b, sx, sy: math.exp(-((u-a)/sx)**2 - ((v-b)/sy)**2)

        # Cheekbones and temples give the front surface a recognizable face volume.
        z += .075 * (gauss(-.48, -.12, .24, .22) + gauss(.48, -.12, .24, .22))
        z += .035 * (gauss(-.76, .30, .18, .34) + gauss(.76, .30, .18, .34))
        # Brow ridges, recessed eye sockets, and raised nose bridge/tip.
        z += .060 * (gauss(-.34, .30, .23, .075) + gauss(.34, .30, .23, .075))
        z -= .070 * (gauss(-.34, .18, .19, .105) + gauss(.34, .18, .19, .105))
        z += .105 * gauss(0, .015, .075, .25)
        z += .165 * gauss(0, -.14, .095, .115)
        z += .045 * (gauss(-.12, -.17, .07, .055) + gauss(.12, -.17, .07, .055))
        # Philtrum, lips and chin pad.
        z += .018 * gauss(0, -.285, .07, .09)
        z += .075 * gauss(0, -.405, .235, .085)
        z += .065 * gauss(0, -.70, .26, .14)
        # Audio-driven jaw opening shifts the lower lip/chin subtly downwards.
        lower_mouth = gauss(0, -.445, .22, .085)
        y -= mouth_open * lower_mouth * (1.0 if v < -.40 else -0.08)
        return x, y, z

    def _project(self, u: float, v: float, t: float, mouth_open: float, w: float, h: float) -> QPointF:
        x, y, z = self._face_surface(u, v, t, mouth_open)
        cy = math.cos(self._yaw); sy = math.sin(self._yaw)
        cp = math.cos(self._pitch); sp = math.sin(self._pitch)
        cr = math.cos(self._roll); sr = math.sin(self._roll)
        xr, zr = x * cy + z * sy, -x * sy + z * cy
        yr, zr = y * cp - zr * sp, y * sp + zr * cp
        xr, yr = xr * cr - yr * sr, xr * sr + yr * cr
        perspective = 1.0 / max(.55, 1.0 + zr * .18)
        scale = min(w, h) * .43 * self._breath_scale * perspective
        return QPointF(w * .5 + xr * scale, h * .455 - yr * scale)

    def paintEvent(self, _event):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Clear the previous frame in the HUD backdrop colour: a transparent
        # ``CompositionMode_Clear`` composites to black on a plain child widget.
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), QColor("#080b11"))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        w, h = float(self.width()), float(self.height())
        elapsed = time.monotonic() - self._start_time
        t = 0.0 if self._reduced_motion else elapsed * self._animation_speed
        cx, cy, size = w * .5, h * .455, min(w, h)
        pink = QColor("#ff4fc8")
        hot = QColor("#ffb1ee")
        cyan = QColor("#67eaff")
        speaking = self._state == "SPEAKING"
        accent = cyan if self._state == "LISTENING" else pink

        # Ambient aura and rotating orbital rings.
        if self._effects_enabled:
            p.setPen(Qt.PenStyle.NoPen)
            for factor, alpha in ((.39, 8), (.32, 10), (.25, 9)):
                p.setBrush(QColor(255, 48, 200, alpha))
                p.drawEllipse(QPointF(cx, cy), size * factor, size * factor * 1.08)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 79, 200, 110), 1.0))
            p.drawEllipse(QPointF(cx, cy), size * .39, size * .44)
            arc = QRectF(cx - size * .43, cy - size * .47, size * .86, size * .94)
            p.setPen(QPen(hot, 1.7))
            p.drawArc(arc, int((t * 23 % 360) * 16), 105 * 16)
            p.setPen(QPen(pink, 1.0, Qt.PenStyle.DashLine))
            p.drawArc(arc.adjusted(8, 8, -8, -8), int((-t * 31 % 360) * 16), 76 * 16)

        mouth = self._mouth_open()
        # Grid mesh is generated from the procedural face surface on every frame.
        cols, rows = 25, 31
        grid: List[List[QPointF]] = []
        for j in range(rows):
            v = -0.98 + 1.96 * j / (rows - 1)
            row: List[QPointF] = []
            for i in range(cols):
                u = -0.98 + 1.96 * i / (cols - 1)
                row.append(self._project(u, v, t, mouth, w, h))
            grid.append(row)

        if self._effects_enabled:
            p.setPen(QPen(QColor(255, 79, 200, int(30 + 32 * self._glow_intensity * self._performance_glow_scale)), .65))
            for j in range(rows):
                for i in range(cols - 1):
                    p.drawLine(grid[j][i], grid[j][i + 1])
            for j in range(rows - 1):
                for i in range(cols):
                    p.drawLine(grid[j][i], grid[j + 1][i])
            # Diagonal links add the triangulated neural-mesh look.
            p.setPen(QPen(QColor(255, 135, 225, 48), .55))
            for j in range(rows - 1):
                for i in range(cols - 1):
                    if (i + j) % 2 == 0:
                        p.drawLine(grid[j][i], grid[j + 1][i + 1])
                    else:
                        p.drawLine(grid[j][i + 1], grid[j + 1][i])

        # Feature contours: eyes, brows, nose, mouth and chin.
        def curve(points, color, width=1.3, close=False):
            path = QPainterPath()
            for index, (u, v) in enumerate(points):
                point = self._project(u, v, t, mouth, w, h)
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            if close:
                path.closeSubpath()
            p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        for eye_center in (-.34, .34):
            eye = [(eye_center + .19 * math.cos(a), .18 + .075 * math.sin(a)) for a in [i * math.tau / 32 for i in range(33)]]
            curve(eye, hot if self._state != "LISTENING" else cyan, 1.55, True)
            brow = [(eye_center + .22 * k / 20, .31 + .045 * math.sin(math.pi * k / 20)) for k in range(21)]
            curve(brow, pink, 1.7)
            # Iris and pupil are luminous nodes, with a small blink squeeze.
            eye_pt = self._project(eye_center, .18, t, mouth, w, h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 177, 238, 220))
            eye_h = max(1.0, size * .016 * (1.0 - self._blink * .88))
            p.drawEllipse(eye_pt, size * .018, eye_h)
            p.setBrush(QColor(255, 79, 200, 210))
            p.drawEllipse(eye_pt, size * .007, max(1.0, eye_h * .55))

        curve([(0, .16), (-.035, .02), (-.07, -.10), (-.10, -.17), (-.055, -.20), (0, -.21), (.055, -.20), (.10, -.17), (.07, -.10), (.035, .02), (0, .16)], hot, 1.35)
        curve([(-.22, -.39), (-.14, -.365), (-.07, -.38), (0, -.39), (.07, -.38), (.14, -.365), (.22, -.39)], hot, 1.7)
        lower_lip = [(.22 * math.cos(a), -.405 - mouth * .45 * math.sin(a)) for a in [i * math.pi / 24 for i in range(25)]]
        curve(lower_lip, pink, 1.45)
        if mouth > .045:
            mouth_shape = [(.18 * math.cos(a), -.39 - mouth * .48 * math.sin(a)) for a in [i * math.tau / 36 for i in range(37)]]
            curve(mouth_shape, QColor(255, 90, 210, 210), 1.0, True)

        # Nodes sit on the face mesh; a deterministic sparse network is easier to read.
        p.setPen(Qt.PenStyle.NoPen)
        for j in range(1, rows - 1, 2):
            for i in range(1, cols - 1, 2):
                if (i * 7 + j * 11) % 5:
                    continue
                pt = grid[j][i]
                pulse = .5 + .5 * math.sin(t * 2.1 + i * .71 + j * .37)
                radius = (1.0 + pulse * (1.3 + self._audio_energy * 2.2)) * self._performance_glow_scale
                p.setBrush(QColor(255, 190, 244, int(105 + pulse * 145)))
                p.drawEllipse(pt, radius, radius)
                if self._effects_enabled and pulse > .86:
                    p.setBrush(QColor(255, 105, 225, 32))
                    p.drawEllipse(pt, radius * 3.2, radius * 3.2)

        # Floating particles and scanning beam.
        if self._effects_enabled:
            for x, y, radius, speed, phase in self._particles[:self._visible_particle_count()]:
                px = (x * .5 + .5) * w + math.sin(t * speed + phase) * 8
                py = (y * .5 + .5) * h + math.cos(t * speed + phase) * 6
                alpha = int(45 + 130 * (.5 + .5 * math.sin(t * 1.8 + phase)))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 105, 220, alpha))
                p.drawEllipse(QPointF(px, py), radius + self._audio_energy, radius + self._audio_energy)
            scan_y = h * .08 + self._scan * h * .75
            p.setPen(QPen(QColor(255, 155, 232, 95), 1.0))
            p.drawLine(QPointF(w * .16, scan_y), QPointF(w * .84, scan_y))

        # Status footer.
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(accent, 1))
        label = "NEURAL LINK // LISTENING" if self._state == "LISTENING" else (
            "NEURAL LINK // SPEAKING" if speaking else
            "NEURAL LINK // THINKING" if self._state == "THINKING" else
            "NEURAL LINK // STANDBY")
        p.drawText(QRectF(0, h * .90, w, 18), Qt.AlignmentFlag.AlignCenter, label)
        p.setPen(QPen(QColor(255, 79, 200, 155), 1))
        p.setFont(QFont("Courier New", 8))
        p.drawText(QRectF(0, h * .945, w, 16), Qt.AlignmentFlag.AlignCenter,
                   "PROCEDURAL FACE  •  NO IMAGE ASSETS")
        p.end()
