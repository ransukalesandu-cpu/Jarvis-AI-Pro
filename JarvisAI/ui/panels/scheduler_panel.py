"""
Proactive Scheduler & Tasks Telemetry Panel for Jarvis AI Pro HUD.

Connected to JarvisAI prospective memory / scheduler actions:
displays upcoming reminders, tasks, and Quiet Hours / DND status.
"""

from __future__ import annotations

from typing import Optional
from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame

from core import failsoft


class SchedulerPanel(QFrame):
    """
    Glassmorphism Telemetry Panel displaying proactive tasks & DND status.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("SchedulerPanel")
        self.setMinimumWidth(240)
        self.setStyleSheet("""
            QFrame#SchedulerPanel {
                background: rgba(13, 20, 30, 0.82);
                border: 1px solid rgba(104, 217, 255, 0.24);
                border-radius: 16px;
            }
        """)

        # Data state
        self._upcoming_task = "No active reminders"
        self._dnd_status = "OFF"
        self._quiet_hours = "22:00 - 07:00"

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Header
        hdr = QLabel("SCHEDULER  //  PROACTIVE TASKS")
        hdr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        hdr.setStyleSheet("color: #00e5ff; background: transparent;")
        layout.addWidget(hdr)

        # Task Indicator
        self._lbl_task = QLabel("NO UPCOMING REMINDERS")
        self._lbl_task.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._lbl_task.setStyleSheet("color: #7c4dff; background: transparent;")
        layout.addWidget(self._lbl_task)

        # Sub row for Quiet Hours / DND
        row = QHBoxLayout()
        row.setSpacing(12)

        # DND Status
        self._lbl_dnd = QLabel("DND: OFF")
        self._lbl_dnd.setFont(QFont("Courier New", 8, QFont.Weight.Normal))
        self._lbl_dnd.setStyleSheet("color: #9aafaa; background: transparent;")
        row.addWidget(self._lbl_dnd)

        # Quiet Hours
        self._lbl_quiet = QLabel("QUIET HOURS: ACTIVE")
        self._lbl_quiet.setFont(QFont("Courier New", 8, QFont.Weight.Normal))
        self._lbl_quiet.setStyleSheet("color: #00e676; background: transparent;")
        row.addWidget(self._lbl_quiet)

        layout.addLayout(row)

    @pyqtSlot(str, bool, str)
    def update_scheduler_stats(self, next_task: str = "", dnd_active: bool = False, quiet_hours: str = "22:00 - 07:00"):
        """Update scheduler telemetry panel."""
        self._upcoming_task = next_task or "No upcoming tasks"
        self._dnd_status = "ON" if dnd_active else "OFF"
        self._quiet_hours = quiet_hours

        task_disp = self._upcoming_task if len(self._upcoming_task) <= 24 else self._upcoming_task[:21] + "..."
        self._lbl_task.setText(task_disp.upper())

        self._lbl_dnd.setText(f"DND: {self._dnd_status}")
        self._lbl_dnd.setStyleSheet(
            "color: #ffab00; background: transparent;" if dnd_active else "color: #9aafaa; background: transparent;"
        )

    def fetch_real_scheduler_state(self):
        """Show the soonest pending intention, straight from prospective memory."""
        try:
            from memory.prospective_memory import pending_intentions

            tasks = pending_intentions()
            next_title = (
                str(tasks[0].get("content") or tasks[0].get("trigger") or "")
                if tasks else "No upcoming tasks"
            )
            self.update_scheduler_stats(next_title, False, "22:00 - 07:00")
        except Exception:
            failsoft.suppress('ui.panels.scheduler_panel:SchedulerPanel.fetch_real_scheduler_state')
