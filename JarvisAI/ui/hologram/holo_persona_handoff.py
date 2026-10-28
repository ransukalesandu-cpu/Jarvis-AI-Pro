"""Persona-switch chromatic handoff overlay for PyQt6 hologram faces.

This module is deliberately independent of the Jarvis-AI-Pro project. It paints
only in the annulus outside caller-supplied face bounds and runs one timer only
while a handoff is active. It neither creates a face nor modifies its graphics
effects, audio, authentication, or command logic.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

RGB = tuple[int, int, int]

DEFAULT_DURATION_MS = 550
MIN_DURATION_MS = 400
MAX_DURATION_MS = 700
REDUCED_MOTION_DURATION_MS = 260
PRIVACY_LOCK_DURATION_MS = 180

GLOBAL_MARGIN = 1.22
ARC_COUNT = 3
ARC_SPAN_DEGREES = 46.0
ARC_ROTATION_DEGREES = 95.0
PEAK_ALPHA_MAX = 170
REDUCED_ALPHA_MAX = 102
PRIVACY_ALPHA_MAX = 50
ARC_WIDTH_SCALE = 0.009


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _validate_rgb(value: RGB, label: str) -> RGB:
    if not isinstance(value, tuple) or len(value) != 3:
        raise TypeError(f"{label} must be a three-item RGB tuple")
    channels = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise TypeError(f"{label} channels must be numeric")
        component = float(component)
        if not math.isfinite(component):
            raise ValueError(f"{label} channels must be finite")
        channels.append(int(_clamp(round(component), 0, 255)))
    return channels[0], channels[1], channels[2]


def _lerp_rgb(old: RGB, new: RGB, t: float) -> RGB:
    return tuple(
        int(round(a + (b - a) * t))
        for a, b in zip(old, new)
    )  # type: ignore[return-value]


def _ease_in_out_cubic(t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


@dataclass
class _HandoffState:
    old_primary: RGB
    old_accent: RGB
    new_primary: RGB
    new_accent: RGB
    start_time: float
    duration_s: float
    base_rotation_deg: float
    profile: str  # "normal", "reduced", or "privacy"


class PersonaChromaticHandoff(QWidget):
    """One-shot colour handoff overlay hosted by a stable face container.

    The parent/host may be a face widget or a common container such as a
    QStackedWidget. The bounds provider must return a face rectangle in this
    overlay's local coordinate space.
    """

    def __init__(self, host: QWidget, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent if parent is not None else host)
        self._host = host
        self._bounds_provider: Optional[Callable[[], object]] = None
        self._explicit_bounds: Optional[QRectF] = None
        self._enabled = True
        self._reduced_motion = False
        self._privacy_lock_active = False
        self._frame_interval_ms = 16
        self._glow_scale = 1.0
        self._state: Optional[_HandoffState] = None

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)
        self._sync_geometry()
        self._host.installEventFilter(self)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(self._frame_interval_ms)
        self._timer.timeout.connect(self._tick)
        self.hide()

    # ---- Host and geometry -------------------------------------------------
    def set_bounds_provider(self, provider: Optional[Callable[[], object]]) -> None:
        if provider is not None and not callable(provider):
            raise TypeError("bounds provider must be callable or None")
        self._bounds_provider = provider
        self.update()

    def set_face_bounds(self, rect: Optional[QRect | QRectF]) -> None:
        if rect is not None and not isinstance(rect, (QRect, QRectF)):
            raise TypeError("face bounds must be QRect, QRectF, or None")
        self._explicit_bounds = QRectF(rect) if rect is not None else None
        self.update()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt override)
        if watched is self._host and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self._sync_geometry()
        return False

    def _sync_geometry(self) -> None:
        try:
            self.setGeometry(self._host.rect())
        except RuntimeError:
            # The host's Qt object can disappear during teardown.
            return

    def _resolve_bounds(self) -> Optional[QRectF]:
        if self._explicit_bounds is not None:
            return QRectF(self._explicit_bounds)
        if self._bounds_provider is None:
            return None
        try:
            raw = self._bounds_provider()
        except RuntimeError:
            # Only suppress the known Qt teardown case; caller errors propagate.
            return None
        if raw is None:
            return None
        if isinstance(raw, (QRect, QRectF)):
            return QRectF(raw)
        return QRectF(raw.x(), raw.y(), raw.width(), raw.height())

    # ---- Configuration -----------------------------------------------------
    def set_reduced_motion(self, enabled: bool) -> None:
        """Configure handoffs started after this call."""
        self._reduced_motion = bool(enabled)

    def set_privacy_lock_active(self, active: bool) -> None:
        """Use the dim, static privacy profile; shorten an active effect too."""
        active = bool(active)
        if active == self._privacy_lock_active:
            return
        self._privacy_lock_active = active
        if active and self._state is not None:
            now = time.monotonic()
            current_primary, current_accent = self._current_colors(now)
            previous = self._state
            self._state = _HandoffState(
                old_primary=current_primary,
                old_accent=current_accent,
                new_primary=previous.new_primary,
                new_accent=previous.new_accent,
                start_time=now,
                duration_s=PRIVACY_LOCK_DURATION_MS / 1000.0,
                base_rotation_deg=0.0,
                profile="privacy",
            )
            self._ensure_timer_running()
            self.update()

    def set_performance_budget(
        self,
        frame_interval_ms: Optional[int] = None,
        particle_scale: Optional[float] = None,
        glow_scale: Optional[float] = None,
    ) -> None:
        """Apply the shared hologram budget shape; particles are not used here."""
        del particle_scale
        if frame_interval_ms is not None:
            self._frame_interval_ms = max(8, min(200, int(frame_interval_ms)))
            self._timer.setInterval(self._frame_interval_ms)
        if glow_scale is not None:
            scale = float(glow_scale)
            if not math.isfinite(scale):
                scale = 1.0
            self._glow_scale = _clamp(scale, 0.0, 1.0)
        self.update()

    def set_enabled_effect(self, enabled: bool) -> None:
        """Disable and clear the one-shot effect; idle overlays remain hidden."""
        self._enabled = bool(enabled)
        if not self._enabled:
            self._cancel_active()
        elif self._state is None:
            self.hide()

    # ---- Explicit persona-switch trigger ----------------------------------
    def trigger_handoff(
        self,
        old_primary_rgb: RGB,
        old_accent_rgb: RGB,
        new_primary_rgb: RGB,
        new_accent_rgb: RGB,
        duration_ms: Optional[int] = None,
    ) -> None:
        old_primary_rgb = _validate_rgb(old_primary_rgb, "old_primary_rgb")
        old_accent_rgb = _validate_rgb(old_accent_rgb, "old_accent_rgb")
        new_primary_rgb = _validate_rgb(new_primary_rgb, "new_primary_rgb")
        new_accent_rgb = _validate_rgb(new_accent_rgb, "new_accent_rgb")
        if not self._enabled:
            return

        if (
            self._state is not None
            and self._state.new_primary == new_primary_rgb
            and self._state.new_accent == new_accent_rgb
        ):
            return  # duplicate notification for the same target

        now = time.monotonic()
        if self._state is not None:
            # Retarget from the currently displayed blend, never from stale input.
            start_primary, start_accent = self._current_colors(now)
            base_rotation = self._current_rotation(now)
        else:
            start_primary, start_accent = old_primary_rgb, old_accent_rgb
            base_rotation = 0.0

        if self._privacy_lock_active:
            profile = "privacy"
            duration_s = PRIVACY_LOCK_DURATION_MS / 1000.0
            base_rotation = 0.0
        elif self._reduced_motion:
            profile = "reduced"
            requested = REDUCED_MOTION_DURATION_MS if duration_ms is None else int(duration_ms)
            duration_s = max(80, requested) / 1000.0
            base_rotation = 0.0
        else:
            profile = "normal"
            requested = DEFAULT_DURATION_MS if duration_ms is None else int(duration_ms)
            duration_s = _clamp(requested, MIN_DURATION_MS, MAX_DURATION_MS) / 1000.0

        self._state = _HandoffState(
            old_primary=start_primary,
            old_accent=start_accent,
            new_primary=new_primary_rgb,
            new_accent=new_accent_rgb,
            start_time=now,
            duration_s=max(0.001, duration_s),
            base_rotation_deg=base_rotation,
            profile=profile,
        )
        self._sync_geometry()
        self.show()
        self.raise_()
        self._ensure_timer_running()
        self.update()

    def reverse_active_handoff(self) -> None:
        """Reverse an active handoff from its current blended colour."""
        if self._state is None:
            return
        now = time.monotonic()
        primary, accent = self._current_colors(now)
        previous = self._state
        rotation = self._current_rotation(now)
        self._state = _HandoffState(
            old_primary=primary,
            old_accent=accent,
            new_primary=previous.old_primary,
            new_accent=previous.old_accent,
            start_time=now,
            duration_s=previous.duration_s,
            base_rotation_deg=rotation,
            profile=previous.profile,
        )
        self._ensure_timer_running()
        self.update()

    def active(self) -> bool:
        return self._state is not None

    def shutdown(self) -> None:
        """Idempotent teardown; tolerate only Qt objects already being destroyed."""
        try:
            self._timer.stop()
        except RuntimeError:
            pass
        self._state = None
        try:
            self._host.removeEventFilter(self)
        except RuntimeError:
            pass
        try:
            self.hide()
        except RuntimeError:
            pass

    # ---- Animation lifecycle ----------------------------------------------
    def _ensure_timer_running(self) -> None:
        if not self._timer.isActive():
            self._timer.setInterval(self._frame_interval_ms)
            self._timer.start()

    def _cancel_active(self) -> None:
        self._state = None
        try:
            self._timer.stop()
            self.hide()
        except RuntimeError:
            pass

    def _progress(self, now: float) -> float:
        if self._state is None:
            return 1.0
        return _clamp((now - self._state.start_time) / self._state.duration_s, 0.0, 1.0)

    def _current_colors(self, now: float) -> tuple[RGB, RGB]:
        if self._state is None:
            return (255, 157, 77), (255, 199, 120)
        eased = _ease_in_out_cubic(self._progress(now))
        return (
            _lerp_rgb(self._state.old_primary, self._state.new_primary, eased),
            _lerp_rgb(self._state.old_accent, self._state.new_accent, eased),
        )

    def _current_rotation(self, now: float) -> float:
        if self._state is None or self._state.profile != "normal":
            return 0.0
        return (
            self._state.base_rotation_deg
            + ARC_ROTATION_DEGREES * self._progress(now)
        )

    def _tick(self) -> None:
        if self._state is None:
            self._timer.stop()
            self.hide()
            return
        if self._progress(time.monotonic()) >= 1.0:
            self._state = None
            self._timer.stop()
            self.hide()
            return
        self.update()

    # ---- Annular clipping and paint ---------------------------------------
    def _annulus_clip_path(self, bounds: QRectF) -> QPainterPath:
        """Subtract the exact face ellipse from a slightly larger outer ellipse."""
        cx, cy = bounds.center().x(), bounds.center().y()
        rx, ry = bounds.width() / 2.0, bounds.height() / 2.0
        outer = QPainterPath()
        outer.addEllipse(
            cx - rx * GLOBAL_MARGIN,
            cy - ry * GLOBAL_MARGIN,
            rx * 2.0 * GLOBAL_MARGIN,
            ry * 2.0 * GLOBAL_MARGIN,
        )
        inner = QPainterPath()
        inner.addEllipse(cx - rx, cy - ry, rx * 2.0, ry * 2.0)
        return outer.subtracted(inner)

    @staticmethod
    def _ring_radius(bounds: QRectF) -> float:
        rx, ry = bounds.width() / 2.0, bounds.height() / 2.0
        return (rx + ry) * 0.5 * ((1.0 + GLOBAL_MARGIN) * 0.5)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        del event
        state = self._state
        if state is None or not self._enabled:
            return
        bounds = self._resolve_bounds()
        if bounds is None or bounds.width() <= 0 or bounds.height() <= 0:
            return

        progress = self._progress(time.monotonic())
        eased = _ease_in_out_cubic(progress)
        primary, accent = self._current_colors(time.monotonic())
        if eased < 0.2:
            envelope = eased / 0.2
        elif eased > 0.75:
            envelope = (1.0 - eased) / 0.25
        else:
            envelope = 1.0
        envelope = _clamp(envelope, 0.0, 1.0)

        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipPath(self._annulus_clip_path(bounds))
        try:
            if state.profile == "privacy":
                self._paint_static_ring(painter, bounds, primary, envelope, PRIVACY_ALPHA_MAX, 0.003)
            elif state.profile == "reduced":
                self._paint_static_ring(painter, bounds, primary, envelope, REDUCED_ALPHA_MAX, 0.005)
            else:
                self._paint_sweeping_arcs(painter, bounds, primary, accent, envelope)
        finally:
            painter.end()

    def _paint_static_ring(
        self,
        painter: QPainter,
        bounds: QRectF,
        primary: RGB,
        envelope: float,
        alpha_ceiling: int,
        width_scale: float,
    ) -> None:
        cx, cy = bounds.center().x(), bounds.center().y()
        radius = self._ring_radius(bounds)
        alpha = int(_clamp(alpha_ceiling * envelope * self._glow_scale, 0, alpha_ceiling))
        if alpha <= 0:
            return
        pen = QPen(QColor(primary[0], primary[1], primary[2], alpha))
        pen.setWidthF(max(1.0, min(bounds.width(), bounds.height()) * width_scale))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0))

    def _paint_sweeping_arcs(
        self,
        painter: QPainter,
        bounds: QRectF,
        primary: RGB,
        accent: RGB,
        envelope: float,
    ) -> None:
        cx, cy = bounds.center().x(), bounds.center().y()
        radius = self._ring_radius(bounds)
        rotation = self._current_rotation(time.monotonic())
        alpha = int(_clamp(PEAK_ALPHA_MAX * envelope * self._glow_scale, 0, PEAK_ALPHA_MAX))
        if alpha <= 0:
            return
        rect = QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0)
        width = max(1.0, min(bounds.width(), bounds.height()) * ARC_WIDTH_SCALE)
        for index in range(ARC_COUNT):
            rgb = primary if index % 2 == 0 else accent
            start = rotation + (360.0 / ARC_COUNT) * index
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # A low-alpha broad stroke gives a restrained glow without effects on the host.
            glow = QPen(QColor(rgb[0], rgb[1], rgb[2], int(alpha * 0.24)))
            glow.setWidthF(width * 2.4)
            glow.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(glow)
            painter.drawArc(rect, int(start * 16), int(ARC_SPAN_DEGREES * 16))
            core = QPen(QColor(rgb[0], rgb[1], rgb[2], alpha))
            core.setWidthF(width)
            core.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(core)
            painter.drawArc(rect, int(start * 16), int(ARC_SPAN_DEGREES * 16))
