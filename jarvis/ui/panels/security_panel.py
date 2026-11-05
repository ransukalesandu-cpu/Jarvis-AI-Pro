"""
Security & Identity Telemetry Panel for Jarvis AI Pro HUD.

Displays real-time AuthState (FULL_ACCESS, RESTRICTED, CHALLENGE, PRIVACY_LOCK),
failed PIN attempt counter (e.g. 0/3), and current authentication method.
"""

from __future__ import annotations

from typing import Optional
from PyQt6.QtCore import pyqtSlot, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame


class SecurityPanel(QFrame):
    """
    Glassmorphism Telemetry Panel displaying AuthState & Identity status.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("SecurityPanel")
        self.setMinimumWidth(240)
        self.setStyleSheet("""
            QFrame#SecurityPanel {
                background: rgba(13, 20, 30, 0.82);
                border: 1px solid rgba(104, 217, 255, 0.24);
                border-radius: 16px;
            }
        """)

        # Data state
        self._auth_state = "FULL_ACCESS"  # FULL_ACCESS, RESTRICTED, CHALLENGE, PRIVACY_LOCK
        self._failed_attempts = 0
        self._auth_method = "voice"  # pin, voice, or none
        self._flash_toggle = False

        # Timer for flashing PRIVACY_LOCK alert
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._flash_step)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Header
        hdr = QLabel("SECURITY  //  AUTH STATE")
        hdr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        hdr.setStyleSheet("color: #00e5ff; background: transparent;")
        layout.addWidget(hdr)

        # AuthState Indicator
        self._lbl_status = QLabel("FULL ACCESS (Verified Owner)")
        self._lbl_status.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._lbl_status.setStyleSheet("color: #00e676; background: transparent;")
        layout.addWidget(self._lbl_status)

        # Sub row
        row = QHBoxLayout()
        row.setSpacing(12)

        # PIN Attempt Counter
        self._lbl_attempts = QLabel("PIN ATTEMPTS: 0/3")
        self._lbl_attempts.setFont(QFont("Courier New", 8, QFont.Weight.Normal))
        self._lbl_attempts.setStyleSheet("color: #9aafaa; background: transparent;")
        row.addWidget(self._lbl_attempts)

        # Method
        self._lbl_method = QLabel("METHOD: Voice ID")
        self._lbl_method.setFont(QFont("Courier New", 8, QFont.Weight.Normal))
        self._lbl_method.setStyleSheet("color: #00e5ff; background: transparent;")
        row.addWidget(self._lbl_method)

        layout.addLayout(row)

    @pyqtSlot(str, int, str)
    def update_auth_state(self, state: str, failed_attempts: int = 0, method: str = ""):
        """Update AuthState display."""
        st = str(state or "RESTRICTED").upper()
        self._auth_state = st
        self._failed_attempts = max(0, int(failed_attempts))
        self._auth_method = method

        self._lbl_attempts.setText(f"PIN ATTEMPTS: {self._failed_attempts}/3")
        self._lbl_method.setText(f"METHOD: {method.capitalize() if method else 'None'}")

        if st in ("FULL_ACCESS", "FULL_ACCESS_MODE"):
            self._flash_timer.stop()
            self.setStyleSheet("""
                QFrame#SecurityPanel {
                    background: rgba(13, 20, 30, 0.82);
                    border: 1px solid rgba(0, 230, 118, 0.45);
                    border-radius: 16px;
                }
            """)
            self._lbl_status.setText("FULL ACCESS (Verified Owner)")
            self._lbl_status.setStyleSheet("color: #00e676; background: transparent;")

        elif st in ("RESTRICTED", "RESTRICTED_MODE"):
            self._flash_timer.stop()
            self.setStyleSheet("""
                QFrame#SecurityPanel {
                    background: rgba(13, 20, 30, 0.82);
                    border: 1px solid rgba(255, 171, 0, 0.4);
                    border-radius: 16px;
                }
            """)
            self._lbl_status.setText("RESTRICTED (Guest Mode)")
            self._lbl_status.setStyleSheet("color: #ffab00; background: transparent;")

        elif st in ("CHALLENGE", "CHALLENGE_MODE"):
            self._flash_timer.stop()
            self.setStyleSheet("""
                QFrame#SecurityPanel {
                    background: rgba(13, 20, 30, 0.82);
                    border: 1px solid rgba(0, 229, 255, 0.4);
                    border-radius: 16px;
                }
            """)
            self._lbl_status.setText("CHALLENGE (Awaiting PIN)")
            self._lbl_status.setStyleSheet("color: #00e5ff; background: transparent;")

        elif st in ("PRIVACY_LOCK", "LOCKDOWN"):
            self._lbl_status.setText("PRIVACY LOCK (System Locked)")
            self._lbl_status.setStyleSheet("color: #ff1744; background: transparent;")
            if not self._flash_timer.isActive():
                self._flash_timer.start(500)

    def _flash_step(self):
        self._flash_toggle = not self._flash_toggle
        if self._flash_toggle:
            self.setStyleSheet("""
                QFrame#SecurityPanel {
                    background: rgba(50, 0, 10, 0.85);
                    border: 2px solid #ff1744;
                    border-radius: 16px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#SecurityPanel {
                    background: rgba(13, 20, 30, 0.82);
                    border: 1px solid rgba(255, 23, 68, 0.5);
                    border-radius: 16px;
                }
            """)
