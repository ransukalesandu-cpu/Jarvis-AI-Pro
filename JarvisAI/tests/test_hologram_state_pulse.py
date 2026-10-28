"""Focused lifecycle and state tests for the hologram transition pulse."""

import os
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for path in (str(ROOT_DIR), str(JARVIS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

if sys.platform != "win32" and not os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QCoreApplication, QEvent, QRect, QRectF
from PyQt6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication(sys.argv)

from ui.hologram.holo_state_pulse import HologramStatePulse


class TestHologramStatePulse(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        self.host.resize(400, 400)
        self.pulse = HologramStatePulse(self.host)
        self.pulse.set_bounds_provider(lambda: QRectF(60.0, 55.0, 280.0, 300.0))

        def dispose():
            self.pulse.shutdown()
            self.host.close()
            self.host.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)

    def test_state_change_starts_one_shot_timer(self):
        self.pulse.set_state("LISTENING")
        self.assertEqual(self.pulse.active_pulse_count(), 1)
        self.assertTrue(self.pulse._timer.isActive())

        self.pulse.set_state("LISTENING")
        self.assertEqual(self.pulse.active_pulse_count(), 1)

    def test_warning_aliases_are_rate_limited(self):
        self.pulse.trigger_transition("IDLE", "AUDIO_ERROR")
        self.assertEqual(self.pulse.active_pulse_count(), 1)
        self.assertTrue(self.pulse._pulses[0].warning)

        self.pulse.trigger_transition("AUDIO_ERROR", "CONNECTION_LOST")
        self.assertEqual(self.pulse.active_pulse_count(), 1)

    def test_privacy_lock_cancels_motion_and_uses_static_ring(self):
        self.pulse.set_state("LISTENING")
        self.assertTrue(self.pulse._timer.isActive())

        self.pulse.set_state("LOCKDOWN")
        self.assertEqual(self.pulse.active_pulse_count(), 0)
        self.assertFalse(self.pulse._timer.isActive())
        self.assertTrue(self.pulse.is_lock_static_active())

    def test_reduced_motion_changes_future_pulses_only(self):
        self.pulse.set_state("LISTENING")
        normal_duration = self.pulse._pulses[0].duration

        self.pulse.set_reduced_motion(True)
        self.pulse.trigger_transition("LISTENING", "THINKING")
        reduced_duration = self.pulse._pulses[-1].duration
        self.assertLess(reduced_duration, normal_duration)
        self.assertAlmostEqual(self.pulse._pulses[0].duration, normal_duration)

    def test_concurrent_queue_is_bounded(self):
        for old_state, new_state in (
            ("IDLE", "LISTENING"),
            ("LISTENING", "THINKING"),
            ("THINKING", "SPEAKING"),
            ("SPEAKING", "IDLE"),
            ("IDLE", "LISTENING"),
        ):
            self.pulse.trigger_transition(old_state, new_state)
        self.assertLessEqual(
            self.pulse.active_pulse_count(),
            HologramStatePulse.MAX_CONCURRENT_PULSES,
        )

    def test_disabling_clears_pulses_and_stops_timer(self):
        self.pulse.set_state("LISTENING")
        self.pulse.set_enabled_effect(False)
        self.assertEqual(self.pulse.active_pulse_count(), 0)
        self.assertFalse(self.pulse._timer.isActive())
        self.assertFalse(self.pulse.isVisible())

    def test_reenable_during_privacy_lock_keeps_static_mode(self):
        self.pulse.set_enabled_effect(False)
        self.pulse.set_state("PRIVACY_LOCK")
        self.pulse.set_enabled_effect(True)
        self.assertTrue(self.pulse.is_lock_static_active())
        self.assertFalse(self.pulse._timer.isActive())

    def test_expired_pulse_stops_timer(self):
        self.pulse.set_state("LISTENING")
        self.pulse._pulses[0].start -= 2.0
        self.pulse._tick()
        self.assertEqual(self.pulse.active_pulse_count(), 0)
        self.assertFalse(self.pulse._timer.isActive())

    def test_rgb_validation_and_clamping(self):
        self.pulse.set_colors((300, -10, 64), (1, 2, 3))
        self.assertEqual(self.pulse._primary_rgb, (255, 0, 64))
        with self.assertRaises(TypeError):
            self.pulse.set_colors("bad", (1, 2, 3))
        with self.assertRaises(ValueError):
            self.pulse.set_warning_color((1, 2))

    def test_bounds_provider_fallback_and_invalid_provider_contract(self):
        self.pulse.set_bounds_provider(lambda: QRect())
        self.assertEqual(self.pulse._resolve_bounds(), QRectF(self.host.rect()))

        def deleted_host():
            raise RuntimeError("Qt object deleted during teardown")

        self.pulse.set_bounds_provider(deleted_host)
        self.assertEqual(self.pulse._resolve_bounds(), QRectF(self.host.rect()))

        def programming_error():
            raise AttributeError("provider API is incorrect")

        self.pulse.set_bounds_provider(programming_error)
        with self.assertRaises(AttributeError):
            self.pulse._resolve_bounds()

    def test_shutdown_is_idempotent(self):
        self.pulse.set_state("THINKING")
        self.pulse.shutdown()
        self.pulse.shutdown()
        self.assertFalse(self.pulse._timer.isActive())
        self.assertEqual(self.pulse.active_pulse_count(), 0)


if __name__ == "__main__":
    unittest.main()
