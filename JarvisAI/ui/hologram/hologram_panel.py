"""Composite hologram assembly for JARVIS AI Pro.

Lays out three independent widgets as one floating group:

* ``NeuralWireframeHead``  — the large neural-wireframe face, centred and on
  top.
* ``HolographicOrb``       — a voice-reactive orb beneath the face.
* ``QuantumHeartReactor``  — a small pulsing reactor beside the orb.

The panel itself only owns the layout maths and the faint neural "wires"
drawn between the three pieces; all the actual rendering and state logic
stays inside the three widgets above, so each of them keeps working as a
standalone drop-in if some other screen only wants the face, or only wants
the orb. Nothing here touches authentication, voice processing or privacy
logic — it only consumes the same ``state`` strings and audio-energy floats
the rest of the app already produces, and forwards them to its children.

This is an additive file: existing code that imports ``NeuralWireframeHead``
directly from ``wireframe_head.py`` is completely unaffected. Use
``JarvisHologramPanel`` where the full face + orb + reactor group is wanted.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from core.hologram_theme import JARVIS_PALETTE, ThemePalette
from .holo_scanline_overlay import HologramScanlineOverlay
from .holographic_orb import HolographicOrb
from .quantum_heart_reactor import QuantumHeartReactor
from .wireframe_head import NeuralWireframeHead


class JarvisHologramPanel(QWidget):
    """Face + orb + heart reactor, wired together as one hologram."""

    sig_state_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 460)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self._palette: ThemePalette = JARVIS_PALETTE
        self._start_time = time.time()
        self._reduced_motion = False
        self._frame_interval = 33

        self.head = NeuralWireframeHead(self)
        self.orb = HolographicOrb(self)
        self.heart = QuantumHeartReactor(self)
        # Transparent child overlay: follows the head's geometry and palette.
        self.scanline = HologramScanlineOverlay(self.head)

        self.head.sig_state_changed.connect(self._on_state_changed)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(self._frame_interval)

        self._relayout()

    # ── layout ──────────────────────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return

        # The face owns the top ~68% of the panel and stays centred; it is
        # deliberately the largest element so the hologram still reads as a
        # face first, orb/reactor second.
        face_h = int(h * 0.68)
        self.head.setGeometry(0, 0, w, face_h)

        orb_size = max(64, int(min(w, h) * 0.22))
        orb_x = int(w * 0.5 - orb_size * 0.62)
        orb_y = int(face_h * 0.92)
        self.orb.setGeometry(orb_x, orb_y, orb_size, orb_size)

        heart_size = max(36, int(orb_size * 0.56))
        heart_x = orb_x + orb_size + int(orb_size * 0.12)
        heart_y = orb_y + int(orb_size * 0.22)
        self.heart.setGeometry(heart_x, heart_y, heart_size, heart_size)

    # ── public API ──────────────────────────────────────────────────────────
    @pyqtSlot(float)
    def set_audio_energy(self, level: float) -> None:
        self.head.set_audio_energy(level)
        self.orb.set_audio_energy(level)
        self.heart.set_pulse_energy(level)

    @pyqtSlot(str)
    def set_state(self, state: str) -> None:
        self.head.set_state(state)
        self.orb.set_state(state)
        self.heart.set_state(state)

    def get_state(self) -> str:
        return self.head.get_state()

    def set_palette(self, palette: ThemePalette) -> None:
        if palette is None or palette == self._palette:
            return
        self._palette = palette
        self.head.set_palette(palette)
        self.orb.set_palette(palette)
        self.heart.set_palette(palette)
        self.scanline.update()
        self.update()

    def palette(self) -> ThemePalette:
        return self._palette

    def set_glow(self, intensity: float) -> None:
        self.head.set_glow(intensity)

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        self.head.set_reduced_motion(enabled)
        self.orb.set_reduced_motion(enabled)
        self.heart.set_reduced_motion(enabled)
        self.scanline.set_reduced_motion(enabled)

    def set_performance_budget(self, frame_interval_ms: int, particle_scale: float, glow_scale: float) -> None:
        interval = max(16, min(200, int(frame_interval_ms)))
        if interval != self._frame_interval:
            self._frame_interval = interval
            self._timer.setInterval(interval)
        self.head.set_performance_budget(frame_interval_ms, particle_scale, glow_scale)
        self.orb.set_performance_budget(frame_interval_ms, particle_scale, glow_scale)
        self.heart.set_performance_budget(frame_interval_ms, particle_scale, glow_scale)
        self.scanline.set_performance_budget(frame_interval_ms, particle_scale, glow_scale)

    def face_rect(self):
        """Bounding box of the face mesh, translated into panel coordinates."""
        rect = self.head.face_rect()
        rect.translate(self.head.x(), self.head.y())
        return rect

    # ── wiring ──────────────────────────────────────────────────────────────
    @pyqtSlot(str)
    def _on_state_changed(self, state: str) -> None:
        self.sig_state_changed.emit(state)

    def _draw_wire(self, painter: QPainter, p1: QPointF, p2: QPointF, colour: QColor, t: float, seed: float) -> None:
        """A soft glow-and-core neural wire, with one travelling data pulse."""
        path = QPainterPath()
        mid = QPointF((p1.x() + p2.x()) / 2.0, (p1.y() + p2.y()) / 2.0 - 10.0)
        path.moveTo(p1)
        path.quadTo(mid, p2)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(colour.red(), colour.green(), colour.blue(), 55), 4.2))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(colour.red(), colour.green(), colour.blue(), 170), 1.4))
        painter.drawPath(path)

        if self._reduced_motion:
            return
        frac = (t * 0.35 + seed) % 1.0
        pulse_point = path.pointAtPercent(frac)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 250, 240, 230))
        painter.drawEllipse(pulse_point, 2.6, 2.6)

    # ── painting ────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        t = time.time() - self._start_time
        secondary = QColor(*self._palette.secondary)

        chin = self.head.chin_anchor()
        chin_panel = QPointF(self.head.x() + chin.x(), self.head.y() + chin.y())

        orb_top = self.orb.top_anchor_point()
        orb_top_panel = QPointF(self.orb.x() + orb_top.x(), self.orb.y() + orb_top.y())

        orb_right = self.orb.anchor_point()
        orb_right_panel = QPointF(self.orb.x() + orb_right.x(), self.orb.y() + orb_right.y())

        heart_left = self.heart.anchor_point()
        heart_left_panel = QPointF(self.heart.x() + heart_left.x(), self.heart.y() + heart_left.y())

        self._draw_wire(painter, chin_panel, orb_top_panel, secondary, t, 0.0)
        self._draw_wire(painter, orb_right_panel, heart_left_panel, secondary, t, 0.5)

        painter.end()
