"""Discrete state-transition energy pulse for the JARVIS hologram.

Each real state change triggers a short ring that expands outwards from the
supplied face bounds. The face interior is excluded by an annular clip path.
A single QTimer runs only while transient pulses are active; privacy lock uses
a quiet static ring and does not animate.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QObject, QRect, QRectF, Qt, QTimer, QPointF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QRadialGradient
from PyQt6.QtWidgets import QWidget

RGB = tuple[int, int, int]

_DEFAULT_PRIMARY_RGB: RGB = (255, 157, 77)
_DEFAULT_ACCENT_RGB: RGB = (255, 199, 120)
_DEFAULT_WARNING_RGB: RGB = (255, 104, 72)
_PEAK_ALPHA_CEILING = 200

_CATEGORY_PROFILE = {
    "gentle": {"duration": 0.90, "peak_alpha": 120, "max_extra": 0.55, "band": 0.09},
    "focus": {"duration": 0.50, "peak_alpha": 150, "max_extra": 0.35, "band": 0.06},
    "bright": {"duration": 0.70, "peak_alpha": 190, "max_extra": 0.65, "band": 0.10},
    "warning": {"duration": 0.80, "peak_alpha": 110, "max_extra": 0.45, "band": 0.08},
}
_WARNING_STATES = {
    "ERROR", "FAILED", "AUDIO_ERROR", "SESSION_ERROR",
    "DISCONNECTED", "OFFLINE", "CONNECTION_LOST",
}
_WARNING_COOLDOWN_SECONDS = 1.0


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge1 <= edge0:
        return 1.0 if value >= edge1 else 0.0
    t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _validate_rgb(value) -> RGB:
    if isinstance(value, (str, bytes)):
        raise TypeError("RGB value must be a three-item numeric sequence")
    try:
        channels = tuple(value)
    except TypeError:
        raise TypeError("RGB value must be a three-item numeric sequence") from None
    if len(channels) != 3:
        raise ValueError(f"RGB value must contain exactly three channels, got {len(channels)}")
    try:
        rgb = tuple(int(channel) for channel in channels)
    except (TypeError, ValueError, OverflowError):
        raise TypeError("RGB channels must be finite numeric values") from None
    return tuple(max(0, min(255, channel)) for channel in rgb)  # type: ignore[return-value]


def _categorize_transition(old_state: str, new_state: str) -> str:
    if new_state in _WARNING_STATES:
        return "warning"
    if old_state == "IDLE" and new_state == "LISTENING":
        return "gentle"
    if old_state == "LISTENING" and new_state == "THINKING":
        return "focus"
    if old_state == "THINKING" and new_state == "SPEAKING":
        return "bright"
    return "gentle"


@dataclass
class _Pulse:
    start: float
    duration: float
    peak_alpha: int
    max_extra: float
    band_half_width: float
    warning: bool


class HologramStatePulse(QWidget):
    """Transparent one-shot pulse overlay attached to a generic face widget."""

    GLOBAL_MARGIN = 1.65
    MAX_CONCURRENT_PULSES = 3

    def __init__(self, host: QWidget, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent if parent is not None else host)
        self._host = host
        self._bounds_provider: Optional[Callable[[], object]] = None
        self._explicit_bounds: Optional[QRectF] = None
        self._primary_rgb = _DEFAULT_PRIMARY_RGB
        self._accent_rgb = _DEFAULT_ACCENT_RGB
        self._warning_rgb = _DEFAULT_WARNING_RGB
        self._state = "IDLE"
        self._lock_static_active = False
        self._pulses: list[_Pulse] = []
        self._last_warning_trigger = float("-inf")
        self._enabled = True
        self._reduced_motion = False
        self._frame_interval_ms = 33
        self._glow_scale = 1.0

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
        # No timer while idle: _spawn_pulse starts it on demand.
        self.raise_()

    def set_bounds_provider(self, provider: Optional[Callable[[], object]]) -> None:
        """Supply a callable returning QRect or QRectF bounds in host coordinates."""
        if provider is not None and not callable(provider):
            raise TypeError("bounds provider must be callable or None")
        self._bounds_provider = provider
        self.update()

    def set_face_bounds(self, rect: Optional[QRect | QRectF]) -> None:
        """Set fallback bounds in host-local coordinates."""
        if rect is not None and not isinstance(rect, (QRect, QRectF)):
            raise TypeError("face bounds must be QRect, QRectF, or None")
        self._explicit_bounds = QRectF(rect) if rect is not None else None
        self.update()

    def set_colors(self, primary_rgb, accent_rgb) -> None:
        """Set persona colours using (red, green, blue) tuples."""
        self._primary_rgb = _validate_rgb(primary_rgb)
        self._accent_rgb = _validate_rgb(accent_rgb)
        self.update()

    def set_warning_color(self, warning_rgb) -> None:
        """Set the independent warning colour used for error/disconnect states."""
        self._warning_rgb = _validate_rgb(warning_rgb)
        self.update()

    @staticmethod
    def _normalize_state(state: Optional[str]) -> str:
        if state is None:
            return "IDLE"
        if not isinstance(state, str):
            raise TypeError(f"state must be str or None, got {type(state)!r}")
        normalized = state.strip().upper() or "IDLE"
        return "PRIVACY_LOCK" if normalized == "LOCKDOWN" else normalized

    def set_state(self, new_state: Optional[str]) -> None:
        """Report the current state; a visual pulse occurs only when it changes."""
        new_normalized = self._normalize_state(new_state)
        old_normalized = self._state
        if new_normalized != old_normalized:
            self.trigger_transition(old_normalized, new_normalized)

    def trigger_transition(self, old_state: Optional[str], new_state: Optional[str]) -> None:
        """Explicitly trigger one transition; equal state names are a no-op."""
        old_normalized = self._normalize_state(old_state)
        new_normalized = self._normalize_state(new_state)
        self._state = new_normalized

        if old_normalized == new_normalized:
            return

        # Privacy lock cancels existing motion and uses only a subdued static rim.
        if new_normalized == "PRIVACY_LOCK":
            self._pulses.clear()
            self._timer.stop()
            self._lock_static_active = self._enabled
            self.update()
            return

        if not self._enabled:
            self._lock_static_active = False
            return

        self._lock_static_active = False
        self._spawn_pulse(_categorize_transition(old_normalized, new_normalized))

    def set_reduced_motion(self, enabled: bool) -> None:
        """Shorten future pulses; an in-flight pulse keeps its current timing."""
        self._reduced_motion = bool(enabled)

    def set_performance_budget(
        self, frame_interval_ms: int, particle_scale: float, glow_scale: float
    ) -> None:
        """Apply the common hologram budget signature; there are no particles."""
        del particle_scale
        interval = max(16, min(200, int(frame_interval_ms)))
        value = float(glow_scale)
        if not math.isfinite(value):
            value = 1.0
        self._frame_interval_ms = interval
        self._glow_scale = max(0.0, min(1.0, value))
        if self._timer.isActive():
            self._timer.setInterval(interval)
        self.update()

    def set_enabled_effect(self, enabled: bool) -> None:
        """Disable and clear the overlay, or restore it for the current state."""
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if not enabled:
            self._pulses.clear()
            self._timer.stop()
            self._lock_static_active = False
            self.hide()
            return
        self.show()
        self.raise_()
        self._lock_static_active = self._state == "PRIVACY_LOCK"
        self.update()

    def active_pulse_count(self) -> int:
        """Expose the current bounded queue length for tests and diagnostics."""
        return len(self._pulses)

    def is_lock_static_active(self) -> bool:
        return self._lock_static_active

    def shutdown(self) -> None:
        """Stop animation and detach the event filter; safe to call repeatedly."""
        self._timer.stop()
        self._pulses.clear()
        try:
            self._host.removeEventFilter(self)
        except RuntimeError:
            # Qt's C++ host may already have been destroyed during application teardown.
            pass

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._host and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.setGeometry(0, 0, max(1, self._host.width()), max(1, self._host.height()))
        return False

    def _resolve_bounds(self) -> QRectF:
        if self._bounds_provider is not None:
            try:
                candidate = self._bounds_provider()
            except RuntimeError:
                # A deleted Qt object may invalidate a provider during teardown.
                candidate = None
            if isinstance(candidate, (QRect, QRectF)) and candidate.width() > 0 and candidate.height() > 0:
                return QRectF(candidate)

        if (
            self._explicit_bounds is not None
            and self._explicit_bounds.width() > 0
            and self._explicit_bounds.height() > 0
        ):
            return QRectF(self._explicit_bounds)

        try:
            return QRectF(self._host.rect())
        except RuntimeError:
            return QRectF()

    def _spawn_pulse(self, category: str) -> None:
        now = time.monotonic()
        if category == "warning":
            if now - self._last_warning_trigger < _WARNING_COOLDOWN_SECONDS:
                return
            self._last_warning_trigger = now

        profile = _CATEGORY_PROFILE[category]
        duration = profile["duration"]
        max_extra = profile["max_extra"]
        peak = profile["peak_alpha"]
        band = profile["band"]
        if self._reduced_motion:
            duration *= 0.35
            max_extra *= 0.18

        pulse = _Pulse(
            start=now,
            duration=max(0.05, duration),
            peak_alpha=peak,
            max_extra=max_extra,
            band_half_width=band,
            warning=(category == "warning"),
        )
        if len(self._pulses) >= self.MAX_CONCURRENT_PULSES:
            self._pulses.pop(0)
        self._pulses.append(pulse)
        if not self._timer.isActive():
            self._timer.start(self._frame_interval_ms)
        self.update()

    def _tick(self) -> None:
        now = time.monotonic()
        self._pulses = [pulse for pulse in self._pulses if now - pulse.start < pulse.duration]
        if not self._pulses:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        del event
        if not self._enabled or (not self._pulses and not self._lock_static_active):
            return
        bounds = self._resolve_bounds()
        if bounds.width() <= 0 or bounds.height() <= 0:
            return

        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        margin = self.GLOBAL_MARGIN
        outer_rect = QRectF(
            bounds.center().x() - bounds.width() * margin / 2.0,
            bounds.center().y() - bounds.height() * margin / 2.0,
            bounds.width() * margin,
            bounds.height() * margin,
        )
        outer_path = QPainterPath()
        outer_path.addEllipse(outer_rect)
        inner_path = QPainterPath()
        inner_path.addEllipse(bounds)
        painter.setClipPath(outer_path.subtracted(inner_path))

        primary = QColor(*self._primary_rgb)
        accent = QColor(*self._accent_rgb)
        warning = QColor(*self._warning_rgb)

        if self._lock_static_active:
            self._draw_ring(painter, bounds, 1.0, 0.05, primary, primary, int(48 * self._glow_scale))
        else:
            now = time.monotonic()
            for pulse in tuple(self._pulses):
                elapsed = max(0.0, now - pulse.start)
                progress = max(0.0, min(1.0, elapsed / pulse.duration))
                fade_in = _smoothstep(0.0, 0.08, progress)
                envelope = fade_in * ((1.0 - progress) ** 1.4)
                peak_alpha = int(
                    min(_PEAK_ALPHA_CEILING, pulse.peak_alpha) * envelope * self._glow_scale
                )
                radius = 1.0 + pulse.max_extra * (1.0 - (1.0 - progress) ** 3)
                band = pulse.band_half_width * (1.0 - 0.3 * progress)
                base = warning if pulse.warning else primary
                ring = warning if pulse.warning else accent
                self._draw_ring(painter, bounds, radius, band, base, ring, peak_alpha)

        painter.end()

    def _draw_ring(
        self,
        painter: QPainter,
        bounds: QRectF,
        radius: float,
        band_half_width: float,
        base_colour: QColor,
        ring_colour: QColor,
        peak_alpha: int,
    ) -> None:
        if peak_alpha <= 0:
            return

        margin = self.GLOBAL_MARGIN
        # Clamp the brightest radius to the face edge or farther out.
        radius = max(1.0, min(margin, radius))
        inner = max(1.0, radius - band_half_width)
        outer = min(margin, radius + band_half_width * 1.6)

        def stop(value: float) -> float:
            return max(0.0, min(1.0, value / margin))

        rx = bounds.width() / 2.0
        ry = bounds.height() / 2.0
        if rx <= 0.0 or ry <= 0.0:
            return

        painter.save()
        painter.translate(bounds.center())
        painter.scale(rx * margin, ry * margin)

        gradient = QRadialGradient(QPointF(0.0, 0.0), 1.0)
        gradient.setColorAt(0.0, QColor(base_colour.red(), base_colour.green(), base_colour.blue(), 0))
        gradient.setColorAt(stop(inner), QColor(base_colour.red(), base_colour.green(), base_colour.blue(), 0))
        gradient.setColorAt(stop(radius), QColor(ring_colour.red(), ring_colour.green(), ring_colour.blue(), peak_alpha))
        gradient.setColorAt(stop(outer), QColor(base_colour.red(), base_colour.green(), base_colour.blue(), 0))
        gradient.setColorAt(1.0, QColor(base_colour.red(), base_colour.green(), base_colour.blue(), 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(0.0, 0.0), 1.0, 1.0)
        painter.restore()
