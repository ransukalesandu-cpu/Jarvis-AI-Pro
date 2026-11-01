"""Lightweight, code-drawn cinematic JARVIS boot sequence.

No video, image assets, multimedia backend, or extra Qt process is required.
The splash is intentionally isolated from the desktop HUD and closes before
JarvisUI is constructed.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class StartupSequenceSplash(QWidget):
    """Fullscreen animated boot screen; emits finished exactly once."""

    finished = pyqtSignal()

    DURATION_MS = 4100
    TITLE_HOLD_MS = 1000
    TITLE_FADE_END_MS = 1500

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("JARVIS")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._done = False
        self._elapsed = 0

    def start(self) -> None:
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
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.finish()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _ease(value: float) -> float:
        value = max(0.0, min(1.0, value))
        return value * value * (3.0 - 2.0 * value)

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        t = self._elapsed
        bg = QColor("#03070c")
        p.fillRect(self.rect(), bg)

        # Restrained technical grid and edge markers.
        grid_pen = QPen(QColor(55, 132, 151, 28), 1)
        p.setPen(grid_pen)
        step = 54
        for x in range(int(cx) % step, w, step):
            p.drawLine(x, 0, x, h)
        for y in range(int(cy) % step, h, step):
            p.drawLine(0, y, w, y)
        p.setPen(QPen(QColor(77, 213, 222, 95), 1))
        margin = 34
        length = 28
        for x, sx in ((margin, 1), (w - margin, -1)):
            for y, sy in ((margin, 1), (h - margin, -1)):
                p.drawLine(x, y, x + sx * length, y)
                p.drawLine(x, y, x, y + sy * length)

        # First beat: only the JARVIS wordmark, held for one second.
        if t < self.TITLE_FADE_END_MS:
            alpha = 255 if t <= self.TITLE_HOLD_MS else int(
                255 * (1.0 - self._ease(
                    (t - self.TITLE_HOLD_MS) /
                    (self.TITLE_FADE_END_MS - self.TITLE_HOLD_MS)
                ))
            )
            p.setPen(QColor(197, 245, 248, alpha))
            font = QFont("Consolas", max(28, int(min(w, h) * 0.075)))
            font.setWeight(QFont.Weight.Light)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 13)
            p.setFont(font)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "JARVIS")
            if t < self.TITLE_HOLD_MS:
                p.end()
                return

        # Boot HUD assembles after the title fades away.
        progress = self._ease((t - self.TITLE_FADE_END_MS) /
                              (self.DURATION_MS - self.TITLE_FADE_END_MS))
        if t >= self.TITLE_HOLD_MS:
            reveal = self._ease((t - self.TITLE_HOLD_MS) / 650.0)
            radius = 72 + 105 * progress
            p.save()
            p.translate(cx, cy - 8)
            p.setPen(QPen(QColor(68, 211, 220, int(125 * reveal)), 1))
            p.drawEllipse(-radius, -radius, radius * 2, radius * 2)
            p.setPen(QPen(QColor(68, 211, 220, int(55 * reveal)), 1))
            p.drawEllipse(-radius * .78, -radius * .78,
                          radius * 1.56, radius * 1.56)
            p.setPen(QPen(QColor(113, 237, 237, int(160 * reveal)), 1))
            p.drawLine(-radius - 24, 0, radius + 24, 0)
            p.drawLine(0, -radius - 24, 0, radius + 24)
            p.setPen(QPen(QColor(79, 220, 225, int(210 * reveal)), 2))
            import math
            p.drawArc(int(-radius), int(-radius), int(radius * 2),
                      int(radius * 2), int((t * .12) % 360 * 16), 105 * 16)
            p.drawArc(int(-radius * .78), int(-radius * .78),
                      int(radius * 1.56), int(radius * 1.56),
                      int((-t * .16) % 360 * 16), -82 * 16)
            p.restore()

            p.setPen(QColor(171, 237, 240, int(220 * reveal)))
            label_font = QFont("Consolas", 10)
            label_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
            p.setFont(label_font)
            p.drawText(0, int(cy + radius + 42), w, 22,
                       Qt.AlignmentFlag.AlignHCenter, "J A R V I S  //  SYSTEM BOOT")

            status = "INITIALIZING NEURAL INTERFACE"
            if progress > .34:
                status = "SYNCHRONIZING CORE SYSTEMS"
            if progress > .68:
                status = "CALIBRATING HOLOGRAPHIC DISPLAY"
            if progress > .94:
                status = "ALL SYSTEMS READY"
            p.setPen(QColor(110, 188, 197, int(210 * reveal)))
            p.drawText(0, int(cy + radius + 68), w, 18,
                       Qt.AlignmentFlag.AlignHCenter, status)

            bar_w = min(390, int(w * .42))
            bar_x = int(cx - bar_w / 2)
            bar_y = int(cy + radius + 100)
            p.setPen(QPen(QColor(62, 150, 164, int(120 * reveal)), 1))
            p.drawRect(bar_x, bar_y, bar_w, 3)
            p.fillRect(bar_x, bar_y, int(bar_w * progress), 3,
                       QColor(105, 229, 231, int(230 * reveal)))
            p.setPen(QColor(110, 188, 197, int(170 * reveal)))
            p.drawText(bar_x, bar_y + 22, bar_w, 16,
                       Qt.AlignmentFlag.AlignCenter,
                       f"{int(progress * 100):02d}%")

        p.end()
