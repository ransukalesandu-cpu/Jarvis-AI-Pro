"""Central neural wireframe *face* hologram for JARVIS AI Pro.

The mesh is generated from a parametric head surface at runtime: no image, no
texture, no model download. It is rendered with QPainter on a translucent
canvas, so the hologram floats over the HUD instead of sitting in a black
rectangle, and it stays cheap enough to run on integrated graphics.

What changed in the holographic-UI upgrade
------------------------------------------
* **It is a face now.** The old mesh was a UV sphere stretched vertically. The
  generator deforms the sphere into a human head: narrower chin and jaw, flatter
  cranium at the back, brow ridge, cheekbones, eye sockets and a nose bridge,
  with the features also drawn as brighter accent curves.
* **Persona colours.** Colours come from ``core.hologram_theme``: JARVIS uses
  the restored electric-cyan identity while Bihansa remains rose-pink.
* **Truthful states.** IDLE / LISTENING / THINKING / SPEAKING / ERROR /
  DISCONNECTED / PRIVACY_LOCK, each with a distinct but restrained treatment.
  SPEAKING is driven by real output energy; there is no fake lip-sync claim.
* **Performance budget.** ``set_performance_budget()`` lowers the frame rate,
  particle count and bloom when the adaptive-performance engine says so.
* **Transparent canvas.** The frame is cleared with a source-over transparent
  fill (not ``CompositionMode_Clear``, which turns black on plain widgets).
"""

from __future__ import annotations

import math
import os
import random
import time
from typing import List, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from core.hologram_theme import JARVIS_PALETTE, ThemePalette, backdrop_rgb

if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    _BASE_CANVAS = QWidget
else:
    try:
        from PyQt6.QtOpenGLWidgets import QOpenGLWidget

        _BASE_CANVAS = QOpenGLWidget
    except Exception:  # pragma: no cover - PyQt6 always ships this on desktop
        _BASE_CANVAS = QWidget


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    """Hermite ramp; used to blend facial features without hard creases."""
    if edge1 == edge0:
        return 0.0
    t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _gaussian(value: float, centre: float, spread: float) -> float:
    if spread <= 0:
        return 0.0
    return math.exp(-((value - centre) ** 2) / (2.0 * spread * spread))


class NeuralWireframeHead(_BASE_CANVAS):
    """Voice-reactive 3D neural head/face visualizer."""

    sig_state_changed = pyqtSignal(str)

    # Kept for compatibility with older code that referenced the original
    # palette constants. The live palette comes from ``set_palette``.
    COLOR_BG = QColor("#07090d")
    COLOR_CYAN = QColor("#00e5ff")
    COLOR_VIOLET = QColor("#7c4dff")
    COLOR_RED = QColor("#ff1744")
    COLOR_GREEN = QColor("#00e676")
    COLOR_AMBER = QColor("#ffab00")

    # A denser shell keeps the forehead, cheek and jaw contours crisp without
    # introducing a heavyweight model or external rendering dependency.
    RINGS = 28
    SECTORS = 44

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        # The hologram floats over the HUD: no opaque rectangle, no system fill.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self._palette: ThemePalette = JARVIS_PALETTE
        self._state = "IDLE"
        self._audio_energy = 0.0
        self._target_energy = 0.0

        self._rot_x = 0.0
        self._rot_y = 0.0
        self._drift_y = 0.0
        self._start_time = time.time()
        self._glitch_intensity = 0.0
        self._glow = 1.0
        self._reduced_motion = False
        self._particle_budget = 1.0
        self._frame_interval = 16

        self._vertices: List[Tuple[float, float, float]] = []
        self._edges: List[Tuple[int, int]] = []
        self._feature_edges: List[Tuple[int, int]] = []
        self._eyes: List[int] = []
        self._particles: List[dict] = []
        self._build_mesh_geometry()
        self._build_particles()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(16)

    # ── geometry ────────────────────────────────────────────────────────────
    #: Head profile: (v, half-width) from crown (v = 1) to chin (v = -1).
    #: Widest at the temples/cheekbones, tapering hard into the jaw and chin.
    PROFILE = (
        (0.55, 0.90), (0.40, 0.97), (0.22, 1.00), (0.04, 0.98),
        (-0.14, 0.93), (-0.32, 0.85), (-0.45, 0.76), (-0.55, 0.68),
    )

    @classmethod
    def _radius_at(cls, v: float) -> float:
        """Half-width of the head at height ``v``.

        The crown and the chin are rounded caps rather than the linear ends of
        the profile table, which is what stopped the head from looking like a
        vase: a dome on top, a blunt jaw and chin below.
        """
        v = max(-1.0, min(1.0, v))
        if v > 0.55:
            # Dome: a half-ellipse from the temples to the crown.
            t = (v - 0.55) / 0.45
            return 0.80 * math.sqrt(max(0.0, 1.0 - t * t)) + 0.08
        if v < -0.55:
            # Rounded, slightly blunt chin.
            t = (-0.55 - v) / 0.45
            return 0.10 + 0.56 * math.sqrt(max(0.0, 1.0 - t * t))
        profile = cls.PROFILE
        for (v0, r0), (v1, r1) in zip(profile, profile[1:]):
            if v <= v0 and v >= v1:
                span = v0 - v1
                t = 0.0 if span <= 0 else (v0 - v) / span
                return r0 + (r1 - r0) * t
        return profile[-1][1]

    @classmethod
    def _head_surface(
        cls, a: float, v: float, *, sculpt: bool = True
    ) -> Tuple[float, float, float]:
        """Point on the head shell.

        ``a`` is the horizontal angle in quadrant units: ``a = 0`` is the centre
        of the face, ``a = ±1`` the ears, ``|a| > 1`` the back of the skull.
        ``v`` is the vertical parameter: ``1`` crown, ``-1`` chin.
        """
        theta = a * math.pi / 2.0
        radius = cls._radius_at(v)
        sin_t, cos_t = math.sin(theta), math.cos(theta)

        # Heads are taller than wide; 0.86 keeps the silhouette from reading as
        # a ball while leaving room for the cheekbones.
        x = sin_t * radius * 0.86
        # The face is flatter than the back of the skull, which is what makes the
        # frontal features read as a face instead of a sphere.
        depth = 0.88 if cos_t > 0 else 1.0
        z = cos_t * radius * depth
        y = v * 1.10 - 0.02

        front = max(0.0, cos_t)
        if front > 0.0 and sculpt:
            ax = abs(x)
            # Nose bridge + tip: a narrow ridge down the centre line.
            nose = _gaussian(ax, 0.0, 0.085) * (
                _gaussian(v, 0.06, 0.22) + 0.45 * _gaussian(v, -0.17, 0.07)
            )
            z += 0.30 * nose * front
            # Feature curves use angular coordinates; sculpting follows their
            # projected x positions so the face reads clearly at HUD scale.
            eye_x = math.sin(0.40 * math.pi / 2.0) * 0.86 * cls._radius_at(0.18)
            brow_x = math.sin(0.25 * math.pi / 2.0) * 0.86 * cls._radius_at(0.33)
            cheek_x = math.sin(0.62 * math.pi / 2.0) * 0.86 * cls._radius_at(-0.05)
            z += 0.075 * _gaussian(ax, brow_x, 0.15) * _gaussian(v, 0.33, 0.095) * front
            z -= 0.125 * _gaussian(ax, eye_x, 0.14) * _gaussian(v, 0.18, 0.105) * front
            z += 0.085 * _gaussian(ax, cheek_x, 0.16) * _gaussian(v, -0.05, 0.16) * front
            z += 0.045 * _gaussian(ax, 0.0, 0.36) * _gaussian(v, -0.30, 0.055) * front
            z -= 0.075 * _gaussian(ax, 0.0, 0.37) * _gaussian(v, -0.37, 0.045) * front
            z -= 0.022 * _gaussian(ax, cheek_x * 0.78, 0.075) * _gaussian(v, -0.22, 0.12) * front
            z += 0.045 * _gaussian(ax, 0.0, 0.16) * _gaussian(v, -0.66, 0.11) * front
            # Jaw: pull the lower sides back so the skull ends in a jaw, not a box.
            if v < -0.35:
                z *= 1.0 - 0.10 * min(1.0, (-0.35 - v) / 0.55)

        return (x, y, z)

    def _build_mesh_geometry(self):
        """Build the neural face: a head shell plus explicit facial features."""
        vertices: List[Tuple[float, float, float]] = []
        edges: List[Tuple[int, int]] = []
        rings, sectors = self.RINGS, self.SECTORS

        # Grid over the shell. V is non-linear (denser around the features) so
        # the nose, eyes and mouth get enough vertices.
        vs = [-1.0 + 2.0 * (r / rings) for r in range(rings + 1)]
        vs = [math.copysign(abs(v) ** 0.85, v) for v in vs]
        for v in vs:
            for s in range(sectors):
                a = -2.0 + 4.0 * (s / sectors)
                vertices.append(self._head_surface(a, v))

        def index(r: int, s: int) -> int:
            return r * sectors + (s % sectors)

        for r in range(rings):
            for s in range(sectors):
                nxt = (s + 1) % sectors
                edges.append((index(r, s), index(r, nxt)))          # ring
                edges.append((index(r, s), index(r + 1, s)))        # meridian
                if (r + s) % 3 == 0:
                    edges.append((index(r, s), index(r + 1, nxt)))  # neural cross-link

        # Facial features are sampled on the shell itself, so they follow the
        # surface instead of floating in front of it.
        feature: List[Tuple[int, int]] = []

        def add_polyline(points: List[Tuple[float, float]], closed: bool = False) -> List[int]:
            base = len(vertices)
            for a, v in points:
                vertices.append(self._head_surface(a, v))
            count = len(points)
            for i in range(count if closed else count - 1):
                feature.append((base + i, base + (i + 1) % count))
            return list(range(base, base + count))

        # Eyes: closed rings, slightly wider than tall, sitting in the sockets.
        self._eyes = []
        for side in (-1, 1):
            # Smooth outer eyelid and a smaller inner contour give each eye a
            # defined socket instead of a coarse octagonal loop.
            outer_eye = [
                (side * 0.40 + 0.155 * math.cos(t), 0.18 + 0.075 * math.sin(t))
                for t in [i * math.pi / 8 for i in range(16)]
            ]
            add_polyline(outer_eye, closed=True)
            inner_eye = [
                (side * 0.40 + 0.105 * math.cos(t), 0.18 + 0.040 * math.sin(t))
                for t in [i * math.pi / 8 for i in range(16)]
            ]
            add_polyline(inner_eye, closed=True)
            self._eyes.append(len(vertices))
            vertices.append(self._head_surface(side * 0.40, 0.18))

        # Brows: denser, tapered arcs above the eyes.
        for side in (-1, 1):
            brow = [
                (side * (0.20 + 0.0525 * i),
                 0.30 + 0.030 * math.sqrt(max(0.0, 1 - ((i - 4) / 4.4) ** 2)) - 0.006 * i)
                for i in range(9)
            ]
            add_polyline(brow)

        # Nose: a continuous bridge, tip contour and clearly separated nostrils.
        add_polyline([(0.0, 0.30 - 0.052 * i) for i in range(9)])
        add_polyline([(-0.035, -0.105), (-0.020, -0.135), (0.0, -0.148),
                      (0.020, -0.135), (0.035, -0.105)])
        for side in (-1, 1):
            add_polyline([
                (side * 0.025, -0.135), (side * 0.055, -0.158),
                (side * 0.085, -0.164), (side * 0.112, -0.145),
                (side * 0.118, -0.118),
            ])

        # Cheekbone and jaw contours add definition to the face silhouette.
        for side in (-1, 1):
            add_polyline([
                (side * (0.54 + 0.035 * i), 0.02 - 0.060 * i)
                for i in range(7)
            ])
            add_polyline([
                (side * (0.78 - 0.055 * i), -0.22 - 0.050 * i)
                for i in range(7)
            ])

        # Philtrum and mouth: smooth cupid's-bow upper lip and lower lip.
        add_polyline([(0.0, -0.17), (0.0, -0.22), (0.0, -0.27)])
        add_polyline([
            (-0.30 + 0.05 * i,
             -0.345 + 0.032 * math.sin(math.pi * i / 12)
             + 0.010 * math.sin(math.pi * i / 6))
            for i in range(13)
        ])
        add_polyline([
            (-0.25 + (0.50 / 12) * i,
             -0.405 - 0.018 * math.sin(math.pi * i / 12))
            for i in range(13)
        ])
        # A short, gently curved chin crease finishes the lower-face detail.
        add_polyline([
            (-0.16 + 0.04 * i, -0.56 - 0.018 * math.sin(math.pi * i / 8))
            for i in range(9)
        ])

        self._vertices = vertices
        self._edges = edges
        self._feature_edges = feature

    def _build_particles(self):
        """Orbital neural dust around the head (scaled by the perf budget)."""
        self._particles = []
        for _ in range(48):
            self._particles.append({
                "radius": random.uniform(1.15, 2.15),
                "angle": random.uniform(0, math.pi * 2),
                "speed": random.uniform(0.02, 0.05),
                "y_offset": random.uniform(-0.85, 0.85),
                "size": random.uniform(1.8, 4.2),
            })

    # ── public API ──────────────────────────────────────────────────────────
    @pyqtSlot(float)
    def set_audio_energy(self, level: float):
        """Thread-safe update of microphone/TTS energy in [0, 1]."""
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

    def get_state(self) -> str:
        return self._state

    def set_palette(self, palette: ThemePalette) -> None:
        """Swap persona identity (JARVIS copper ⇄ Bihansa pink) in place."""
        if palette is None or palette == self._palette:
            return
        self._palette = palette
        self.update()

    def palette(self) -> ThemePalette:
        return self._palette

    def set_glow(self, intensity: float) -> None:
        try:
            self._glow = max(0.2, min(1.6, float(intensity)))
        except (TypeError, ValueError):
            self._glow = 1.0
        self.update()

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        self.update()

    def set_performance_budget(self, frame_interval_ms: int, particle_scale: float, glow_scale: float) -> None:
        """Apply an adaptive budget without rebuilding geometry."""
        interval = max(16, min(200, int(frame_interval_ms)))
        if interval != self._frame_interval:
            self._frame_interval = interval
            self._timer.setInterval(interval)
        self._particle_budget = max(0.0, min(1.0, float(particle_scale)))
        self._glow_scale = max(0.2, min(1.0, float(glow_scale)))
        self.update()

    _glow_scale = 1.0

    # ── animation ───────────────────────────────────────────────────────────
    def _step(self):
        t = time.time() - self._start_time
        self._audio_energy += (self._target_energy - self._audio_energy) * 0.25
        speed = 0.0 if self._reduced_motion else 1.0

        # The head is a *face*, not a spinning ball: it holds a three-quarter
        # view and drifts a little, so the eyes/nose/mouth stay readable while
        # still feeling alive.
        look = math.sin(t * 0.42) if not self._reduced_motion else 0.0
        if self._state == "THINKING":
            self._rot_y = 0.30 + 0.22 * look + 0.05 * math.sin(t * 2.1)
            self._rot_x = 0.06 + 0.05 * math.sin(t * 1.7)
            self._glitch_intensity = 0.0
        elif self._state in ("SPEAKING", "LISTENING"):
            self._rot_y = 0.26 + 0.16 * look
            self._rot_x = 0.03 + math.sin(t * 0.9) * 0.08
            self._glitch_intensity = 0.0
        elif self._state == "PRIVACY_LOCK":
            self._rot_y = 0.0
            self._rot_x = 0.0
            self._glitch_intensity = random.uniform(0.05, 0.25)
        elif self._state in ("ERROR", "DISCONNECTED"):
            self._rot_y = 0.10 + 0.04 * look
            self._rot_x = math.sin(t * 0.4) * 0.05
            self._glitch_intensity = 0.05
        else:
            self._rot_y = 0.28 + 0.20 * look
            self._rot_x = 0.02 + math.sin(t * 0.8) * 0.08
            self._glitch_intensity = 0.0

        self._drift_y = 0.0 if self._reduced_motion else math.sin(t * 1.4) * 10.0
        if not self._reduced_motion:
            boost = 2.4 if self._state == "THINKING" else 1.0
            for particle in self._particles:
                particle["angle"] += particle["speed"] * boost
        self.update()

    # ── painting ────────────────────────────────────────────────────────────
    def face_rect(self):
        """Bounding box the face mesh actually occupies, in widget coordinates.

        Used by the task-panel layout so panels are placed around the face
        instead of around the whole (much larger) transparent widget.
        """
        side = min(self.width(), self.height()) * 0.72
        return QRectF(
            self.width() / 2.0 - side / 2.0,
            self.height() / 2.0 - side / 2.0,
            side,
            side,
        ).toRect()

    def paintEvent(self, event):
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Clear to the HUD backdrop colour. A transparent clear is composited
        # as black on a plain child widget, which is exactly the black rectangle
        # the hologram used to sit in; matching the backdrop keeps it invisible.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(*backdrop_rgb()))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        width, height = self.width(), self.height()
        cx, cy = width / 2.0, (height / 2.0) + self._drift_y
        palette = self._palette
        t = time.time() - self._start_time
        primary = QColor(*palette.primary)
        secondary = QColor(*palette.secondary)
        accent = QColor(*palette.accent)

        scale_mod = 1.0
        glow_alpha = 34
        if self._state == "IDLE":
            scale_mod = 1.0 + (0.0 if self._reduced_motion else 0.035 * math.sin(t * math.pi))
            glow_alpha = 30
        elif self._state == "LISTENING":
            scale_mod = 1.0 + self._audio_energy * 0.42
            glow_alpha = 34 + int(40 * self._audio_energy)
        elif self._state == "THINKING":
            scale_mod = 1.04 + (0.0 if self._reduced_motion else 0.06 * math.sin(t * 5.0))
            glow_alpha = 46
            primary = QColor(*palette.secondary)
        elif self._state == "SPEAKING":
            scale_mod = 1.0 + self._audio_energy * 0.30 + (0.0 if self._reduced_motion else 0.04 * math.sin(t * 11.0))
            glow_alpha = 40 + int(55 * self._audio_energy)
        elif self._state == "PRIVACY_LOCK":
            scale_mod = 0.86
            primary = self.COLOR_RED
            secondary = QColor("#ff8a80")
            accent = self.COLOR_RED
            glow_alpha = 26
        elif self._state in ("ERROR", "DISCONNECTED"):
            scale_mod = 0.97
            primary = QColor("#ff8f5a")
            secondary = QColor("#ffb38a")
            accent = QColor("#ff6b6b")
            glow_alpha = 20

        base_radius = min(width, height) * 0.30 * scale_mod
        cos_y, sin_y = math.cos(self._rot_y), math.sin(self._rot_y)
        cos_x, sin_x = math.cos(self._rot_x), math.sin(self._rot_x)

        projected: List[Tuple[float, float, float]] = []
        for x0, y0, z0 in self._vertices:
            if self._glitch_intensity > 0:
                wobble = self._glitch_intensity * 0.2
                x0 += random.uniform(-wobble, wobble)
                y0 += random.uniform(-wobble, wobble)
            x1 = x0 * cos_y + z0 * sin_y
            z1 = -x0 * sin_y + z0 * cos_y
            y2 = y0 * cos_x - z1 * sin_x
            z2 = y0 * sin_x + z1 * cos_x
            # Gentle perspective: a short focal length distorted the face into
            # an egg by magnifying the nose relative to the temples.
            fov = 9.0
            dist = fov / (fov + z2 + 1.2)
            # Screen y grows downward, so the model's +y (crown) must be
            # subtracted: without this the whole face renders upside down.
            projected.append((cx + x1 * base_radius * dist, cy - y2 * base_radius * dist, z2))

        # 1. Environmental bloom behind the head (cheap: one radial gradient).
        halo = QRadialGradient(QPointF(cx, cy), base_radius * 1.7)
        glow_colour = QColor(*(QColor(*palette.glow).getRgb()[:3]))
        alpha = int(glow_alpha * self._glow * self._glow_scale)
        halo.setColorAt(0.0, QColor(glow_colour.red(), glow_colour.green(), glow_colour.blue(), alpha))
        halo.setColorAt(0.55, QColor(glow_colour.red(), glow_colour.green(), glow_colour.blue(), alpha // 4))
        halo.setColorAt(1.0, QColor(glow_colour.red(), glow_colour.green(), glow_colour.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QPointF(cx, cy), base_radius * 1.7, base_radius * 1.7)

        # 2. Neural dust: only while something is happening, and budget-limited.
        visible_particles = int(len(self._particles) * self._particle_budget)
        if self._state in ("THINKING", "SPEAKING", "LISTENING") and visible_particles:
            painter.setPen(Qt.PenStyle.NoPen)
            for particle in self._particles[:visible_particles]:
                radius = base_radius * particle["radius"]
                px = cx + math.cos(particle["angle"]) * radius
                depth = math.sin(particle["angle"]) * radius
                py = cy + particle["y_offset"] * base_radius * 0.7
                particle_alpha = int(max(30, min(220, 150 + depth * 0.25)))
                painter.setBrush(QColor(secondary.red(), secondary.green(), secondary.blue(), particle_alpha))
                size = particle["size"] * (1.4 if self._state == "THINKING" else 1.0)
                painter.drawEllipse(QPointF(px, py), size, size)

        # 3. Wireframe edges. Quantized depth paths preserve back-to-front
        # shading while replacing hundreds of per-edge QPen/QColor allocations.
        pen_width = 1.7 if self._state in ("LISTENING", "SPEAKING") else 1.15
        edge_paths = [QPainterPath() for _ in range(8)]
        for idx1, idx2 in self._edges:
            x1, y1, z1 = projected[idx1]
            x2, y2, z2 = projected[idx2]
            avg_z = (z1 + z2) * 0.5
            if avg_z < -0.02:
                continue
            front = max(0.0, min(1.0, (avg_z + 1.0) * 0.5))
            bucket = min(7, int(front * 7.999))
            edge_paths[bucket].moveTo(x1, y1)
            edge_paths[bucket].lineTo(x2, y2)
        for bucket, path in enumerate(edge_paths):
            if path.isEmpty():
                continue
            alpha = int(34 + 116 * (bucket / 7.0))
            painter.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), alpha), pen_width))
            painter.drawPath(path)

        # 4. Facial features: brighter curves so the mesh reads as a face.
        visible_features = [
            (projected[i1], projected[i2])
            for i1, i2 in self._feature_edges
            if (projected[i1][2] + projected[i2][2]) / 2.0 >= 0.05
        ]
        # Wide, soft pass gives the features a holographic bloom...
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 70), 4.6))
        for (x1, y1, _z1), (x2, y2, _z2) in visible_features:
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        # ...and a crisp core makes them readable at a glance.
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 245), 2.0))
        for (x1, y1, _z1), (x2, y2, _z2) in visible_features:
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Eye highlights: two small ellipses where the eyes are, so the gaze
        # reads instantly even at a glance.
        eye_alpha = 210
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), eye_alpha))
        for eye in self._eyes:
            x1, y1, z1 = projected[eye]
            if z1 <= 0.1:
                continue
            painter.drawEllipse(QPointF(x1, y1), 3.2, 2.2)

        # 5. Neural nodes. Batch ellipses by depth to avoid a brush allocation
        # and draw call for every mesh vertex.
        node_radius = 1.9 + (self._audio_energy * 3.4 if self._state in ("LISTENING", "SPEAKING") else 0.0)
        node_paths = [QPainterPath() for _ in range(8)]
        for px, py, z in projected:
            if z < 0.0:
                continue
            bucket = min(7, max(0, int(max(0.0, min(1.0, (z + 1.0) * 0.5)) * 7.999)))
            node_paths[bucket].addEllipse(QPointF(px, py), node_radius, node_radius)
        painter.setPen(Qt.PenStyle.NoPen)
        for bucket, path in enumerate(node_paths):
            if path.isEmpty():
                continue
            alpha = int(40 + (230 - 40) * (bucket / 7.0))
            painter.setBrush(QColor(secondary.red(), secondary.green(), secondary.blue(), alpha))
            painter.drawPath(path)

        # 6. Status chrome.
        if self._state == "PRIVACY_LOCK":
            self._draw_lockdown_overlay(painter, width, height, cx, cy)
        elif self._state in ("ERROR", "DISCONNECTED"):
            self._draw_status_badge(
                painter, width, height, "LINK LOST" if self._state == "DISCONNECTED" else "ERROR",
                "Reconnecting — check the dashboard", QColor("#ff6b6b"),
            )
        elif self._state == "SPEAKING" and self._audio_energy > 0.02:
            self._draw_energy_ring(painter, cx, cy, base_radius, accent)

        painter.end()

    def _draw_energy_ring(self, painter: QPainter, cx: float, cy: float, radius: float, accent: QColor) -> None:
        """A single thin ring that grows with real output energy."""
        ring_radius = radius * (1.16 + 0.10 * self._audio_energy)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(),
                                   int(60 + 120 * self._audio_energy)), 1.1))
        painter.drawEllipse(QPointF(cx, cy), ring_radius, ring_radius * 0.94)

    def _draw_status_badge(self, painter: QPainter, width: float, height: float,
                           title: str, subtitle: str, colour: QColor) -> None:
        painter.save()
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.setPen(QPen(colour))
        painter.drawText(QRectF(0, height - 74, width, 20),
                         int(Qt.AlignmentFlag.AlignCenter), title)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QPen(QColor(220, 210, 205, 190)))
        painter.drawText(QRectF(0, height - 54, width, 18),
                         int(Qt.AlignmentFlag.AlignCenter), subtitle)
        painter.restore()

    def _draw_lockdown_overlay(self, painter: QPainter, width: float, height: float,
                               cx: float, cy: float) -> None:
        """Prominent security lockdown overlay during PRIVACY_LOCK."""
        painter.save()
        painter.fillRect(self.rect(), QColor(10, 0, 4, 170))

        shield = QPainterPath()
        shield_width, shield_height = 60.0, 70.0
        shield.moveTo(cx, cy - shield_height / 2.0)
        shield.lineTo(cx + shield_width / 2.0, cy - shield_height / 3.0)
        shield.lineTo(cx + shield_width / 2.0, cy + shield_height / 4.0)
        shield.lineTo(cx, cy + shield_height / 2.0)
        shield.lineTo(cx - shield_width / 2.0, cy + shield_height / 4.0)
        shield.lineTo(cx - shield_width / 2.0, cy - shield_height / 3.0)
        shield.closeSubpath()

        painter.setPen(QPen(self.COLOR_RED, 3))
        painter.setBrush(QColor(183, 28, 28, 120))
        painter.drawPath(shield)

        painter.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        painter.setPen(QPen(self.COLOR_RED, 1))
        painter.drawText(QRectF(0, cy + shield_height / 2.0 + 15, width, 30),
                         int(Qt.AlignmentFlag.AlignCenter), "SYSTEM PRIVACY LOCK ENGAGED")

        painter.setFont(QFont("Courier New", 9))
        painter.setPen(QPen(QColor("#ff8a80"), 1))
        painter.drawText(QRectF(0, cy + shield_height / 2.0 + 45, width, 25),
                         int(Qt.AlignmentFlag.AlignCenter), "MUTED & BLOCKED — PIN REQUIRED")
        painter.restore()
