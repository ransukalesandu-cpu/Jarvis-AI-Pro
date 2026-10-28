"""
Memory Store Telemetry Panel for Jarvis AI Pro HUD.

Connected to JarvisAI/memory system: displays number of indexed local facts/summaries,
last recalled memory key, and memory health status.
"""

from __future__ import annotations

from typing import Optional
from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame

from core import failsoft


class MemoryPanel(QFrame):
    """
    Glassmorphism Telemetry Panel displaying local long-term memory metrics.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("MemoryPanel")
        self.setMinimumWidth(240)
        self.setStyleSheet("""
            QFrame#MemoryPanel {
                background: rgba(13, 20, 30, 0.82);
                border: 1px solid rgba(104, 217, 255, 0.24);
                border-radius: 16px;
            }
        """)

        # Data state
        self._indexed_count = 0
        self._last_key = "None"
        self._memory_status = "ONLINE"

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Header
        hdr = QLabel("MEMORY  //  INDEXED STORE")
        hdr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        hdr.setStyleSheet("color: #00e5ff; background: transparent;")
        layout.addWidget(hdr)

        # Count Indicator
        self._lbl_count = QLabel("INDEXED FACTS: 0")
        self._lbl_count.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._lbl_count.setStyleSheet("color: #00e5ff; background: transparent;")
        layout.addWidget(self._lbl_count)

        # Details Row
        row = QHBoxLayout()
        row.setSpacing(12)

        # Last Recalled Key
        self._lbl_key = QLabel("LAST RECALLED: --")
        self._lbl_key.setFont(QFont("Courier New", 8, QFont.Weight.Normal))
        self._lbl_key.setStyleSheet("color: #9aafaa; background: transparent;")
        row.addWidget(self._lbl_key)

        layout.addLayout(row)

    @pyqtSlot(int, str, str)
    def update_memory_stats(self, indexed_count: int, last_key: str = "None", status: str = "ONLINE"):
        """Update memory telemetry panel."""
        self._indexed_count = max(0, int(indexed_count))
        self._last_key = str(last_key or "None")
        self._memory_status = str(status)

        self._lbl_count.setText(f"INDEXED FACTS: {self._indexed_count}")

        key_disp = self._last_key if len(self._last_key) <= 16 else self._last_key[:13] + "..."
        self._lbl_key.setText(f"LAST RECALLED: {key_disp}")

    def fetch_real_memory_state(self):
        """Fetch live stats from the memory manager.

        This called ``get_memory_manager().get_all_facts()`` — neither of which
        exists — inside a bare ``try/except``, so the panel's counters stayed at
        zero for everyone. ``all_entries_for_ui()`` is the supported listing.
        """
        try:
            from memory.memory_manager import all_entries_for_ui

            entries = all_entries_for_ui()
            latest_key = str(entries[0].get("key", "None")) if entries else "None"
            self.update_memory_stats(len(entries), latest_key, "ONLINE")
        except Exception:
            failsoft.suppress('ui.panels.memory_panel:MemoryPanel.fetch_real_memory_state')
