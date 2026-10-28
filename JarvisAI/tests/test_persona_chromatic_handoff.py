"""Lifecycle and geometry tests for the persona chromatic handoff overlay."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for path in (str(ROOT_DIR), str(JARVIS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

if sys.platform != "win32" and not os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication(sys.argv)

from ui.hologram.holo_persona_handoff import (
    DEFAULT_DURATION_MS,
    MIN_DURATION_MS,
    MAX_DURATION_MS,
    PRIVACY_LOCK_DURATION_MS,
    REDUCED_MOTION_DURATION_MS,
    PersonaChromaticHandoff,
)

JARVIS_PRIMARY = (255, 157, 77)
JARVIS_ACCENT = (255, 199, 120)
BIHANSA_PRIMARY = (236, 64, 122)
BIHANSA_ACCENT = (255, 160, 200)


class TestPersonaChromaticHandoff(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        self.host.resize(500, 500)
        self.effect = PersonaChromaticHandoff(self.host)
        self.effect.set_bounds_provider(lambda: QRectF(150.0, 120.0, 200.0, 260.0))

    def tearDown(self):
        self.effect.shutdown()
        self.host.close()
        self.host.deleteLater()
        app.processEvents()

    def trigger(self, target_primary=BIHANSA_PRIMARY, target_accent=BIHANSA_ACCENT, duration=None):
        self.effect.trigger_handoff(
            JARVIS_PRIMARY, JARVIS_ACCENT, target_primary, target_accent, duration
        )

    def test_starts_hidden_and_idle_without_timer(self):
        self.assertFalse(self.effect.active())
        self.assertFalse(self.effect.isVisible())
        self.assertFalse(self.effect._timer.isActive())

    def test_trigger_shows_overlay_and_starts_single_timer(self):
        self.trigger()
        self.assertTrue(self.effect.active())
        self.assertTrue(self.effect.isVisible())
        self.assertTrue(self.effect._timer.isActive())

    def test_completion_clears_state_hides_overlay_and_stops_timer(self):
        self.trigger()
        self.effect._state.start_time -= self.effect._state.duration_s + 0.01
        self.effect._tick()
        self.assertFalse(self.effect.active())
        self.assertFalse(self.effect.isVisible())
        self.assertFalse(self.effect._timer.isActive())

    def test_duplicate_target_is_a_noop(self):
        with patch("ui.hologram.holo_persona_handoff.time.monotonic", return_value=10.0):
            self.trigger()
            original_start = self.effect._state.start_time
            self.trigger()
            self.assertEqual(self.effect._state.start_time, original_start)

    def test_retarget_starts_from_current_blend_and_preserves_rotation_phase(self):
        with patch("ui.hologram.holo_persona_handoff.time.monotonic") as clock:
            clock.return_value = 10.0
            self.trigger()
            clock.return_value = 10.25
            blended = self.effect._current_colors(10.25)
            rotation = self.effect._current_rotation(10.25)
            self.effect.trigger_handoff(
                JARVIS_PRIMARY, JARVIS_ACCENT, (30, 60, 90), (40, 70, 100)
            )
            self.assertEqual(self.effect._state.old_primary, blended[0])
            self.assertEqual(self.effect._state.old_accent, blended[1])
            self.assertAlmostEqual(self.effect._state.base_rotation_deg, rotation)
            self.assertEqual(self.effect._state.start_time, 10.25)

    def test_reverse_uses_current_blend_and_previous_start_colour_as_target(self):
        with patch("ui.hologram.holo_persona_handoff.time.monotonic") as clock:
            clock.return_value = 5.0
            self.trigger()
            clock.return_value = 5.2
            blended = self.effect._current_colors(5.2)
            self.effect.reverse_active_handoff()
            self.assertEqual(self.effect._state.old_primary, blended[0])
            self.assertEqual(self.effect._state.new_primary, JARVIS_PRIMARY)
            self.assertEqual(self.effect._state.new_accent, JARVIS_ACCENT)

    def test_normal_duration_is_clamped(self):
        self.trigger(duration=50)
        self.assertAlmostEqual(self.effect._state.duration_s * 1000, MIN_DURATION_MS)
        self.effect._cancel_active()
        self.trigger(duration=5000)
        self.assertAlmostEqual(self.effect._state.duration_s * 1000, MAX_DURATION_MS)

    def test_default_duration_is_550ms(self):
        self.trigger()
        self.assertAlmostEqual(self.effect._state.duration_s * 1000, DEFAULT_DURATION_MS)

    def test_reduced_motion_is_static_and_short(self):
        self.effect.set_reduced_motion(True)
        self.trigger()
        self.assertEqual(self.effect._state.profile, "reduced")
        self.assertAlmostEqual(
            self.effect._state.duration_s * 1000, REDUCED_MOTION_DURATION_MS
        )
        self.assertEqual(self.effect._current_rotation(10**9), 0.0)

    def test_privacy_lock_reduces_active_effect_immediately(self):
        with patch("ui.hologram.holo_persona_handoff.time.monotonic") as clock:
            clock.return_value = 20.0
            self.trigger()
            clock.return_value = 20.15
            blended = self.effect._current_colors(20.15)
            self.effect.set_privacy_lock_active(True)
            self.assertEqual(self.effect._state.profile, "privacy")
            self.assertEqual(self.effect._state.old_primary, blended[0])
            self.assertAlmostEqual(
                self.effect._state.duration_s * 1000, PRIVACY_LOCK_DURATION_MS
            )
            self.assertEqual(self.effect._current_rotation(20.2), 0.0)

    def test_annulus_excludes_face_interior(self):
        clip = self.effect._annulus_clip_path(QRectF(100.0, 100.0, 200.0, 200.0))
        self.assertFalse(clip.contains(QPointF(200.0, 200.0)))
        self.assertFalse(clip.contains(QPointF(230.0, 200.0)))
        self.assertTrue(clip.contains(QPointF(310.0, 200.0)))

    def test_invalid_rgb_raises(self):
        with self.assertRaises(TypeError):
            self.effect.trigger_handoff((1, 2), JARVIS_ACCENT, BIHANSA_PRIMARY, BIHANSA_ACCENT)
        with self.assertRaises(TypeError):
            self.effect.trigger_handoff(
                (True, 2, 3), JARVIS_ACCENT, BIHANSA_PRIMARY, BIHANSA_ACCENT
            )

    def test_out_of_range_rgb_is_clamped(self):
        with patch("ui.hologram.holo_persona_handoff.time.monotonic", return_value=1.0):
            self.effect.trigger_handoff(
                (300, -10, 128), (0, 0, 0), BIHANSA_PRIMARY, BIHANSA_ACCENT
            )
            self.assertEqual(self.effect._state.old_primary, (255, 0, 128))

    def test_runtime_error_from_bounds_provider_is_treated_as_teardown(self):
        self.effect.set_bounds_provider(lambda: (_ for _ in ()).throw(RuntimeError("deleted")))
        self.assertIsNone(self.effect._resolve_bounds())

    def test_other_bounds_provider_errors_propagate(self):
        self.effect.set_bounds_provider(lambda: (_ for _ in ()).throw(ValueError("bad callback")))
        with self.assertRaises(ValueError):
            self.effect._resolve_bounds()

    def test_disabling_clears_overlay_immediately(self):
        self.trigger()
        self.effect.set_enabled_effect(False)
        self.assertFalse(self.effect.active())
        self.assertFalse(self.effect.isVisible())
        self.assertFalse(self.effect._timer.isActive())
        self.trigger()
        self.assertFalse(self.effect.active())

    def test_shutdown_is_idempotent(self):
        self.trigger()
        self.effect.shutdown()
        self.effect.shutdown()
        self.assertFalse(self.effect.active())
        self.assertFalse(self.effect._timer.isActive())


if __name__ == "__main__":
    unittest.main()
