"""Regression tests for the image-free procedural Bihansa hologram."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

from ui.hologram.bihansa_hologram import BihansaHologramWidget
from ui.hologram.bihansa_settings import BihansaModeSettings


class BihansaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = BihansaModeSettings(
            # Use an isolated INI file so tests never change real user preferences.
            settings=__import__("PyQt6.QtCore", fromlist=["QSettings"]).QSettings(
                str(Path(self.tmp.name) / "settings.ini"),
                __import__("PyQt6.QtCore", fromlist=["QSettings"]).QSettings.Format.IniFormat,
            )
        )

    def test_procedural_face_renders_without_image_assets(self):
        widget = BihansaHologramWidget()
        self.addCleanup(widget.close)
        widget.set_reduced_motion(True)
        widget.resize(640, 640)
        image = QImage(640, 640, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            widget.render(painter)
        finally:
            painter.end()
        self.assertFalse(image.isNull())
        self.assertGreater(image.pixelColor(320, 300).alpha(), 0)

    def test_audio_energy_and_visemes_drive_mouth(self):
        widget = BihansaHologramWidget()
        self.addCleanup(widget.close)
        widget.set_state("SPEAKING")
        widget.set_audio_energy(0.9)
        widget._tick()
        self.assertGreater(widget._target_energy, 0.8)
        self.assertGreater(widget._mouth_open(), 0.0)
        widget.set_viseme("aa", 1.0)
        self.assertGreater(widget._viseme_weights["aa"], 0.9)

    def test_voice_reactive_toggle_clears_audio_energy(self):
        widget = BihansaHologramWidget()
        self.addCleanup(widget.close)
        widget.set_audio_energy(0.8)
        widget.set_voice_reactive(False)
        self.assertEqual(widget._target_energy, 0.0)
        self.assertEqual(widget._audio_energy, 0.0)

    def test_settings_persist_and_clamp_values(self):
        self.settings.glow_intensity = 10
        self.settings.animation_speed = -5
        self.assertEqual(self.settings.glow_intensity, 1.5)
        self.assertEqual(self.settings.animation_speed, 0.0)
        self.settings.reduced_motion = True
        self.assertTrue(self.settings.reduced_motion)

    def test_reset_only_changes_bihansa_preferences(self):
        qsettings = self.settings._settings
        qsettings.setValue("other/enabled", True)
        self.settings.glow_intensity = 0.4
        self.settings.restore_bihansa_defaults()
        self.assertEqual(self.settings.glow_intensity, 1.0)
        self.assertTrue(qsettings.value("other/enabled", type=bool))


if __name__ == "__main__":
    unittest.main()
