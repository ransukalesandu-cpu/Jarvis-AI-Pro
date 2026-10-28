"""Focused tests for the standalone neural rim-light widget."""

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

from PyQt6.QtCore import QCoreApplication, QRectF
from PyQt6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication(sys.argv)

from ui.hologram.holo_rim_light import NeuralRimLight


class TestNeuralRimLight(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        self.host.resize(480, 480)
        self.rim = NeuralRimLight(self.host)
        self.rim.set_bounds_provider(lambda: QRectF(60.0, 60.0, 360.0, 360.0))

        def dispose():
            self.host.close()
            self.host.deleteLater()
            QCoreApplication.sendPostedEvents(None)

        self.addCleanup(dispose)

    def test_audio_energy_is_clamped_and_smoothed(self):
        self.rim.set_audio_energy(2.0)
        self.assertEqual(self.rim._target_energy, 1.0)
        self.rim._tick()
        self.assertAlmostEqual(self.rim._audio_energy, 0.25)

        self.rim.set_audio_energy(float("nan"))
        self.assertEqual(self.rim._target_energy, 0.0)

    def test_unknown_state_uses_safe_fallback(self):
        self.rim.set_state("SOMETHING_UNEXPECTED")
        self.assertAlmostEqual(self.rim._current_alpha_fraction(), 0.12)

    def test_invalid_bounds_provider_falls_back_to_host(self):
        def broken_bounds():
            raise RuntimeError("bounds are temporarily unavailable")

        self.rim.set_bounds_provider(broken_bounds)
        self.assertEqual(self.rim._resolve_bounds(), QRectF(self.host.rect()))

    def test_color_channels_are_clamped(self):
        self.rim.set_colors((300, -4, 10), (1, 2, 3))
        self.assertEqual(self.rim._primary_rgb, (255, 0, 10))
        self.assertEqual(self.rim._accent_rgb, (1, 2, 3))

    def test_performance_budget_does_not_restart_disabled_timer(self):
        self.rim.set_enabled_effect(False)
        self.rim.set_performance_budget(120, 0.3, 0.5)
        self.assertEqual(self.rim._frame_interval_ms, 120)
        self.assertAlmostEqual(self.rim._glow_scale, 0.5)
        self.assertFalse(self.rim._timer.isActive())

    def test_reduced_motion_keeps_base_intensity_without_breathing(self):
        self.rim.set_state("IDLE")
        self.rim.set_reduced_motion(True)
        self.assertAlmostEqual(self.rim._current_alpha_fraction(), 0.20)


if __name__ == "__main__":
    unittest.main()
