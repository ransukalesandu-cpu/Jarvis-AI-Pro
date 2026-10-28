"""
System Telemetry Ring Widget for Jarvis AI Pro HUD.

Draws smooth circular gauges using QPainter for CPU, RAM, and Battery percentages,
reading real system metrics via psutil.
"""

from __future__ import annotations

from typing import Optional
import psutil

from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSlot
from PyQt6.QtGui import QFont, QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel


class TelemetryGaugeWidget(QWidget):
    """
    Single smooth circular gauge ring widget.
    """

    def __init__(self, label: str = "CPU", color_hex: str = "#00e5ff", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(80, 80)
        self._label = label
        self._color = QColor(color_hex)
        self._value = 0.0  # 0.0 to 100.0
        self._target_value = 0.0

    def set_value(self, val: float):
        self._target_value = max(0.0, min(100.0, float(val)))
        # Lerp update
        self._value += (self._target_value - self._value) * 0.35
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        if not p.isActive():
            return

        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        size = min(W, H) - 12
        cx, cy = W / 2.0, H / 2.0
        rect = QRectF(cx - size / 2.0, cy - size / 2.0, size, size)

        # Background Track
        p.setPen(QPen(QColor("#101923"), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 0, 360 * 16)

        # Active Arc (Start at 90 deg / top)
        span_angle = -int((self._value / 100.0) * 360.0 * 16)
        p.setPen(QPen(self._color, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 90 * 16, span_angle)

        # Value text
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(QColor("#edf3e8"), 1))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{int(self._value)}%")

        # Label text below
        p.setFont(QFont("Courier New", 7, QFont.Weight.Normal))
        p.setPen(QPen(QColor("#78908d"), 1))
        p.drawText(QRectF(0, cy + size / 2.0 - 2, W, 14), Qt.AlignmentFlag.AlignCenter, self._label)

        p.end()


class SystemTelemetryRing(QFrame):
    """
    Glassmorphism Telemetry Ring panel holding CPU, RAM, and Battery gauge rings.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("SystemTelemetryRing")
        self.setMinimumWidth(280)
        self.setStyleSheet("""
            QFrame#SystemTelemetryRing {
                background: rgba(13, 20, 30, 0.82);
                border: 1px solid rgba(104, 217, 255, 0.24);
                border-radius: 16px;
            }
        """)

        self._init_ui()

        # Update timer for live system metrics (1 second interval)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_metrics)
        self._timer.start(1000)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(6)

        # Header
        hdr = QLabel("SYSTEM TELEMETRY  //  HARDWARE GAUGES")
        hdr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        hdr.setStyleSheet("color: #00e5ff; background: transparent;")
        main_layout.addWidget(hdr)

        # Gauges Row
        row = QHBoxLayout()
        row.setSpacing(10)

        self._gauge_cpu = TelemetryGaugeWidget("CPU", "#00e5ff")
        self._gauge_ram = TelemetryGaugeWidget("RAM", "#7c4dff")
        self._gauge_bat = TelemetryGaugeWidget("BAT", "#00e676")

        row.addWidget(self._gauge_cpu)
        row.addWidget(self._gauge_ram)
        row.addWidget(self._gauge_bat)

        main_layout.addLayout(row)

    @pyqtSlot()
    def update_metrics(self):
        """Read real system metrics using psutil."""
        try:
            cpu_pct = psutil.cpu_percent(interval=None)
            ram_pct = psutil.virtual_memory().percent

            bat_pct = 100.0
            battery = psutil.sensors_battery()
            if battery is not None:
                bat_pct = float(battery.percent)

            self._gauge_cpu.set_value(cpu_pct)
            self._gauge_ram.set_value(ram_pct)
            self._gauge_bat.set_value(bat_pct)
        except Exception:
            pass
