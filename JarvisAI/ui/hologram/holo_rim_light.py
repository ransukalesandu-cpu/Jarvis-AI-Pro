"""Voice-reactive neural rim light for the modular hologram panel.

This transparent child widget draws a restrained elliptical rim around a
host-provided face bounding box. The ring is clipped to an annulus outside the
face boundary, leaving the face interior untouched.

The widget only depends on PyQt6 and the Python standard library. Host geometry,
persona colours, state, audio energy, reduced-motion preference, and performance
budget are supplied explicitly by the composing UI.
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QRadialGradient
from PyQt6.QtWidgets import QWidget

RGB = tuple[int, int, int]

_DEFAULT_PRIMARY_RGB: RGB = (255, 157, 77)
_DEFAULT_ACCENT_RGB: RGB = (255, 199, 115)

_STATE_PROFILE = {
    "IDLE": {"base": 0.20, "breathe_amp": 0.05, "breathe_hz": 0.20, "audio_gain": 0.0},
    "LISTENING": {"base": 0.26, "breathe_amp": 0.0, "breathe_hz": 0.0, "audio_gain": 0.55},
    "THINKING": {"base": 0.38, "breathe_amp": 0.10, "breathe_hz": 0.55, "audio_gain": 0.0},
    "SPEAKING": {"base": 0.28, "breathe_amp": 0.0, "breathe_hz": 0.0, "audio_gain": 0.62},
    "_default": {"base": 0.12, "breathe_amp": 0.0, "breathe_hz": 0.0, "audio_gain": 0.10},
}

_PEAK_ALPHA_MAX = 190


def _rgb(value, fallback: RGB) -> RGB:
    """Return a clamped RGB tuple, falling back for malformed palette data."""
    try:
        channels = tuple(int(channel) for channel in value[:3])
        if len(channels) != 3:
            return fallback
        return tuple(max(0, min(255, channel)) for channel in channels)  # type: ignore[return-value]
    except (TypeError, ValueError, IndexError):
        return fallback


class NeuralRimLight(QWidget):
    """A low-cost audio-reactive glow placed over a generic host widget."""

    def __init__(self, host: QWidget, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent if parent is not None else host)
        self._host = host
        self._bounds_provider: Optional[Callable[[], QRectF]] = None
        self._primary_rgb = _DEFAULT_PRIMARY_RGB
        self._accent_rgb = _DEFAULT_ACCENT_RGB
        self._state = "IDLE"
        self._audio_energy = 0.0
        self._target_energy = 0.0
        self._enabled = True
        self._reduced_motion = False
        self._frame_interval_ms = 33
        self._glow_scale = 1.0
        self._start_time = time.monotonic()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(0, 0, max(1, host.width()), max(1, host.height()))
        host.installEventFilter(self)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self._frame_interval_ms)
        self.raise_()

    def set_bounds_provider(self, provider: Optional[Callable[[], QRectF]]) -> None:
        """Set a callable returning the ring bounds in host-local coordinates."""
        self._bounds_provider = provider
        self.update()

    def set_colors(self, primary_rgb: RGB, accent_rgb: RGB) -> None:
        """Set primary and highlight RGB colours, each as a three-item tuple."""
        self._primary_rgb = _rgb(primary_rgb, _DEFAULT_PRIMARY_RGB)
        self._accent_rgb = _rgb(accent_rgb, _DEFAULT_ACCENT_RGB)
        self.update()

    def set_state(self, state: str) -> None:
        """Set IDLE, LISTENING, THINKING, SPEAKING, or an unknown state."""
        self._state = str(state or "IDLE").upper()
        self.update()

    def set_audio_energy(self, level: float) -> None:
        """Feed normalized real audio energy in the range 0.0 to 1.0."""
        try:
            energy = float(level)
            if not math.isfinite(energy):
                energy = 0.0
            self._target_energy = max(0.0, min(1.0, energy))
        except (TypeError, ValueError):
            self._target_energy = 0.0

    def set_reduced_motion(self, enabled: bool) -> None:
        """Disable decorative breathing while keeping audio-reactive intensity."""
        self._reduced_motion = bool(enabled)
        self.update()

    def set_performance_budget(
        self, frame_interval_ms: int, particle_scale: float, glow_scale: float
    ) -> None:
        """Apply the common hologram budget signature; particle_scale is unused."""
        del particle_scale
        try:
            interval = max(16, min(200, int(frame_interval_ms)))
        except (TypeError, ValueError):
            interval = 33
        try:
            scale = float(glow_scale)
            if not math.isfinite(scale):
                scale = 1.0
        except (TypeError, ValueError):
            scale = 1.0
        self._frame_interval_ms = interval
        self._glow_scale = max(0.0, min(1.0, scale))
        # setInterval preserves a stopped timer rather than accidentally
        # restarting animation after set_enabled_effect(False).
        self._timer.setInterval(interval)
        self.update()

    def set_enabled_effect(self, enabled: bool) -> None:
        """Enable or hide the effect without destroying the widget."""
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if enabled:
            self.show()
            self._timer.start(self._frame_interval_ms)
        else:
            self._timer.stop()
            self.hide()
        self.update()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._host and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.setGeometry(0, 0, max(1, self._host.width()), max(1, self._host.height()))
        return False

    def _resolve_bounds(self) -> QRectF:
        if self._bounds_provider is not None:
            try:
                rect = self._bounds_provider()
                if rect is not None and rect.width() > 0 and rect.height() > 0:
                    return QRectF(rect)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        return QRectF(self._host.rect())

    def _current_alpha_fraction(self) -> float:
        profile = _STATE_PROFILE.get(self._state, _STATE_PROFILE["_default"])
        elapsed = time.monotonic() - self._start_time
        value = profile["base"]
        if not self._reduced_motion and profile["breathe_amp"] > 0.0:
            phase = elapsed * profile["breathe_hz"] * 2.0 * math.pi
            value += profile["breathe_amp"] * (0.5 + 0.5 * math.sin(phase))
        value += profile["audio_gain"] * self._audio_energy
        return max(0.0, min(1.0, value))

    def _tick(self) -> None:
        difference = self._target_energy - self._audio_energy
        if abs(difference) < 0.002:
            self._audio_energy = self._target_energy
        else:
            self._audio_energy += difference * 0.25
        if self._enabled:
            self.update()

    def paintEvent(self, event) -> None:
        del event
        if not self._enabled:
            return

        bounds = self._resolve_bounds()
        if bounds.width() <= 0.0 or bounds.height() <= 0.0:
            return

        fraction = self._current_alpha_fraction()
        peak_alpha = int(_PEAK_ALPHA_MAX * fraction * self._glow_scale)
        if peak_alpha <= 0:
            return

        primary = QColor(*self._primary_rgb)
        accent = QColor(*self._accent_rgb)

        # Draw in normalized ellipse coordinates. The inner path represents
        # the supplied face bounds; the annulus only permits painting outside
        # that boundary. The centre/face interior is therefore never painted.
        margin = 1.12
        edge_radius = 1.0 / margin
        rx = bounds.width() / 2.0
        ry = bounds.height() / 2.0
        if rx <= 0.0 or ry <= 0.0:
            return

        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.save()
        painter.translate(bounds.center())
        painter.scale(rx * margin, ry * margin)

        annulus = QPainterPath()
        annulus.setFillRule(Qt.FillRule.OddEvenFill)
        annulus.addEllipse(QRectF(-1.0, -1.0, 2.0, 2.0))
        annulus.addEllipse(
            QRectF(-edge_radius, -edge_radius, 2.0 * edge_radius, 2.0 * edge_radius)
        )

        gradient = QRadialGradient(QPointF(0.0, 0.0), 1.0)
        gradient.setColorAt(0.0, QColor(primary.red(), primary.green(), primary.blue(), 0))
        gradient.setColorAt(max(0.0, edge_radius - 0.002), QColor(primary.red(), primary.green(), primary.blue(), 0))
        gradient.setColorAt(edge_radius, QColor(accent.red(), accent.green(), accent.blue(), peak_alpha))
        gradient.setColorAt(1.0, QColor(primary.red(), primary.green(), primary.blue(), 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(annulus)
        painter.restore()
        painter.end()
