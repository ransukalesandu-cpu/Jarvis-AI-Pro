"""Quantum-reactor heart for the HUD: a small, code-drawn holographic mesh.

Placement (changed in the holographic-UI upgrade)
-------------------------------------------------
The heart used to sit at the far left edge of the stage with conduits arcing
across the whole screen. It now docks **left of the status orb, below the
hologram**, so the three elements read as one cluster and the face keeps the
centre. The conduits are short: heart → orb, plus a dim filament up toward the
jaw. Nothing crosses the face.

It stays a full-stage transparent overlay (parented to the stage, as before) and
positions itself from the stage size, so it lands in the same place at every
resolution and never overlaps the task panels, which the layout engine keeps
clear of the hologram box.

Battery behaviour
-----------------
``set_battery(available, percent, plugged)`` drives three truthful effects:

* plugging in fires **one** energy pulse through the mesh (it does not loop
  while the charger stays connected);
* at or below the warning threshold the palette shifts amber/red and the pulse
  speeds up;
* when the machine has no battery sensor the heart simply stays in its normal
  red/pink/orange cycle — no invented percentage, no fake charging state.
"""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import QEvent, QPointF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from core.hologram_theme import JARVIS_PALETTE, ThemePalette


class NeuralHeartReactor(QWidget):
    """Small heart-shaped neural mesh with short head/orb conduits and aura."""

    CHARGE_PULSE_SECONDS = 1.8

    def __init__(self, stage: QWidget, parent=None):
        super().__init__(stage)
        self._stage = stage
        self._state = "IDLE"
        self._started_at = time.monotonic()
        self._palette: ThemePalette = JARVIS_PALETTE
        self._reduced_motion = False
        self._glow = 1.0
        self._energy = 0.0
        self._battery_available = False
        self._battery_percent: float | None = None
        self._battery_plugged = False
        self._last_plugged: bool | None = None
        self._charge_pulse_started: float | None = None
        self._low_battery = False
        self._face_rect = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setObjectName("NeuralHeartReactor")
        self.setGeometry(stage.rect())
        stage.installEventFilter(self)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(33)

    # ── feed ────────────────────────────────────────────────────────────────
    def eventFilter(self, watched, event):
        if watched is self._stage and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._stage.rect())
            self.raise_()
        return super().eventFilter(watched, event)

    def set_state(self, state: str):
        self._state = str(state or "IDLE").upper()
        self.update()

    def set_palette(self, palette: ThemePalette) -> None:
        self._palette = palette or JARVIS_PALETTE
        self.update()

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        self._timer.setInterval(120 if self._reduced_motion else 33)
        self.update()

    def set_glow(self, intensity: float) -> None:
        try:
            self._glow = max(0.2, min(1.6, float(intensity)))
        except (TypeError, ValueError):
            self._glow = 1.0

    def set_face_rect(self, rect) -> None:
        """Tell the reactor where the face is, so the filament ends on its chin."""
        self._face_rect = rect
        self.update()

    def set_energy(self, energy: float) -> None:
        try:
            self._energy = max(0.0, min(1.0, float(energy)))
        except (TypeError, ValueError):
            self._energy = 0.0

    def set_battery(self, available: bool, percent: float | None = None,
                    plugged: bool = False, *, low_threshold: float = 25.0) -> None:
        """Feed real battery state. ``available=False`` means "no sensor"."""
        was_plugged = self._last_plugged
        self._battery_available = bool(available)
        self._battery_plugged = bool(plugged) if available else False
        self._battery_percent = float(percent) if (available and percent is not None) else None
        self._last_plugged = self._battery_plugged if available else None
        self._low_battery = (
            self._battery_available
            and not self._battery_plugged
            and self._battery_percent is not None
            and self._battery_percent <= low_threshold
        )
        # One pulse on the plug-in edge only.
        if self._battery_available and was_plugged is False and self._battery_plugged:
            self._charge_pulse_started = time.monotonic()
        self.update()

    def charge_pulse_active(self) -> bool:
        if self._charge_pulse_started is None:
            return False
        return (time.monotonic() - self._charge_pulse_started) < self.CHARGE_PULSE_SECONDS

    # ── palette helpers ─────────────────────────────────────────────────────
    def _cycle_color(self, elapsed: float) -> QColor:
        """Smoothly loop red → pink → orange (the reactor's identity)."""
        palette = self._palette
        stops = (palette.heart_red, palette.heart_pink, palette.heart_orange)
        if self._reduced_motion:
            elapsed = 0.0
        phase = (elapsed / 3.2) % len(stops)
        index = int(phase)
        blend = phase - index
        start, end = stops[index], stops[(index + 1) % len(stops)]
        colour = QColor(*(round(a + (b - a) * blend) for a, b in zip(start, end)))
        if self._low_battery:
            # Amber/red warning without abandoning the reactor palette.
            blend_colour = QColor(255, 140, 60)
            ratio = 0.45
            colour = QColor(
                int(colour.red() * (1 - ratio) + blend_colour.red() * ratio),
                int(colour.green() * (1 - ratio) + blend_colour.green() * ratio),
                int(colour.blue() * (1 - ratio) + blend_colour.blue() * ratio),
            )
        return colour

    def dock_position(self) -> tuple[float, float]:
        """Heart centre in stage coordinates: left of the orb, below the face."""
        width, height = self.width(), self.height()
        orb_centre_x = width / 2.0
        orb_centre_y = height - 26.0
        return (orb_centre_x - 52.0, orb_centre_y - 2.0)

    # ── painting ────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        del event
        width, height = self.width(), self.height()
        if width < 120 or height < 120:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        elapsed = time.monotonic() - self._started_at
        pulse_speed = 2.4 if self._low_battery else 0.42
        pulse = (math.sin(elapsed * 2.0 * math.pi * pulse_speed) + 1.0) * 0.5
        breath = 1.0 if self._reduced_motion else 1.0 + 0.055 * math.sin(elapsed * 2.0 * math.pi * pulse_speed)
        colour = self._cycle_color(elapsed)
        boost = 1.18 if self._state in ("SPEAKING", "THINKING") else 1.0
        boost *= 1.0 + 0.25 * self._energy

        charge = 1.0
        if self.charge_pulse_active() and self._charge_pulse_started is not None:
            progress = (time.monotonic() - self._charge_pulse_started) / self.CHARGE_PULSE_SECONDS
            charge = 1.0 + 0.9 * (1.0 - progress)

        cx, cy = self.dock_position()
        size = 26.0 * breath * (1.06 if self.charge_pulse_active() else 1.0)

        # Aura.
        aura_radius = 40.0 * breath * charge
        aura = QRadialGradient(QPointF(cx, cy), aura_radius)
        centre_colour = QColor(colour)
        centre_colour.setAlpha(min(255, int((30 + 20 * pulse) * boost * self._glow)))
        aura.setColorAt(0.0, centre_colour)
        aura.setColorAt(0.55, QColor(colour.red(), colour.green(), colour.blue(), 10))
        aura.setColorAt(1.0, QColor(colour.red(), colour.green(), colour.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(aura))
        painter.drawEllipse(QPointF(cx, cy), aura_radius, aura_radius)

        # Charging rings expand and fade — only during the plug-in pulse.
        if self.charge_pulse_active() and self._charge_pulse_started is not None:
            progress = (time.monotonic() - self._charge_pulse_started) / self.CHARGE_PULSE_SECONDS
            ring_radius = size * (1.4 + 2.2 * progress)
            ring_alpha = int(150 * (1.0 - progress) * self._glow)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(colour.red(), colour.green(), colour.blue(), max(0, ring_alpha)), 1.2))
            painter.drawEllipse(QPointF(cx, cy), ring_radius, ring_radius)

        # Conduits: short, local, and nowhere near the face.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        wire = QPen(QColor(colour.red(), colour.green(), colour.blue(),
                           int((60 + 26 * pulse) * boost)), 0.8)
        wire.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(wire)

        orb_anchor = QPointF(cx + 52.0, cy + 2.0)          # the status orb, to the right
        heart_anchor = QPointF(cx + size * 0.62, cy - size * 0.05)
        link = QPainterPath(heart_anchor)
        link.cubicTo(QPointF(cx + 22.0, cy - 10.0), QPointF(orb_anchor.x() - 26.0, orb_anchor.y() - 4.0), orb_anchor)
        painter.drawPath(link)

        # One dim filament rising to the chin of the face (a real anchor, not a
        # stub: the reactor feeds the head).
        if self._face_rect is not None and self._face_rect.isValid():
            chin = QPointF(self._face_rect.center().x(),
                           self._face_rect.bottom() - self._face_rect.height() * 0.06)
        else:
            chin = QPointF(cx + 26.0, cy - 120.0)
        filament = QPainterPath(QPointF(cx - size * 0.2, cy - size * 0.7))
        filament.cubicTo(
            QPointF(cx - 6.0, cy - 60.0),
            QPointF(chin.x() - 30.0, chin.y() + 90.0),
            chin,
        )
        painter.drawPath(filament)
        painter.setBrush(QBrush(QColor(colour.red(), colour.green(), colour.blue(), 150)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(chin, 1.8, 1.8)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(colour.red(), colour.green(), colour.blue(), int((95 + 45 * pulse) * boost))))
        painter.drawEllipse(heart_anchor, 1.7, 1.7)
        painter.drawEllipse(orb_anchor, 2.0, 2.0)

        # Heart shell.
        heart_width, heart_height = size * 1.02, size * 1.10
        left, top = cx - heart_width / 2.0, cy - heart_height / 2.0
        heart = QPainterPath()
        heart.moveTo(cx, top + heart_height * 0.27)
        heart.cubicTo(cx - heart_width * 0.10, top - heart_height * 0.02,
                      left - heart_width * 0.10, top + heart_height * 0.08,
                      left, top + heart_height * 0.36)
        heart.cubicTo(left + heart_width * 0.06, top + heart_height * 0.61,
                      cx - heart_width * 0.12, top + heart_height * 0.82,
                      cx, top + heart_height)
        heart.cubicTo(cx + heart_width * 0.12, top + heart_height * 0.82,
                      left + heart_width * 1.06, top + heart_height * 0.61,
                      left + heart_width, top + heart_height * 0.36)
        heart.cubicTo(left + heart_width * 1.10, top + heart_height * 0.08,
                      cx + heart_width * 0.10, top - heart_height * 0.02,
                      cx, top + heart_height * 0.27)
        heart.closeSubpath()
        painter.setBrush(QBrush(QColor(colour.red(), colour.green(), colour.blue(),
                                       int((22 + 12 * pulse) * boost * charge))))
        painter.setPen(QPen(QColor(colour.red(), colour.green(), colour.blue(),
                                   min(255, int((180 + 55 * pulse) * boost))), 1.05))
        painter.drawPath(heart)

        # Internal mesh.
        points = [
            QPointF(cx, top + heart_height * 0.27),
            QPointF(cx - heart_width * 0.29, top + heart_height * 0.38),
            QPointF(cx + heart_width * 0.29, top + heart_height * 0.38),
            QPointF(cx - heart_width * 0.18, top + heart_height * 0.62),
            QPointF(cx + heart_width * 0.18, top + heart_height * 0.62),
            QPointF(cx, top + heart_height * 0.84),
        ]
        painter.setPen(QPen(QColor(colour.red(), colour.green(), colour.blue(),
                                   min(255, int(150 * boost))), 0.75))
        for a, b in ((0, 1), (0, 2), (1, 2), (1, 3), (1, 4),
                     (2, 3), (2, 4), (3, 4), (3, 5), (4, 5)):
            painter.drawLine(points[a], points[b])

        # Reactor core.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 228, 236, min(255, 185 + int(50 * pulse)))))
        core = 2.1 + 0.6 * pulse
        painter.drawEllipse(QPointF(cx, cy + 1.0), core, core)

        # Tiny "charging" bolt, only while plugged in.
        if self._battery_available and self._battery_plugged:
            painter.setPen(QPen(QColor(255, 214, 150, 220), 1.0))
            x = cx + size * 0.78
            y = cy - size * 0.62
            bolt = QPainterPath(QPointF(x, y))
            bolt.lineTo(x - 3.4, y + 4.4)
            bolt.lineTo(x + 0.6, y + 4.4)
            bolt.lineTo(x - 2.6, y + 8.6)
            painter.drawPath(bolt)

        painter.end()
