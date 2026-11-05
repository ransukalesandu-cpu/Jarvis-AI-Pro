"""Guest notice, Security ON/OFF, owner list and Guest history controls (Security V2, Phase 5)."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from jarvis.core import security_view


class GuestSecurityView(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(6)
        self._notice = QLabel(self)
        self._notice.setWordWrap(True)
        self._notice.setStyleSheet("color:#ffab00;background:rgba(255,171,0,0.10);border-radius:8px;padding:6px;")
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#9aafaa;background:transparent;")
        self._owners = QLabel(self)
        self._owners.setWordWrap(True)
        self._owners.setStyleSheet("color:#00e5ff;background:transparent;")
        self._history = QLabel(self)
        self._history.setWordWrap(True)
        self._history.setStyleSheet("color:#9aafaa;background:transparent;")
        self._toggle = QPushButton(self)
        self._delete = QPushButton("Delete latest Guest history", self)
        self._toggle.clicked.connect(self._on_toggle)
        self._delete.clicked.connect(self._on_delete)
        for w in (self._notice, self._status, self._owners, self._history, self._toggle, self._delete):
            lay.addWidget(w)
        self._monitoring = True
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)
        self.refresh()

    def refresh(self) -> None:
        s = security_view.snapshot()
        self._monitoring = s["monitoring"]
        mode = s["mode"]
        self._notice.setVisible(mode == "guest")
        self._notice.setText(s["notice"])
        owner = mode == "owner"
        for w in (self._owners, self._history, self._toggle, self._delete):
            w.setVisible(owner)
        self._status.setVisible(mode != "signed_out")
        self._status.setText({
            "guest": "Guest Mode: restricted. The owner must sign in for more.",
            "legacy": "Single-owner mode. Create owners with scripts/security_owners.py to enable Guest Mode.",
            "owner": f"Signed in as {s['owner_name'] or 'owner'}. Security monitoring: "
                     f"{'ON' if s['monitoring'] else 'OFF'}.",
        }.get(mode, ""))
        if owner:
            self._owners.setText("Owners: " + ", ".join(
                f"{o['name']}{' (admin)' if o['admin'] else ''}{'' if o['status'] == 'active' else ' [revoked]'}"
                for o in s["owners"]))
            self._history.setText(s["guest_summary"])
            self._toggle.setText("Turn Guest monitoring OFF" if s["monitoring"] else "Turn Guest monitoring ON")

    def _say(self, text: str) -> None:
        self._status.setVisible(True)
        self._status.setText(text)

    def _on_toggle(self) -> None:
        turning_off = self._monitoring
        if turning_off and QMessageBox.question(
                self, "Turn monitoring off?",
                "Guest sessions will no longer be logged. Baseline protections stay on.\n"
                "This needs a recent second-factor confirmation.") != QMessageBox.StandardButton.Yes:
            return
        self._say(security_view.perform("monitoring", enabled=not self._monitoring))
        self.refresh()

    def _on_delete(self) -> None:
        if QMessageBox.question(self, "Delete Guest history?",
                                "Permanently delete the latest Guest session log?") != QMessageBox.StandardButton.Yes:
            return
        self._say(security_view.perform("delete_latest_guest"))
        self.refresh()
