"""
Hybrid AI Brain Telemetry Panel for Jarvis AI Pro HUD.

Displays real-time routing status (Local Rule Router <20ms vs Cloud AI),
measured round-trip latency, and active language mode (English / Sinhala / Singlish).
"""

from __future__ import annotations

from typing import Optional
from PyQt6.QtCore import Qt, pyqtSlot, QRectF
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QBrush
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame


class HybridBrainPanel(QFrame):
    """
    Glassmorphism Telemetry Panel displaying Hybrid AI Brain routing status.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("HybridBrainPanel")
        self.setMinimumWidth(240)
        self.setStyleSheet("""
            QFrame#HybridBrainPanel {
                background: rgba(13, 20, 30, 0.82);
                border: 1px solid rgba(104, 217, 255, 0.24);
                border-radius: 16px;
            }
        """)

        # Do not display fabricated routing data before the backend reports a result.
        self._active_route = "Waiting for request"
        self._is_local = False
        self._latency_ms = 0.0
        self._language_mode = "Auto"
        self._model_name = ""

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Header
        hdr = QLabel("BRAIN  //  HYBRID ROUTER")
        hdr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        hdr.setStyleSheet("color: #00e5ff; background: transparent;")
        layout.addWidget(hdr)

        # Active Route Indicator — waits for real backend telemetry.
        self._lbl_route = QLabel("ROUTER: WAITING FOR REQUEST")
        self._lbl_route.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._lbl_route.setStyleSheet("color: #9aafaa; background: transparent;")
        layout.addWidget(self._lbl_route)

        # Details Row
        row = QHBoxLayout()
        row.setSpacing(12)

        # Latency
        self._lbl_latency = QLabel("LATENCY: —")
        self._lbl_latency.setFont(QFont("Courier New", 8, QFont.Weight.Normal))
        self._lbl_latency.setStyleSheet("color: #9aafaa; background: transparent;")
        row.addWidget(self._lbl_latency)

        # Language Mode
        self._lbl_lang = QLabel("LANG: Auto")
        self._lbl_lang.setFont(QFont("Courier New", 8, QFont.Weight.Normal))
        self._lbl_lang.setStyleSheet("color: #7c4dff; background: transparent;")
        row.addWidget(self._lbl_lang)

        layout.addLayout(row)

    @pyqtSlot(str, float, str, str)
    def update_telemetry(self, route: str, latency_ms: float, language: str = "English", model: str = ""):
        """Update real panel data."""
        self._active_route = route
        self._is_local = "local" in route.lower() or "rule" in route.lower()
        self._latency_ms = max(0.0, float(latency_ms))
        self._language_mode = language
        self._model_name = model

        model_tag = f" ({model})" if model else ""
        if self._is_local:
            self._lbl_route.setText(f"LOCAL AI{model_tag}")
            self._lbl_route.setStyleSheet("color: #00e676; background: transparent;")
        else:
            self._lbl_route.setText(f"CLOUD AI{model_tag}")
            self._lbl_route.setStyleSheet("color: #7c4dff; background: transparent;")

        self._lbl_latency.setText(f"LATENCY: {self._latency_ms:.1f} ms")
        self._lbl_lang.setText(f"LANG: {self._language_mode}")
