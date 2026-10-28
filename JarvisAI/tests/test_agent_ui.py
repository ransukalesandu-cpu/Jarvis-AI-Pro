"""Qt tests for the autonomous panel, the Dynamic Island and the HUD wiring.

These require a working Qt display stack (offscreen is fine). On a machine
without libGL/libxkbcommon — like a bare container without the documented system
packages — every test here is skipped with an explicit reason instead of failing
collection. The CI job installs ``libportaudio2 libgl1 libegl1``, so this file
runs there.

All logic that does not need Qt (labels, summaries, geometry) is covered by
``test_agent_core.py`` and runs everywhere.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

if (sys.platform != "win32" and not os.environ.get("DISPLAY")
        and "QT_QPA_PLATFORM" not in os.environ):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QWidget

    QT_AVAILABLE = True
except Exception:  # pragma: no cover - depends on the host's system libraries
    QT_AVAILABLE = False
    QApplication = None
    QWidget = object
    Qt = None

SKIP_REASON = "Qt cannot load on this machine (missing libGL/libxkbcommon)"

from agent.models import StepKind, StepState, Task, TaskState, TaskStep
from agent.presentation import IslandSummary


def _task(state: TaskState = TaskState.RUNNING) -> Task:
    task = Task(objective="Fix the failing tests and run the suite")
    task.set_plan([
        TaskStep(title="inspect", kind=StepKind.INSPECT),
        TaskStep(title="run tests", kind=StepKind.RUN_TESTS),
    ])
    task.transition(TaskState.PLANNING)
    if state is TaskState.PAUSED:
        task.transition(TaskState.PAUSED)
    else:
        task.transition(TaskState.RUNNING)
        task.steps[0].state = StepState.COMPLETED
        if state in (TaskState.COMPLETED, TaskState.FAILED):
            task.steps[1].state = (StepState.COMPLETED if state is TaskState.COMPLETED
                                   else StepState.FAILED)
            task.transition(state)
    return task


class FakeService:
    def __init__(self, task: Task | None = None):
        self.task = task
        self.paused = 0
        self.resumed = 0
        self.stopped: list[str] = []

        class _Runner:
            def __init__(self, owner):
                self._owner = owner

            @property
            def active_task(self):
                return self._owner.task

        self.runner = _Runner(self)

    def status(self):
        return {
            "active": None,
            "queued": [],
            "paused": False,
            "cancel_requested": False,
            "task": self.task.to_dict() if self.task else None,
            "settings": {},
            "capabilities": {},
        }

    def pause(self):
        self.paused += 1
        return True

    def resume(self):
        self.resumed += 1
        return True

    def stop(self, reason=""):
        self.stopped.append(reason)
        return True

    def subscribe(self, callback):
        self.callback = callback
        return lambda: None

    def handle_voice(self, text):
        return "ok"


@unittest.skipUnless(QT_AVAILABLE, SKIP_REASON)
class QtAgentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    # ── panel ────────────────────────────────────────────────────────────
    def test_panel_renders_running_task_and_controls_call_service(self):
        from ui.panels.autonomous_panel import AutonomousPanel

        service = FakeService(_task())
        panel = AutonomousPanel(service=service)
        self.addCleanup(panel.deleteLater)
        panel.refresh()
        self.assertIn("Fix the failing tests", panel._objective.text())
        self.assertEqual(panel._chip.text(), "WORKING")
        self.assertIn("1/2 steps", panel._meta.text())
        self.assertIn("inspect", panel._steps.text())
        self.assertTrue(panel._pause_button.isEnabled())

        panel._pause()
        self.assertEqual(service.paused, 1)
        panel._stop()
        self.assertEqual(len(service.stopped), 1)

    def test_panel_shows_idle_without_task(self):
        from ui.panels.autonomous_panel import AutonomousPanel

        panel = AutonomousPanel(service=FakeService(None))
        self.addCleanup(panel.deleteLater)
        panel.refresh()
        self.assertEqual(panel._chip.text(), "IDLE")
        self.assertFalse(panel._pause_button.isEnabled())
        self.assertFalse(panel._stop_button.isEnabled())

    def test_panel_renders_blockers_and_report(self):
        from ui.panels.autonomous_panel import AutonomousPanel

        task = _task()
        task.blockers.append("No vision provider is configured.")
        from agent.models import TaskReport

        task.report = TaskReport(task_id=task.id, objective=task.objective,
                                 state=task.state, completed=["inspect"])
        panel = AutonomousPanel(service=FakeService(task))
        self.addCleanup(panel.deleteLater)
        panel.refresh()
        self.assertIn("No vision provider", panel._blockers.text())
        self.assertIn("Task finished", panel._report.toPlainText())

    # ── island ───────────────────────────────────────────────────────────
    def test_island_renders_expands_and_emits(self):
        from ui.dynamic_island import DynamicIsland

        island = DynamicIsland(service=FakeService(_task()))
        self.addCleanup(island.deleteLater)
        island.refresh()
        summary = island.summary()
        self.assertEqual(summary.title, "WORKING")
        self.assertEqual(island.size().width(), 228)

        island.expand(True)
        self.assertEqual(island.size().width(), 340)
        self.assertTrue(island._pause_button.isVisibleTo(island))

        fired = []
        island.open_requested.connect(lambda: fired.append("open"))
        island.open_requested.emit()
        self.assertEqual(fired, ["open"])

        # Painting must not raise with a real QPainter.
        from PyQt6.QtGui import QPixmap

        pixmap = QPixmap(island.size())
        island.render(pixmap)
        self.assertFalse(pixmap.isNull())

    def test_island_set_summary_updates_text(self):
        from ui.dynamic_island import DynamicIsland

        island = DynamicIsland(service=FakeService(None))
        self.addCleanup(island.deleteLater)
        island.set_summary(IslandSummary("PAUSED", "Paused at step 2", 0.4,
                                         TaskState.PAUSED, "#ffd166", True))
        self.assertEqual(island.summary().title, "PAUSED")
        self.assertAlmostEqual(island.summary().progress, 0.4)

    def test_island_geometry_clamped_inside_screen(self):
        from ui.dynamic_island import DynamicIsland

        island = DynamicIsland(service=FakeService(None))
        self.addCleanup(island.deleteLater)
        island.move(100000, 100000)
        island.reposition()
        screen = island.screen().availableGeometry() if island.screen() else None
        if screen is not None:
            self.assertGreaterEqual(island.x(), screen.x())
            self.assertLessEqual(island.x() + island.width(),
                                 screen.x() + screen.width())

    # ── dashboard ────────────────────────────────────────────────────────
    def test_dashboard_accepts_extra_panel_without_moving_existing_cards(self):
        from ui.panels.modern_dashboard import ModernDashboard

        panels = tuple(QWidget() for _ in range(5))
        extra = QWidget()
        dashboard = ModernDashboard(panels, extra_panel=extra)
        self.addCleanup(dashboard.deleteLater)
        self.assertEqual(len(dashboard._cards), 5)
        self.assertIsNotNone(dashboard._extra_card)
        self.assertTrue(dashboard.open_extra())

    def test_dashboard_without_extra_panel_still_works(self):
        from ui.panels.modern_dashboard import ModernDashboard

        panels = tuple(QWidget() for _ in range(5))
        dashboard = ModernDashboard(panels)
        self.addCleanup(dashboard.deleteLater)
        self.assertEqual(len(dashboard._cards), 5)
        self.assertFalse(dashboard.open_extra())

    # ── HUD wiring ───────────────────────────────────────────────────────
    def test_hud_has_agent_panel_and_five_telemetry_cards(self):
        from ui.hud_main import HUDMainWindow

        with patch("agent.integration.get_service", return_value=FakeService(None)):
            hud = HUDMainWindow()
            self.addCleanup(hud.deleteLater)
            self.assertIsNotNone(hud._panel_agent)
            self.assertEqual(len(hud._dashboard._cards), 5)
            self.assertIsNotNone(hud._dashboard._extra_card)
            hud._open_agent_panel()
            self.assertIs(hud._workspace_stack.currentWidget(), hud._dashboard)

    def test_hud_minimize_shows_island_and_restore_hides_it(self):
        from PyQt6.QtTest import QTest
        from ui.hud_main import HUDMainWindow

        with patch("agent.integration.get_service", return_value=FakeService(_task())):
            hud = HUDMainWindow()
            self.addCleanup(hud.deleteLater)
            hud.show()
            QTest.qWait(50)
            self.assertIsNotNone(hud._island_controller)
            # Drive the controller directly: some offscreen platforms do not
            # report a minimised window state, and this is the exact code path
            # changeEvent() calls.
            hud._island_controller.sync(True)
            QTest.qWait(100)
            island = hud._island_controller.island
            self.assertIsNotNone(island)
            self.assertTrue(island.isVisible())
            hud._island_controller.sync(False)
            QTest.qWait(100)
            self.assertFalse(island.isVisible())

    def test_hud_change_event_uses_window_state(self):
        from ui.hud_main import HUDMainWindow

        with patch("agent.integration.get_service", return_value=FakeService(_task())):
            hud = HUDMainWindow()
            self.addCleanup(hud.deleteLater)
            hud._island_controller.sync(True)
            self.assertTrue(hud._island_controller.island.isVisible())
            hud._island_controller.restore_window()
            self.assertFalse(hud._island_controller.island.isVisible())


class RouteAgentTextTests(unittest.TestCase):
    """The main.py interception must be narrow and must never raise."""

    def test_only_agent_commands_are_intercepted(self):
        import main as jarvis_main

        class Ui:
            def __init__(self):
                self.logs = []

            def write_log(self, text):
                self.logs.append(text)

        class FakeRunner:
            active_task = None

        class Service:
            runner = FakeRunner()

            def handle_voice(self, text):
                return "Stopping the task."

        jarvis = jarvis_main.JarvisLive.__new__(jarvis_main.JarvisLive)
        jarvis.ui = Ui()
        jarvis._loop = None
        jarvis.session = None

        with patch("agent.integration.get_service", return_value=Service()):
            self.assertEqual(
                jarvis._route_agent_text("JARVIS, stop."), "Stopping the task."
            )
            self.assertIsNone(jarvis._route_agent_text("what's the weather tomorrow"))

    def test_failure_to_load_the_agent_is_tolerated(self):
        import main as jarvis_main

        jarvis = jarvis_main.JarvisLive.__new__(jarvis_main.JarvisLive)
        with patch("agent.integration.get_service", side_effect=RuntimeError("no agent")):
            self.assertIsNone(jarvis._route_agent_text("JARVIS, stop."))


if __name__ == "__main__":
    unittest.main()
