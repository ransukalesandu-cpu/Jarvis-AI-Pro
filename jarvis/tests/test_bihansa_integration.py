"""Regression tests for the image-free procedural Bihansa hologram."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from jarvis.ui.hologram.bihansa_settings import BihansaModeSettings


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
