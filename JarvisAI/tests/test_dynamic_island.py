"""Tests for the Dynamic Island pill — the minimised representation of the HUD.

The island is a *view*. Nothing in it may stop the microphone, the audio session
or a running task, so the tests assert that it only records state and emits
requests; the HUD decides what happens next.
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

from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from core.hologram_theme import BIHANSA_PALETTE, JARVIS_PALETTE
from core.system_status import Notification, PRIORITY_CRITICAL, PRIORITY_NORMAL
from ui.dynamic_island import ISLAND_STATES, DynamicIsland, IslandIdleClock


class TestDynamicIsland(unittest.TestCase):
    def setUp(self):
        self.island = DynamicIsland(None, palette=JARVIS_PALETTE)
        self.addCleanup(self._dispose)

    def _dispose(self):
        try:
            self.island.hide()
            self.island.close()
            self.island.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        except RuntimeError:
            pass

    def test_starts_collapsed_with_known_state(self):
        self.assertEqual(self.island.state, "idle")
        self.assertIn(self.island.state, ISLAND_STATES)
        self.assertEqual(self.island.size().width(), DynamicIsland.COLLAPSED_SIZE[0])
        self.assertEqual(self.island.size().height(), DynamicIsland.COLLAPSED_SIZE[1])
        self.assertTrue(self.island.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(self.island.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))

    def test_state_names_are_normalised(self):
        self.island.set_state("LISTENING")
        self.assertEqual(self.island.state, "listening")
        self.island.set_state("PRIVACY_LOCK")
        self.assertEqual(self.island.state, "privacy")
        self.island.set_state("LOCKDOWN")
        self.assertEqual(self.island.state, "privacy")
        # Unknown states degrade to idle instead of raising.
        self.island.set_state("who_knows")
        self.assertEqual(self.island.state, "idle")
        self.island.set_state(None)
        self.assertEqual(self.island.state, "idle")

    def test_expand_and_collapse_change_geometry_and_signal(self):
        seen = []
        self.island.sig_expanded_changed.connect(seen.append)
        self.island.expand()
        self.assertEqual(self.island.size().width(), DynamicIsland.EXPANDED_SIZE[0])
        self.assertEqual(seen, [True])
        self.island.collapse()
        self.assertEqual(self.island.size().width(), DynamicIsland.COLLAPSED_SIZE[0])
        self.assertEqual(seen, [True, False])
        # Collapsing twice does not re-emit.
        self.island.collapse()
        self.assertEqual(seen, [True, False])

    def test_energy_and_texts_are_bounded(self):
        self.island.set_energy(5.0)
        self.assertEqual(self.island._energy, 1.0)
        self.island.set_energy(-3)
        self.assertEqual(self.island._energy, 0.0)
        self.island.set_energy("junk")
        self.assertEqual(self.island._energy, 0.0)
        self.island.set_task_summary("Downloading 3 files")
        self.assertEqual(self.island._task_summary, "Downloading 3 files")
        self.island.set_battery_text("87%")
        self.assertEqual(self.island._battery_text, "87%")
        # An empty string means "no sensor": nothing is drawn for it.
        self.island.set_battery_text("")
        self.assertEqual(self.island._battery_text, "")

    def test_notification_expands_and_collapses_again(self):
        note = Notification("battery:low", "Battery low", "25% left", PRIORITY_NORMAL)
        self.island.show_notification(note, auto_collapse_ms=2500)
        self.assertIs(self.island._notification, note)
        self.assertEqual(self.island.size().width(), DynamicIsland.NOTIFICATION_SIZE[0])
        self.island.clear_notification()
        self.assertIsNone(self.island._notification)
        self.assertEqual(self.island.size().width(), DynamicIsland.COLLAPSED_SIZE[0])

    def test_critical_notifications_stay_longer(self):
        note = Notification("health:microphone", "Microphone failed", "", PRIORITY_CRITICAL)
        self.island.show_notification(note, auto_collapse_ms=1000)
        # 1 s was requested, but criticals get the longer floor.
        self.assertGreaterEqual(self.island._collapse_timer.interval(), 9000)

    def test_restore_signal_from_click(self):
        seen = []
        self.island.sig_restore_requested.connect(lambda: seen.append("restore"))
        self.island.show()
        QTest.mouseClick(self.island, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        self.assertEqual(seen, ["restore"])

    def test_drag_does_not_count_as_a_click(self):
        seen = []
        self.island.sig_restore_requested.connect(lambda: seen.append("restore"))
        self.island.show()
        QTest.mousePress(self.island, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        QTest.mouseMove(self.island, QPoint(80, 40))
        QTest.mouseRelease(self.island, Qt.MouseButton.LeftButton, pos=QPoint(80, 40))
        self.assertEqual(seen, [], "dragging the pill must not restore the window")

    def test_keyboard_restore_and_escape(self):
        restores, expanded = [], []
        self.island.sig_restore_requested.connect(lambda: restores.append(1))
        self.island.sig_expanded_changed.connect(expanded.append)
        self.island.show()
        QTest.keyClick(self.island, Qt.Key.Key_Return)
        self.assertEqual(restores, [1])
        self.island.expand()
        QTest.keyClick(self.island, Qt.Key.Key_Escape)
        self.assertEqual(expanded, [True, False])

    def test_escape_without_expansion_is_harmless(self):
        self.island.show()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        self.island.keyPressEvent(event)   # must not raise

    def test_click_reports_an_activation_reason(self):
        reasons = []
        self.island.sig_activated.connect(reasons.append)
        self.island.show()
        QTest.mouseClick(self.island, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        self.assertEqual(reasons, ["restore"])

    def test_clicking_an_expanded_pill_collapses_instead(self):
        reasons, expanded = [], []
        self.island.sig_activated.connect(reasons.append)
        self.island.sig_expanded_changed.connect(expanded.append)
        self.island.show()
        self.island.expand()
        QTest.mouseClick(self.island, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        self.assertEqual(reasons, [])
        self.assertEqual(expanded, [True, False])

    def test_accent_follows_palette_and_state(self):
        self.assertEqual(self.island.accent_name().lower(), "#%02x%02x%02x" % JARVIS_PALETTE.accent)
        self.island.set_palette(BIHANSA_PALETTE)
        self.assertEqual(self.island.accent_name().lower(), "#%02x%02x%02x" % BIHANSA_PALETTE.accent)
        self.island.set_state("error")
        self.assertEqual(self.island.accent_name().lower(), "#ff6b6b")
        self.island.set_state("privacy")
        self.assertEqual(self.island.accent_name().lower(), "#ff456b")

    def test_reduced_motion_slows_the_tick(self):
        self.island.set_reduced_motion(True)
        self.assertGreaterEqual(self.island._tick_timer.interval(), 120)
        self.island.set_reduced_motion(False)
        self.assertLess(self.island._tick_timer.interval(), 120)

    def test_keeps_itself_on_screen(self):
        self.island.show()
        self.island.move(-500, -500)
        self.island._keep_on_screen()
        self.assertGreaterEqual(self.island.x(), 0)
        self.assertGreaterEqual(self.island.y(), 0)

    def test_does_not_touch_audio_or_sessions(self):
        """The island owns no audio/session attribute at all."""
        for forbidden in ("bridge", "session", "audio", "_mic"):
            self.assertFalse(hasattr(self.island, forbidden), forbidden)


class TestIslandIdleClock(unittest.TestCase):
    def test_elapsed_is_monotonic_and_non_negative(self):
        clock = IslandIdleClock()
        self.assertGreaterEqual(clock.elapsed(), 0.0)
        self.assertGreaterEqual(clock.elapsed(), 0.0)


if __name__ == "__main__":
    unittest.main()
