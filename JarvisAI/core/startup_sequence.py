"""Premium, lightweight, code-drawn JARVIS startup experience.

The splash uses Qt painting rather than a browser/video renderer. This is
intentional: the main UI loads Qt WebEngine lazily, and starting a second
Chromium renderer just for a splash would increase launch time and RAM.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient, QLinearGradient
from PyQt6.QtWidgets import QWidget


class StartupSequenceSplash(QWidget):
    """Fullscreen cinematic boot screen; emits finished exactly once."""

    finished = pyqtSignal()

    DURATION_MS = 6500
    TITLE_HOLD_MS = 1000
    TITLE_FADE_END_MS = 1550
    FRAME_INTERVAL_MS = 16

    _BG = QColor("#03070b")
    _CYAN = QColor("#78e8e5")
    _PALE = QColor("#d9ffff")
    _MUTED = QColor("#75a9ae")
    _COPPER = QColor("#d99469")

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("JARVIS")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(self.FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._done = False
        self._elapsed = 0

    def start(self) -> None:
        self._elapsed = 0
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self._clock.start()
        self._timer.start()
        self.setFocus()

    def _tick(self) -> None:
        self._elapsed = self._clock.elapsed()
        self.update()
        if self._elapsed >= self.DURATION_MS:
            self.finish()

    def finish(self) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self.close()
        self.finished.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() in (
            Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.finish()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

    @classmethod
    def _ease(cls, value: float) -> float:
        value = cls._clamp(value)
        return value * value * (3.0 - 2.0 * value)

    @staticmethod
    def _font(size: int, weight=QFont.Weight.Normal, family="Segoe UI") -> QFont:
        font = QFont(family, max(1, size))
        font.setWeight(weight)
        return font

    def _draw_title(self, p: QPainter, w: int, h: int, elapsed: int) -> None:
        # First second is deliberately just the JARVIS wordmark on black.
        fade = self._ease((elapsed - self.TITLE_HOLD_MS) /
                          (self.TITLE_FADE_END_MS - self.TITLE_HOLD_MS))
        alpha = int(255 * (1.0 - fade))
        p.setPen(QColor(222, 255, 255, alpha))
        font = self._font(max(30, int(min(w, h) * .078)), QFont.Weight.Light)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 15)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "JARVIS")

    def _draw_corner_marks(self, p: QPainter, w: int, h: int, alpha: int) -> None:
        p.setPen(QPen(QColor(104, 222, 224, alpha), 1.2))
        inset, length = 30, 34
        for x, sx in ((inset, 1), (w - inset, -1)):
            for y, sy in ((inset, 1), (h - inset, -1)):
                p.drawLine(x, y, x + sx * length, y)
                p.drawLine(x, y, x, y + sy * length)

    def _draw_background(self, p: QPainter, w: int, h: int,
                         reveal: float, elapsed: int) -> None:
        glow = QRadialGradient(QPointF(w * .5, h * .46), max(w, h) * .68)
        glow.setColorAt(0.0, QColor(10, 35, 43, int(100 * reveal)))
        glow.setColorAt(.55, QColor(5, 17, 24, int(60 * reveal)))
        glow.setColorAt(1.0, self._BG)
        p.fillRect(self.rect(), glow)

        alpha = int(22 * reveal)
        p.setPen(QPen(QColor(73, 177, 190, alpha), 1))
        step = 56
        offset = int((elapsed * .012) % step)
        for x in range(-step + offset, w + step, step):
            p.drawLine(x, 0, x, h)
        for y in range(-step + offset, h + step, step):
            p.drawLine(0, y, w, y)
        self._draw_corner_marks(p, w, h, int(115 * reveal))

    def _draw_particles(self, p: QPainter, w: int, h: int,
                        reveal: float, elapsed: int) -> None:
        # Deterministic particles: no random allocations on the 60 fps path.
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(42):
            x0 = ((i * 197 + 37) % 997) / 997.0 * w
            y0 = ((i * 313 + 91) % 991) / 991.0 * h
            drift = elapsed * (0.004 + (i % 5) * .001)
            x = (x0 + math.sin(drift + i) * 13) % max(1, w)
            y = (y0 - drift * (5 + i % 4)) % max(1, h)
            pulse = .45 + .55 * math.sin(elapsed * .002 + i * 1.7) ** 2
            alpha = int(105 * reveal * pulse)
            p.setBrush(QColor(112, 225, 226, alpha))
            radius = 1.0 + (i % 3) * .45
            p.drawEllipse(QPointF(x, y), radius, radius)

    def _draw_reactor(self, p: QPainter, cx: float, cy: float,
                      radius: float, reveal: float, elapsed: int) -> None:
        pulse = .94 + .06 * math.sin(elapsed * .003)
        r = radius * pulse
        p.save()
        p.translate(cx, cy)

        aura = QRadialGradient(QPointF(0, 0), r * 1.9)
        aura.setColorAt(0.0, QColor(49, 201, 211, int(32 * reveal)))
        aura.setColorAt(.62, QColor(28, 136, 158, int(15 * reveal)))
        aura.setColorAt(1.0, QColor(12, 70, 90, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(aura)
        p.drawEllipse(QPointF(0, 0), r * 1.9, r * 1.9)

        for idx, (scale, start, span, color, width) in enumerate((
            (1.0, elapsed * .045, 104, self._CYAN, 2.0),
            (.82, -elapsed * .062, 146, self._COPPER, 1.3),
            (.64, elapsed * .085 + 120, 72, self._PALE, 1.0),
        )):
            p.setBrush(Qt.BrushStyle.NoBrush)
            pen_color = QColor(color)
            pen_color.setAlpha(int((175 if idx == 0 else 115) * reveal))
            p.setPen(QPen(pen_color, width))
            rect = QRectF(-r * scale, -r * scale, r * 2 * scale, r * 2 * scale)
            p.drawArc(rect, int(start * 16), int(span * 16))

        p.setPen(QPen(QColor(116, 231, 231, int(95 * reveal)), 1))
        p.drawEllipse(QRectF(-r * .46, -r * .46, r * .92, r * .92))
        p.drawLine(QPointF(-r * 1.2, 0), QPointF(r * 1.2, 0))
        p.drawLine(QPointF(0, -r * 1.2), QPointF(0, r * 1.2))

        p.setPen(QColor(226, 255, 255, int(235 * reveal)))
        p.setFont(self._font(max(12, int(r * .20)), QFont.Weight.Light))
        p.drawText(QRectF(-r * .65, -r * .22, r * 1.3, r * .44),
                   Qt.AlignmentFlag.AlignCenter, "J")
        p.restore()

    def _draw_readouts(self, p: QPainter, w: int, h: int,
                       reveal: float, progress: float) -> None:
        alpha = int(190 * reveal)
        left_x = max(34, int(w * .095))
        right_x = min(w - 210, int(w * .78))
        top = int(h * .34)
        p.setFont(self._font(9, QFont.Weight.DemiBold, "Consolas"))
        p.setPen(QColor(108, 191, 198, alpha))
        p.drawText(left_x, top, "BOOT SEQUENCE")
        p.drawText(left_x, top + 19, "CORE / 01")
        p.drawText(right_x, top, "SYSTEM STATUS")
        p.drawText(right_x, top + 19, f"{int(progress * 100):02d}%")

        stages = (
            ("NEURAL INTERFACE", .20),
            ("CORE SYNCHRONIZATION", .46),
            ("HOLOGRAPHIC MATRIX", .72),
            ("VOICE CHANNEL", .91),
        )
        for name, threshold in stages:
            y = top + 48 + stages.index((name, threshold)) * 25
            active = progress >= threshold
            p.setPen(QColor(129, 235, 218, alpha) if active
                     else QColor(82, 125, 133, int(105 * reveal)))
            p.drawText(left_x, y, ("✓  " if active else "·  ") + name)

        p.setPen(QColor(100, 171, 181, int(150 * reveal)))
        p.drawText(right_x, top + 48, "SECURE LINK")
        p.setPen(QColor(133, 220, 201, alpha))
        p.drawText(right_x, top + 66, "ENCRYPTED  /  READY")

    def _draw_boot(self, p: QPainter, w: int, h: int,
                   elapsed: int, reveal: float) -> None:
        progress = self._ease(
            (elapsed - self.TITLE_FADE_END_MS) /
            (self.DURATION_MS - self.TITLE_FADE_END_MS)
        )
        cx, cy = w * .5, h * .43
        radius = min(w, h) * (.105 + .035 * progress)
        self._draw_background(p, w, h, reveal, elapsed)
        self._draw_particles(p, w, h, reveal, elapsed)

        scan_y = (elapsed * .16) % max(1, h)
        scan = QLinearGradient(0, scan_y - 22, 0, scan_y + 22)
        scan.setColorAt(0.0, QColor(70, 200, 210, 0))
        scan.setColorAt(.5, QColor(70, 200, 210, int(15 * reveal)))
        scan.setColorAt(1.0, QColor(70, 200, 210, 0))
        p.fillRect(QRectF(0, scan_y - 22, w, 44), scan)

        self._draw_reactor(p, cx, cy, radius, reveal, elapsed)

        title_y = int(cy + radius + 47)
        p.setPen(QColor(205, 247, 244, int(235 * reveal)))
        p.setFont(self._font(11, QFont.Weight.DemiBold, "Consolas"))
        p.drawText(QRectF(0, title_y, w, 24), Qt.AlignmentFlag.AlignCenter,
                   "J A R V I S   / /   NEURAL OPERATING SYSTEM")
        status = (
            "INITIALIZING NEURAL INTERFACE" if progress < .20 else
            "SYNCHRONIZING CORE SYSTEMS" if progress < .46 else
            "CALIBRATING HOLOGRAPHIC MATRIX" if progress < .91 else
            "ALL SYSTEMS ONLINE"
        )
        p.setPen(QColor(126, 190, 196, int(220 * reveal)))
        p.setFont(self._font(9, QFont.Weight.Normal, "Consolas"))
        p.drawText(QRectF(0, title_y + 27, w, 20), Qt.AlignmentFlag.AlignCenter,
                   status)

        bar_w = min(420, int(w * .42))
        bar_x = (w - bar_w) / 2
        bar_y = title_y + 66
        p.setPen(QPen(QColor(70, 145, 157, int(135 * reveal)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, 4), 2, 2)
        fill = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
        fill.setColorAt(0, QColor(72, 190, 190, int(220 * reveal)))
        fill.setColorAt(.72, QColor(143, 237, 219, int(245 * reveal)))
        fill.setColorAt(1, QColor(222, 177, 130, int(240 * reveal)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w * progress, 4), 2, 2)

        self._draw_readouts(p, w, h, reveal, progress)

        p.setPen(QColor(74, 123, 132, int(155 * reveal)))
        p.setFont(self._font(8, QFont.Weight.Normal, "Consolas"))
        p.drawText(34, h - 28, "JARVIS AI  •  LOCAL INTERFACE")
        p.drawText(QRectF(w - 210, h - 43, 176, 20),
                   Qt.AlignmentFlag.AlignRight, "PRESS ESC TO SKIP")

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w, h = self.width(), self.height()
        elapsed = self._elapsed

        # The initial title beat is deliberately minimal: no grid, HUD or
        # secondary labels are visible during its one-second hold.
        if elapsed < self.TITLE_FADE_END_MS:
            p.fillRect(self.rect(), self._BG)
            self._draw_title(p, w, h, elapsed)
            if elapsed <= self.TITLE_HOLD_MS:
                p.end()
                return
            reveal = self._ease(
                (elapsed - self.TITLE_HOLD_MS) /
                (self.TITLE_FADE_END_MS - self.TITLE_HOLD_MS)
            )
            self._draw_boot(p, w, h, elapsed, reveal)
        else:
            self._draw_boot(p, w, h, elapsed, 1.0)
        p.end()
