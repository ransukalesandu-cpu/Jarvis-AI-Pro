"""Tests for the HUD wiring: producer panels, media transport, responsive chrome.

Two behaviours are new and both are about honesty:

* a background producer (reminders, downloads) can open a panel exactly like a
  voice command does, and the manager updates that card in place rather than
  rebuilding it every poll;
* the music panel's play/pause/next buttons only exist when this machine can
  actually deliver a media key.
"""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

if sys.platform != "win32" and not os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import unittest

from PyQt6.QtCore import QCoreApplication, QEvent, QRect
from PyQt6.QtWidgets import QApplication, QToolButton, QWidget

app = QApplication.instance() or QApplication(sys.argv)

from core.hologram_theme import JARVIS_PALETTE
from core.media_transport import TransportController
from core.task_sources import SourceTask
from ui.task_panels import TaskKind, TaskPanelManager, TaskSpec, TaskState

FACE = QRect(400, 120, 480, 380)


class PanelHarness(unittest.TestCase):
    def setUp(self):
        self._widgets = []

    def track(self, widget):
        self._widgets.append(widget)
        return widget

    def tearDown(self):
        for widget in self._widgets:
            try:
                widget.close()
                widget.deleteLater()
            except RuntimeError:
                pass
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        except RuntimeError:
            pass

    def manager(self, size=(1280, 720)):
        stage = self.track(QWidget())
        stage.resize(*size)
        manager = self.track(TaskPanelManager(stage, JARVIS_PALETTE))
        manager.resize(*size)
        manager.set_blocked_rect(FACE)
        return manager


def _reminder(title="Call the bank"):
    return SourceTask(
        key="source:reminder", kind=TaskKind.REMINDER, title=title,
        subtitle="29 Oct 09:00", detail="1 pending intention(s)", state="waiting",
    )


def _download(title="Portal 2"):
    return SourceTask(
        key="source:download", kind=TaskKind.DOWNLOAD, title=title,
        subtitle="DOWNLOADING",
    )


class TestSourceSync(PanelHarness):
    def test_a_reported_task_opens_a_panel(self):
        manager = self.manager()
        live = manager.sync_sources([_reminder()])
        self.assertEqual(live, ["source:reminder"])
        self.assertTrue(manager.has_task("source:reminder"))
        self.assertEqual(manager.panel("source:reminder").spec.kind, TaskKind.REMINDER)
        # A reminder is scheduled, not running: no sweeping progress bar.
        self.assertEqual(manager.panel("source:reminder").spec.state, TaskState.WAITING)

    def test_a_download_is_running_and_indeterminate(self):
        manager = self.manager()
        manager.sync_sources([_download()])
        spec = manager.panel("source:download").spec
        self.assertEqual(spec.state, TaskState.RUNNING)
        self.assertIsNone(spec.progress)

    def test_an_unknown_producer_state_falls_back_to_running(self):
        manager = self.manager()
        manager.sync_sources([SourceTask(key="source:odd", kind="generic", title="X", state="???")])
        self.assertEqual(manager.panel("source:odd").spec.state, TaskState.RUNNING)

    def test_a_still_reported_task_is_updated_in_place(self):
        manager = self.manager()
        manager.sync_sources([_reminder()])
        first = manager.panel("source:reminder")
        manager.sync_sources([_reminder(title="Call the bank now")])
        self.assertIs(manager.panel("source:reminder"), first)
        self.assertEqual(first.spec.title, "Call the bank now")

    def test_a_task_that_stops_being_reported_closes_its_panel(self):
        manager = self.manager()
        manager.sync_sources([_reminder(), _download()])
        live = manager.sync_sources([_reminder()])
        self.assertEqual(live, ["source:reminder"])
        self.assertFalse(manager.has_task("source:download"))

    def test_producer_panels_never_touch_voice_command_panels(self):
        manager = self.manager()
        manager.open_task(TaskSpec(task_id="cmd:play_music", kind=TaskKind.MUSIC,
                                   title="Playing", state=TaskState.RUNNING))
        manager.sync_sources([_reminder()])
        manager.sync_sources([])
        self.assertTrue(manager.has_task("cmd:play_music"))
        self.assertFalse(manager.has_task("source:reminder"))

    def test_sync_is_idempotent(self):
        manager = self.manager()
        tasks = [_reminder(), _download()]
        first = manager.sync_sources(tasks)
        second = manager.sync_sources(tasks)
        self.assertEqual(first, second)
        self.assertEqual(sorted(manager.task_ids()), ["source:download", "source:reminder"])

    def test_a_dismissed_source_panel_stays_closed_while_still_reported(self):
        manager = self.manager()
        manager.sync_sources([_reminder()])
        manager.panel("source:reminder").sig_dismiss.emit("source:reminder")
        self.assertFalse(manager.has_task("source:reminder"))
        manager.sync_sources([_reminder()])
        self.assertFalse(manager.has_task("source:reminder"))

    def test_a_dismissed_panel_returns_when_the_producer_reports_it_again(self):
        manager = self.manager()
        manager.sync_sources([_reminder()])
        manager.dismiss_source("source:reminder")
        manager.sync_sources([_reminder()])
        self.assertFalse(manager.has_task("source:reminder"))
        # The reminder came due / was cleared, then a new one appears.
        manager.sync_sources([])
        manager.sync_sources([_reminder("Pay the bill")])
        self.assertTrue(manager.has_task("source:reminder"))
        self.assertEqual(manager.panel("source:reminder").spec.title, "Pay the bill")

    def test_dismiss_source_refuses_foreign_ids(self):
        manager = self.manager()
        manager.open_task(TaskSpec(task_id="cmd:x", title="X"))
        self.assertFalse(manager.dismiss_source("cmd:x"))
        self.assertTrue(manager.has_task("cmd:x"))

    def test_a_key_without_the_prefix_still_gets_one(self):
        manager = self.manager()
        live = manager.sync_sources([SourceTask(key="download", kind="download", title="D")])
        self.assertEqual(live, ["source:download"])

    def test_a_task_with_no_key_is_ignored(self):
        manager = self.manager()
        self.assertEqual(manager.sync_sources([SourceTask(key="", kind=TaskKind.GENERIC, title="dropped")]), [])
        self.assertEqual(manager.task_ids(), [])


class TestTransportControlsOnThePanel(PanelHarness):
    def _music_spec(self, **kwargs):
        return TaskSpec(task_id="media:now", kind=TaskKind.MUSIC, title="Playing",
                        subtitle="MEDIA", state=TaskState.RUNNING, **kwargs)

    def _buttons(self, panel):
        return {b.toolTip(): b for b in panel.findChildren(QToolButton)}

    def test_no_callbacks_means_no_transport_buttons(self):
        manager = self.manager()
        panel = manager.open_task(self._music_spec())
        buttons = self._buttons(panel)
        self.assertNotIn("Play/pause", buttons)
        self.assertNotIn("Next track", buttons)
        self.assertNotIn("Previous track", buttons)

    def test_callbacks_from_a_real_transport_draw_the_buttons(self):
        manager = self.manager()
        spec = self._music_spec(**TransportController(press=lambda key: None).callbacks())
        panel = manager.open_task(spec)
        buttons = self._buttons(panel)
        self.assertEqual(
            set(buttons),
            {"Play/pause", "Next track", "Previous track"},
        )

    def test_pressing_play_pause_sends_a_real_media_key(self):
        pressed = []
        controller = TransportController(press=pressed.append)
        manager = self.manager()
        spec = self._music_spec(**controller.callbacks())
        manager.open_task(spec)
        buttons = self._buttons(manager.panel("media:now"))
        buttons["Play/pause"].click()
        self.assertEqual(pressed, ["playpause"])

    def test_the_glyph_follows_a_delivered_key_only(self):
        controller = TransportController(press=lambda key: None)
        manager = self.manager()
        manager.open_task(self._music_spec(**controller.callbacks()))
        panel = manager.panel("media:now")
        self.assertIn("▶", {b.text() for b in panel.findChildren(QToolButton)})

        controller.play_pause()
        manager.update_task("media:now", playing=controller.playing)
        self.assertIn("⏸", {b.text() for b in panel.findChildren(QToolButton)})

    def test_a_rejected_key_leaves_the_glyph_alone(self):
        def refuse(_key):
            raise RuntimeError("no keyboard backend")

        controller = TransportController(press=refuse)
        manager = self.manager()
        manager.open_task(self._music_spec(**controller.callbacks()))
        controller.play_pause()
        manager.update_task("media:now", playing=controller.playing)
        panel = manager.panel("media:now")
        self.assertIn("▶", {b.text() for b in panel.findChildren(QToolButton)})


class TestHudWiring(PanelHarness):
    """The HUD must use these pieces, not just contain them."""

    def setUp(self):
        super().setUp()
        from ui.hud_main import HUDMainWindow

        self.window = self.track(HUDMainWindow())

    def test_the_battery_dialog_opens_on_the_live_thresholds(self):
        from ui.panels.battery_settings import BatteryThresholdsDialog

        captured = {}

        def fake_exec(dialog_self):
            captured["thresholds"] = dialog_self.thresholds()
            return 0

        original = BatteryThresholdsDialog.exec
        BatteryThresholdsDialog.exec = fake_exec
        try:
            dialog = self.window._open_battery_settings()
        finally:
            BatteryThresholdsDialog.exec = original
            dialog.deleteLater()
        self.assertEqual(captured["thresholds"], self.window._battery.thresholds)

    def test_saving_thresholds_updates_the_monitor_and_the_performance_tiers(self):
        from core.system_status import BatteryThresholds

        self.window._apply_battery_thresholds(BatteryThresholds(60, 35, 15, 95))
        self.assertEqual(self.window._battery.thresholds, BatteryThresholds(60, 35, 15, 95))
        self.assertEqual(self.window._performance.saver_percent, 35)
        self.assertEqual(self.window._performance.balanced_percent, 60)
        # And it is persisted, so the next launch reads the same bands.
        stored = self.window._settings.value("battery/low")
        self.assertEqual(int(stored), 35)

    def test_the_source_registry_is_polled_and_creates_panels(self):
        from core.task_sources import TaskSourceRegistry

        self.window._task_sources = TaskSourceRegistry(
            {"reminders": lambda: _reminder("Stand up")}
        )
        self.window._sync_task_sources()
        self.assertTrue(self.window._task_panels.has_task("source:reminder"))

        self.window._task_sources = TaskSourceRegistry({"reminders": lambda: None})
        self.window._sync_task_sources()
        self.assertFalse(self.window._task_panels.has_task("source:reminder"))

    def test_a_failing_producer_does_not_break_the_poll(self):
        def broken():
            raise RuntimeError("memory unreadable")

        from core.task_sources import TaskSourceRegistry

        self.window._task_sources = TaskSourceRegistry({"reminders": broken})
        self.window._sync_task_sources()   # must not raise
        self.assertEqual(self.window._task_panels.task_ids(), [])

    # -- now-playing card ---------------------------------------------------
    def _run_command(self, action, result):
        """Drive one real tool call through the HUD's start/finish pair."""
        self.window._on_command_started(action, "")
        self.window._on_command_finished(action, result)

    def test_a_successful_music_command_opens_a_now_playing_card(self):
        self._run_command("play_music", "Searching YouTube for lofi beats.")
        self.assertTrue(self.window._task_panels.has_task("media:now"))
        spec = self.window._task_panels.panel("media:now").spec
        self.assertEqual(spec.kind, TaskKind.MUSIC)
        # A control surface is not "progress": no indeterminate sweep.
        self.assertEqual(spec.state, TaskState.WAITING)
        self.assertEqual(spec.title, "Searching YouTube for lofi beats.")

    def test_a_failed_music_command_opens_no_card(self):
        self._run_command("play_music", "I could not open the browser.")
        self.assertFalse(self.window._task_panels.has_task("media:now"))

    def test_a_non_music_command_opens_no_card(self):
        self._run_command("web_search", "Found three results.")
        self.assertFalse(self.window._task_panels.has_task("media:now"))

    def test_without_a_media_backend_the_card_says_so_and_shows_no_buttons(self):
        from core import media_transport

        original = media_transport._presser
        media_transport._presser = lambda: None
        try:
            self._run_command("play_music", "Searching YouTube for jazz.")
        finally:
            media_transport._presser = original
        panel = self.window._task_panels.panel("media:now")
        self.assertIn("UNAVAILABLE", panel.spec.subtitle)
        self.assertEqual(panel.spec.on_play_pause, None)
        self.assertEqual(panel.spec.on_next, None)
        self.assertEqual(panel.spec.on_previous, None)
        self.assertNotIn("Play/pause", {b.toolTip() for b in panel.findChildren(QToolButton)})

    def test_dismissing_the_now_playing_card_removes_it(self):
        self._run_command("play_music", "Searching YouTube for jazz.")
        self.window._dismiss_now_playing()
        self.assertFalse(self.window._task_panels.has_task("media:now"))
        self.assertTrue(self.window._now_playing_dismissed)

    def test_a_wrapped_source_tick_never_raises(self):
        self.window._poll_system_status()
        self.window._source_tick = 3
        self.window._poll_system_status()   # hits the %4 branch


if __name__ == "__main__":
    unittest.main()


class TestResponsiveChromeIsApplied(PanelHarness):
    """The window must *use* these numbers, not keep its own constants."""

    def setUp(self):
        super().setUp()
        from core import hud_layout
        from ui.hud_main import HUDMainWindow

        self.layout = hud_layout
        self.window = self.track(HUDMainWindow())

    def _sizes_at(self, width, height):
        self.window.resize(width, height)
        self.window._apply_responsive_chrome()
        return self.window._left_rail.width(), self.window._right_menu.width()

    def test_a_wide_window_uses_the_full_rail_and_dropdown(self):
        rail, menu = self._sizes_at(1800, 1000)
        self.assertEqual(rail, self.layout.rail_width(1800))
        self.assertEqual(menu, self.layout.dropdown_width(1800))

    def test_a_narrow_window_shrinks_both(self):
        wide_rail, wide_menu = self._sizes_at(1800, 1000)
        # The window's own minimum is 860 px, so narrow means "at the minimum".
        narrow_rail, narrow_menu = self._sizes_at(860, 700)
        self.assertLess(narrow_rail, wide_rail)
        self.assertLess(narrow_menu, wide_menu)
        self.assertGreaterEqual(narrow_menu, self.layout.DROPDOWN_MIN)

    def test_rail_buttons_follow_the_rail(self):
        self._sizes_at(860, 700)
        rail = self.window._left_rail.width()
        expected = self.layout.rail_button_size(self.window.width())
        for button in self.window._left_icon_buttons:
            self.assertEqual(button.width(), expected)
            self.assertLess(button.width(), rail)


if __name__ == "__main__":
    unittest.main()
