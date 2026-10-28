"""Integration tests for the holographic command-centre wiring in the real HUD.

Everything here drives the actual :class:`HUDMainWindow` and asserts on real
widget state — no mocks of the pieces under test. The only stubs are the data
sources that must not touch the network or the machine in CI:

* subsystem probes are replaced by a dict-driven :class:`HealthMonitor`;
* the battery reader is a fake psutil sample;
* the background prober thread is disabled with an env flag.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

if sys.platform != "win32" and not os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
# Never spawn a probing thread from a test-created HUD window.
os.environ.setdefault("JARVIS_DISABLE_SUBSYSTEM_PROBES", "1")

import unittest

from PyQt6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from audio.visualizer_bridge import VisualizerBridge
from core.hologram_theme import BIHANSA_PALETTE, JARVIS_PALETTE
from core.system_status import BatteryMonitor, BatteryReading, HealthMonitor, Notification, PRIORITY_NORMAL
from ui.hud_main import HUDMainWindow
from ui.task_panels import TaskState


class HUDHarness(unittest.TestCase):
    def setUp(self):
        self.bridge = VisualizerBridge()
        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        config_patch = patch("memory.config_manager.CONFIG_FILE", Path(settings_dir.name) / "api_keys.json")
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.settings = QSettings(
            str(Path(settings_dir.name) / "settings.ini"), QSettings.Format.IniFormat
        )
        settings_patch = patch("ui.hud_main.QSettings", return_value=self.settings)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

    def make_hud(self, width=1280, height=800):
        hud = HUDMainWindow(bridge=self.bridge)
        hud.resize(width, height)
        hud.show()
        app.processEvents()

        def dispose():
            hud.close()
            hud.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)
        return hud


class TestPaletteWiring(HUDHarness):
    def test_jarvis_palette_reaches_every_renderer(self):
        hud = self.make_hud()
        self.assertEqual(hud.palette.primary, JARVIS_PALETTE.primary)
        self.assertEqual(hud.wireframe_visualizer._palette.primary, JARVIS_PALETTE.primary)
        # The Bihansa companion keeps its own pink identity even in JARVIS mode.
        self.assertEqual(hud.bihansa_visualizer._palette.primary, BIHANSA_PALETTE.primary)
        self.assertEqual(hud._heart_reactor._palette.primary, JARVIS_PALETTE.primary)

    def test_bihansa_switch_drives_palette_persona_and_voice(self):
        hud = self.make_hud()
        mode_changes = []
        hud.sig_mode_changed.connect(lambda: mode_changes.append(hud.palette.mode))

        hud._bihansa_toggle.setChecked(True)
        app.processEvents()
        self.assertEqual(hud.palette.mode, "bihansa")
        # Chrome and the reactor follow the persona; both faces keep their own hue.
        self.assertEqual(hud._heart_reactor._palette.primary, BIHANSA_PALETTE.primary)
        self.assertEqual(hud._status_strip._palette.primary, BIHANSA_PALETTE.primary)
        self.assertEqual(hud.wireframe_visualizer._palette.primary, JARVIS_PALETTE.primary)
        # The persona switch still asks the live layer for a new voice persona.
        self.assertEqual(mode_changes, ["bihansa"])
        from memory.config_manager import get_assistant_mode
        self.assertEqual(get_assistant_mode(), "bihansa")

        hud._bihansa_toggle.setChecked(False)
        app.processEvents()
        self.assertEqual(hud.palette.mode, "jarvis")
        self.assertEqual(mode_changes, ["bihansa", "jarvis"])

    def test_privacy_lock_survives_a_persona_switch(self):
        hud = self.make_hud()
        self.bridge.update_auth_state("PRIVACY_LOCK")
        app.processEvents()
        self.assertTrue(hud._privacy_locked)
        hud._bihansa_toggle.setChecked(True)
        app.processEvents()
        # A colour/persona change must never unlock the HUD.
        self.assertTrue(hud._privacy_locked)
        self.assertFalse(hud._lock_banner.isHidden())
        self.assertEqual(hud.wireframe_visualizer.get_state(), "PRIVACY_LOCK")


class TestFaceGeometry(HUDHarness):
    def test_face_rect_is_centred_and_square(self):
        hud = self.make_hud()
        face = hud.wireframe_visualizer.face_rect()
        self.assertGreater(face.width(), 100)
        self.assertEqual(face.width(), face.height())
        centre_x = hud.wireframe_visualizer.width() / 2
        self.assertLessEqual(abs(face.center().x() - centre_x), 2)

    def test_head_mesh_is_a_face_not_a_sphere(self):
        """The mesh must have real features and cull its hidden side."""
        hud = self.make_hud()
        head = hud.wireframe_visualizer
        self.assertGreater(len(head._feature_edges), 12)
        self.assertEqual(len(head._eyes), 2)
        # Crown and chin are narrower than the temples.
        self.assertLess(head._radius_at(1.0), head._radius_at(0.2))
        self.assertLess(head._radius_at(-1.0), head._radius_at(0.0))

    def test_panels_avoid_the_orb_and_heart_as_well_as_the_face(self):
        hud = self.make_hud()
        hud._sync_task_blocked_rect()
        blocked = hud._task_panels._blocked
        dock = hud._orb_dock_rect()
        self.assertTrue(blocked.contains(dock))
        hud.begin_command("youtube_video", "Clip")
        app.processEvents()
        panel = hud._task_panels.panel("cmd:youtube_video")
        self.assertEqual(panel.geometry().intersected(blocked).isEmpty(), True)


class TestTaskPanelWiring(HUDHarness):
    def test_overlay_is_on_the_stage_and_avoids_the_face(self):
        hud = self.make_hud()
        hud._sync_task_blocked_rect()
        blocked = hud._task_panels._blocked
        self.assertFalse(blocked.isNull())
        face = hud.wireframe_visualizer.face_rect()
        self.assertLessEqual(abs(blocked.width() - face.width()), 4)
        self.assertIs(hud._task_panels.parentWidget(), hud._hologram_stage)

    def test_voice_command_highlights_runs_and_confirms(self):
        hud = self.make_hud()
        hud.begin_command("web_search", "latest fusion news")
        app.processEvents()
        task_id = "cmd:web_search"
        self.assertTrue(hud._task_panels.has_task(task_id))
        panel = hud._task_panels.panel(task_id)
        self.assertEqual(panel.spec.state, TaskState.RUNNING)
        self.assertEqual(panel.spec.title, "latest fusion news")
        self.assertGreater(panel._highlight, 0.0, "the target panel must be highlighted")

        hud.finish_command("web_search", "Here are the latest results from the web.")
        app.processEvents()
        self.assertEqual(panel.spec.state, TaskState.COMPLETED)

    def test_failed_command_is_reported_as_failed(self):
        hud = self.make_hud()
        hud.begin_command("youtube_video", "play something")
        app.processEvents()
        hud.finish_command("youtube_video", "Could not open the browser: permission denied.")
        app.processEvents()
        panel = hud._task_panels.panel("cmd:youtube_video")
        self.assertEqual(panel.spec.state, TaskState.FAILED)

    def test_result_classification_never_claims_unknown_success(self):
        cases = {
            "Opened YouTube.": True,
            "Music saved.": True,
            "": False,
            "Error: no device": False,
            "The action failed.": False,
            "Unable to reach the service": False,
        }
        for text, expected in cases.items():
            self.assertEqual(HUDMainWindow._result_ok(text), expected, text)

    def test_missing_command_does_not_create_a_panel(self):
        hud = self.make_hud()
        hud.finish_command("ghost_action", "ok")
        app.processEvents()
        self.assertEqual(hud._task_panels.task_ids(), [])


class TestHealthAndBatteryWiring(HUDHarness):
    def test_health_strip_reflects_real_subsystem_state(self):
        hud = self.make_hud()
        hud._health = HealthMonitor({
            "microphone": lambda: (True, False, "no input device"),
            "speaker": lambda: (True, True, "2 output devices"),
            "network": lambda: (False, False, "not applicable"),
        })
        hud._refresh_health()
        self.assertEqual(hud._status_strip.state_of("microphone"), "error")
        self.assertEqual(hud._status_strip.state_of("speaker"), "ok")
        # No hardware at all is "unavailable", never green.
        self.assertEqual(hud._status_strip.state_of("network"), "unavailable")

    def test_battery_unavailable_is_not_reported_as_zero(self):
        hud = self.make_hud()
        hud._battery = BatteryMonitor(reader=lambda: BatteryReading(available=False))
        hud._poll_system_status()
        self.assertFalse(hud._heart_reactor._battery_available)
        self.assertIsNone(hud._heart_reactor._battery_percent)
        self.assertEqual(hud._island._battery_text, "")
        self.assertFalse(hud._mini_orb._charging)

    def test_low_battery_degrades_visuals_and_heart(self):
        hud = self.make_hud()
        hud._battery = BatteryMonitor(reader=lambda: BatteryReading(True, 18.0, False))
        hud._poll_system_status()
        self.assertTrue(hud._heart_reactor._battery_available)
        self.assertEqual(hud._heart_reactor._battery_percent, 18.0)
        self.assertTrue(hud._heart_reactor._low_battery)
        self.assertEqual(hud._island._battery_text, "18%")
        # Saver budget: slower frame interval than the full-quality default.
        self.assertGreaterEqual(hud.wireframe_visualizer._frame_interval, 60)
        self.assertEqual(hud._last_budget_tier, "saver")

    def test_charging_pulse_and_bolt_are_edge_triggered(self):
        hud = self.make_hud()
        readings = [
            BatteryReading(True, 40.0, False),
            BatteryReading(True, 41.0, True),
            BatteryReading(True, 42.0, True),
        ]
        queue = list(readings)
        hud._battery = BatteryMonitor(reader=lambda: queue.pop(0) if queue else BatteryReading(available=False))
        hud._poll_system_status()
        self.assertFalse(hud._heart_reactor.charge_pulse_active())
        hud._poll_system_status()
        self.assertTrue(hud._heart_reactor.charge_pulse_active())
        self.assertTrue(hud._mini_orb._charging)
        self.assertEqual(hud._island._battery_text, "41% ⚡")

    def test_notifications_reach_the_toast_once(self):
        hud = self.make_hud()
        hud._notifications.push(Notification("test:one", "Heads up", "Something happened", PRIORITY_NORMAL))
        hud._drain_notifications()
        app.processEvents()
        self.assertTrue(hud._toast.isVisible())
        self.assertEqual(hud._toast._title, "Heads up")
        hud._toast.dismiss()
        self.assertFalse(hud._toast.isVisible())


class TestIslandAndOverlays(HUDHarness):
    def test_minimise_swaps_in_the_island_without_touching_the_session(self):
        hud = self.make_hud()
        self.bridge.update_state("LISTENING")
        app.processEvents()
        hud._enter_island_mode()
        app.processEvents()
        self.assertTrue(hud._island.isVisible())
        self.assertFalse(hud.isVisible())
        self.assertEqual(hud._island.state, "listening")
        # The bridge — and therefore mic/audio/live state — is untouched.
        self.assertEqual(self.bridge.current_state, "LISTENING")
        self.assertTrue(hud._poll_timer.isActive())

        hud._restore_from_island()
        app.processEvents()
        self.assertFalse(hud._island.isVisible())
        self.assertTrue(hud.isVisible())

    def test_escape_closes_the_dropdown(self):
        hud = self.make_hud()
        hud._toggle_right_dropdown()
        self.assertTrue(hud._right_menu.isVisible())
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        hud.keyPressEvent(event)
        self.assertFalse(hud._right_menu.isVisible())

    def test_preferences_persist_and_apply(self):
        hud = self.make_hud()
        hud._reduced_motion_box.setChecked(True)
        app.processEvents()
        self.assertTrue(hud.preferences().reduced_motion)
        self.assertEqual(self.settings.value("visual/reduced_motion"), True)
        # Reduced motion forces the saver budget regardless of battery level.
        hud._battery = BatteryMonitor(reader=lambda: BatteryReading(True, 95.0, True))
        hud._poll_system_status()
        self.assertEqual(hud._last_budget_tier, "saver")

    def test_battery_saver_toggle_is_respected(self):
        hud = self.make_hud()
        hud._battery_saver_box.setChecked(False)
        app.processEvents()
        hud._battery = BatteryMonitor(reader=lambda: BatteryReading(True, 12.0, False))
        hud._poll_system_status()
        self.assertEqual(hud._last_budget_tier, "full")

    def test_island_notifies_while_minimised(self):
        hud = self.make_hud()
        hud._enter_island_mode()
        app.processEvents()
        hud._notifications.push(Notification("battery:low", "Battery low", "18% left"))
        hud._drain_notifications()
        app.processEvents()
        self.assertIsNotNone(hud._island._notification)
        self.assertEqual(hud._island._notification.title, "Battery low")
        self.assertFalse(hud._toast.isVisible())


class TestPaintSmoke(HUDHarness):
    """Every custom-painted surface must survive a real paint pass.

    A Python exception inside ``paintEvent`` aborts the whole process instead of
    failing one test, so the rendering paths are exercised explicitly (``grab()``
    forces a paint even where the offscreen platform would skip it).
    """

    def test_hud_and_all_overlays_paint(self):
        hud = self.make_hud()
        self.assertFalse(hud.grab().isNull())

        hud._status_strip.set_status("microphone", "error", "no input device")
        hud._status_strip.set_status("network", "unavailable", "")
        self.assertFalse(hud._status_strip.grab().isNull())

        hud._notifications.push(Notification("smoke:toast", "Paint check", "body text"))
        hud._drain_notifications()
        app.processEvents()
        self.assertFalse(hud._toast.grab().isNull())

        hud.begin_command("youtube_video", "Ambient mix")
        app.processEvents()
        panel = hud._task_panels.panel("cmd:youtube_video")
        self.assertFalse(panel.grab().isNull())

        self.assertFalse(hud._heart_reactor.grab().isNull())
        self.assertFalse(hud.wireframe_visualizer.grab().isNull())
        self.assertFalse(hud.bihansa_visualizer.grab().isNull())

        island = hud._island
        island.show()
        island.expand()
        island.show_notification(Notification("smoke:island", "Island", "expanded body"))
        app.processEvents()
        self.assertFalse(island.grab().isNull())
        for state in ("listening", "thinking", "speaking", "error", "privacy"):
            island.set_state(state)
            self.assertFalse(island.grab().isNull(), state)

    def test_terminal_panel_paints_its_state_label(self):
        hud = self.make_hud()
        hud.begin_command("web_search", "query")
        app.processEvents()
        hud.finish_command("web_search", "Results ready.")
        app.processEvents()
        panel = hud._task_panels.panel("cmd:web_search")
        self.assertFalse(panel.grab().isNull())
        self.assertEqual(panel.spec.state, TaskState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
