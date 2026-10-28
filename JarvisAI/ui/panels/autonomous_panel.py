"""Live autonomous-task panel for the Bento dashboard.

It reads the engine through :class:`agent.integration.AgentService` and never
blocks the Qt thread: progress arrives on the agent's event bus, is marshalled
through a Qt signal (auto-queued across threads), and the widget only repaints
while it is actually visible.

The panel is deliberately a *separate* surface from the hologram home screen. The
hologram stays the dominant, clean view; this card lives on the dashboard page
behind the ▦ button, exactly as the existing telemetry cards do.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from agent.presentation import progress_text, state_color, state_label, step_line

_ACCENT = "#00e5ff"


class AutonomousPanel(QWidget):
    """Task objective, stage, step list, test evidence and controls."""

    sig_agent_event = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None, *, service: Any | None = None):
        super().__init__(parent)
        self.setObjectName("AutonomousPanel")
        self._service = service
        self._task: Any | None = None
        self._last_state = ""
        self.setStyleSheet(
            """
            QWidget#AutonomousPanel { background: transparent; color: #d9e7ec; }
            QLabel#AgentEyebrow {
                color: #68d9ff; font: 700 9pt 'Consolas'; letter-spacing: 2px;
            }
            QLabel#AgentObjective { color: #eaf6ff; font: 600 11pt 'Aptos'; }
            QLabel#AgentDetail { color: #8caab9; font: 9pt 'Aptos'; }
            QLabel#AgentChip {
                color: #8fffd6; background: rgba(49, 208, 158, 22);
                border: 1px solid rgba(49, 208, 158, 75); border-radius: 9px;
                padding: 5px 9px; font: 700 8pt 'Consolas';
            }
            QProgressBar {
                border: 1px solid rgba(104, 217, 255, 0.28); border-radius: 6px;
                background: rgba(10, 24, 34, 200); height: 8px; text-align: center;
                color: transparent;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00e5ff, stop:1 #7df9ff);
                border-radius: 5px;
            }
            QPlainTextEdit#AgentReport {
                background: rgba(8, 18, 26, 210); color: #bfe6f2;
                border: 1px solid rgba(104, 217, 255, 0.22); border-radius: 10px;
                font: 9pt 'Consolas'; padding: 8px;
            }
            QPushButton#AgentPrimary {
                color: #07141d; background: #80e7ff; border: 0; border-radius: 9px;
                padding: 7px 12px; font: 700 8pt 'Consolas';
            }
            QPushButton#AgentPrimary:hover { background: #c4f4ff; }
            QPushButton#AgentGhost {
                color: #c7e0e9; background: rgba(104, 217, 255, 0.06);
                border: 1px solid rgba(104, 217, 255, 0.30); border-radius: 9px;
                padding: 7px 12px; font: 700 8pt 'Consolas';
            }
            QPushButton#AgentGhost:hover { background: rgba(104, 217, 255, 0.16); }
            QPushButton#AgentDanger {
                color: #ffd6de; background: rgba(255, 69, 107, 0.16);
                border: 1px solid rgba(255, 69, 107, 0.55); border-radius: 9px;
                padding: 7px 12px; font: 700 8pt 'Consolas';
            }
            QPushButton#AgentDanger:hover { background: rgba(255, 69, 107, 0.30); }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)

        header = QHBoxLayout()
        eyebrow = QLabel("AUTONOMOUS TASK")
        eyebrow.setObjectName("AgentEyebrow")
        header.addWidget(eyebrow)
        header.addStretch(1)
        self._chip = QLabel("IDLE")
        self._chip.setObjectName("AgentChip")
        self._chip.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        header.addWidget(self._chip)
        layout.addLayout(header)

        self._objective = QLabel("No task running. Ask JARVIS for multi-step work.")
        self._objective.setObjectName("AgentObjective")
        self._objective.setWordWrap(True)
        layout.addWidget(self._objective)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        self._meta = QLabel("Idle")
        self._meta.setObjectName("AgentDetail")
        self._meta.setWordWrap(True)
        layout.addWidget(self._meta)

        self._steps = QLabel("")
        self._steps.setObjectName("AgentDetail")
        self._steps.setWordWrap(True)
        self._steps.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(self._steps)

        self._blockers = QLabel("")
        self._blockers.setWordWrap(True)
        self._blockers.setStyleSheet("color: #ffb86b; font: 9pt 'Aptos';")
        self._blockers.hide()
        layout.addWidget(self._blockers)

        self._report = QPlainTextEdit(self)
        self._report.setObjectName("AgentReport")
        self._report.setReadOnly(True)
        self._report.setMaximumHeight(150)
        self._report.hide()
        layout.addWidget(self._report)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._pause_button = QPushButton("PAUSE", self)
        self._pause_button.setObjectName("AgentGhost")
        self._pause_button.clicked.connect(self._pause)
        self._stop_button = QPushButton("STOP", self)
        self._stop_button.setObjectName("AgentDanger")
        self._stop_button.clicked.connect(self._stop)
        self._report_button = QPushButton("REPORT", self)
        self._report_button.setObjectName("AgentGhost")
        self._report_button.clicked.connect(self._toggle_report)
        self._refresh_button = QPushButton("REFRESH", self)
        self._refresh_button.setObjectName("AgentPrimary")
        self._refresh_button.clicked.connect(self.refresh)
        for button in (self._pause_button, self._stop_button,
                       self._report_button, self._refresh_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self._timer = QTimer(self)
        self._timer.setInterval(1200)
        self._timer.timeout.connect(self.refresh)
        self._unsubscribe = None
        self._bind_service()

    # ── service plumbing ─────────────────────────────────────────────────
    def _resolve_service(self) -> Any | None:
        if self._service is not None:
            return self._service
        try:
            from agent.integration import get_service

            self._service = get_service()
        except Exception as exc:  # pragma: no cover - depends on host config
            self._meta.setText(f"Autonomy unavailable: {type(exc).__name__}")
            self._service = None
        return self._service

    def _bind_service(self) -> None:
        service = self._resolve_service()
        if service is None:
            return
        try:
            self.sig_agent_event.connect(self._on_agent_event,
                                         Qt.ConnectionType.QueuedConnection)
            self._unsubscribe = service.subscribe(self.sig_agent_event.emit)
        except Exception:
            self._unsubscribe = None
        self.refresh()

    # ── public API -------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._timer.start()
        self.refresh()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        """Re-read the engine snapshot; safe to call at any time."""
        service = self._resolve_service()
        if service is None:
            return
        try:
            snapshot = service.status()
        except Exception as exc:  # pragma: no cover - defensive
            self._meta.setText(f"Could not read task state: {type(exc).__name__}")
            return
        task = snapshot.get("task") or {}
        self._render(task or None, snapshot)

    def bind(self, service: Any) -> None:
        """Attach a different service instance (tests and alt windows)."""
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:
                pass
            self._unsubscribe = None
        self._service = service
        self._bind_service()

    # ── rendering --------------------------------------------------------
    def _on_agent_event(self, event: Any) -> None:
        if not self.isVisible():
            return
        self.refresh()
        kind = getattr(event, "kind", "")
        if kind in {"started", "step_done", "blocked", "finished", "step_failed"}:
            self._last_state = ""

    def _render(self, task: dict[str, Any] | None, snapshot: dict[str, Any]) -> None:
        if not task:
            self._chip.setText("IDLE")
            self._chip.setStyleSheet("")
            self._objective.setText("No task running. Ask JARVIS for multi-step work.")
            self._progress.setValue(0)
            self._meta.setText("Idle")
            self._steps.setText("")
            self._blockers.hide()
            self._report.hide()
            self._pause_button.setEnabled(False)
            self._stop_button.setEnabled(False)
            return

        state = str(task.get("state") or "pending")
        color = state_color(state)
        self._chip.setText(state_label(state))
        self._chip.setStyleSheet(
            f"QLabel#AgentChip {{ color: {color}; background: rgba(10,30,40,200); "
            f"border: 1px solid {color}; border-radius: 9px; padding: 5px 9px; "
            "font: 700 8pt 'Consolas'; }"
        )
        self._objective.setText(str(task.get("objective") or "")[:400])

        steps = task.get("steps") or []
        done = sum(1 for step in steps if step.get("state") == "completed")
        progress = 0 if not steps else int(round(100 * done / len(steps)))
        self._progress.setValue(progress)

        current = next((step for step in steps
                        if step.get("state") in {"running", "verifying"}), None)
        detail = f"{done}/{len(steps)} steps"
        if current:
            detail += f" · now: {current.get('title')}"
        if task.get("state") == "waiting" and task.get("wait_reason"):
            detail += f" · waiting: {task['wait_reason']}"
        attempts = task.get("retries_used") or 0
        if attempts:
            detail += f" · retries: {attempts}"
        self._meta.setText(detail)

        lines = []
        for index, step in enumerate(steps[:8]):
            lines.append(step_line(index, str(step.get("title") or "")[:70],
                                   str(step.get("state") or "pending")))
        if len(steps) > 8:
            lines.append(f"… {len(steps) - 8} more")
        self._steps.setText("\n".join(lines))

        blockers = task.get("blockers") or []
        self._blockers.setText("\n".join(f"⛔ {str(item)[:160]}" for item in blockers[:4]))
        self._blockers.setVisible(bool(blockers))

        report = task.get("report") or {}
        if report:
            from agent.models import TaskReport

            text = TaskReport.from_dict(report).as_text()
            self._report.setPlainText(text)
        else:
            self._report.setPlainText("")

        active = str(task.get("state")) in {"planning", "running", "verifying",
                                            "waiting", "paused"}
        self._pause_button.setEnabled(active)
        self._pause_button.setText("RESUME" if str(task.get("state")) == "paused" else "PAUSE")
        self._stop_button.setEnabled(active)

    # ── controls ---------------------------------------------------------
    def _pause(self) -> None:
        service = self._resolve_service()
        if service is None:
            return
        try:
            if self._pause_button.text() == "RESUME":
                service.resume()
            else:
                service.pause()
        except Exception:
            pass
        QTimer.singleShot(150, self.refresh)

    def _stop(self) -> None:
        service = self._resolve_service()
        if service is None:
            return
        try:
            service.stop("Stopped from the dashboard.")
        except Exception:
            pass
        QTimer.singleShot(150, self.refresh)

    def _toggle_report(self) -> None:
        if self._report.isVisible():
            self._report.hide()
            return
        if not self._report.toPlainText().strip():
            self._report.setPlainText("No report yet.")
        self._report.show()

    def progress_text(self) -> str:
        try:
            from agent.models import Task

            return progress_text(Task.from_dict(self._task) if self._task else None)
        except Exception:
            return ""


class AutonomousTaskCard(QFrame):
    """Thin frame so the card matches the existing bento surfaces."""

    def __init__(self, panel: AutonomousPanel, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("AutonomousTaskCard")
        self.setStyleSheet(
            "QFrame#AutonomousTaskCard { background: rgba(12, 24, 34, 225); "
            "border: 1px solid rgba(104, 217, 255, 0.24); border-radius: 18px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.addWidget(panel)
        self.panel = panel
