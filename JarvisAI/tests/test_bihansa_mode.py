"""Regression tests for the isolated Bihansa Mode foundation."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from JarvisAI.ui.hologram.bihansa_settings import BihansaModeSettings
from JarvisAI.ui.hologram.bihansa_hologram import BihansaHologram


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_mode_defaults_to_jarvis_and_invalid_mode_falls_back(tmp_path):
    store = QSettings(str(tmp_path / "bihansa.ini"), QSettings.Format.IniFormat)
    prefs = BihansaModeSettings(store)
    assert prefs.assistant_mode == "jarvis"
    prefs.assistant_mode = "BIHANSA"
    assert prefs.assistant_mode == "bihansa"
    prefs.assistant_mode = "not-a-mode"
    assert prefs.assistant_mode == "jarvis"


def test_bihansa_preferences_are_bounded_and_reset_only_their_group(tmp_path):
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    store.setValue("other_feature/enabled", True)
    prefs = BihansaModeSettings(store)
    prefs.glow_intensity = 5
    prefs.animation_speed = -1
    prefs.reduced_motion = True
    assert prefs.glow_intensity == 1.5
    assert prefs.animation_speed == 0.0
    assert prefs.reduced_motion is True
    prefs.restore_bihansa_defaults()
    assert prefs.assistant_mode == "jarvis"
    assert prefs.glow_intensity == 1.0
    assert prefs.animation_speed == 1.0
    assert prefs.reduced_motion is False
    assert store.value("other_feature/enabled", type=bool) is True


def test_hologram_state_api_and_audio_energy(app):
    widget = BihansaHologram(reduced_motion=True)
    widget.set_state("speaking")
    assert widget.get_state() == "SPEAKING"
    widget.set_audio_energy(2.0)
    assert widget._target_energy == 1.0
    widget.set_state("unknown-state")
    assert widget.get_state() == "IDLE"
    widget.set_reduced_motion(True)
    widget.set_glow_intensity(0.8)
    widget.set_animation_speed(1.2)
    widget.close()
