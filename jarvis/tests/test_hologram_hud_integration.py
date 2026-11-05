"""HUD <-> hologram engine wiring, checked without starting Chromium (inert host with a recorder)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from jarvis.audio.visualizer_bridge import VisualizerBridge
from jarvis.hologram.fallback import NullHologram
from jarvis.ui import HudCanvas


class RecordingHost(NullHologram):
    def __init__(self, parent=None, ready=True):
        super().__init__(parent)
        self.is_ready = ready
        self.calls = []

    def set_audio_energy(self, level):
        self.calls.append(("in", round(level, 3)))
        super().set_audio_energy(level)

    def set_output_level(self, level, openness=None, width=None):
        self.calls.append(("out", round(level, 3), openness, width))
        super().set_output_level(level, openness, width)


@pytest.fixture
def canvas():
    c = HudCanvas("face.png", enable_avatar=False)
    c.resize(900, 700)
    yield c
    c.shutdown_hologram()
    c.close()


def test_state_is_forwarded_and_normalised(canvas):
    host = RecordingHost()
    canvas.attach_hologram(host)
    canvas.state = "THINKING"
    canvas._drive_hologram(0.0, None, None, None)
    assert host.state == "thinking"
    canvas.state = "SLEEPING"
    canvas._drive_hologram(0.0, None, None, None)
    assert host.state == "sleeping"


def test_listening_uses_the_input_level(canvas):
    host = RecordingHost()
    canvas.attach_hologram(host)
    canvas.state, canvas.speaking = "LISTENING", False
    canvas._drive_hologram(0.6, None, None, None)
    assert ("in", 0.6) in host.calls
    assert not [c for c in host.calls if c[0] == "out"]


def test_speaking_uses_output_audio_only_never_the_microphone_level(canvas):
    host = RecordingHost()
    canvas.attach_hologram(host)
    canvas.state, canvas.speaking = "SPEAKING", True
    # amp (0.9) is the mixed mic+playback level; the viseme frame is the output side.
    canvas._drive_hologram(0.9, 0.4, 0.7, -0.2)
    assert host.calls == [("out", 0.4, 0.7, -0.2)]
    host.calls.clear()
    canvas._drive_hologram(0.9, None, None, None)          # no viseme and no playback level
    assert host.calls == []
    canvas._on_holo_output(0.55, -1.0, 0.0)                # playback-level fallback from the bridge
    canvas._drive_hologram(0.9, None, None, None)
    assert host.calls and host.calls[0][0] == "out" and host.calls[0][1] == 0.55
    assert not [c for c in host.calls if c[0] == "in"]


def test_engine_replaces_legacy_painters_only_when_ready_and_in_face_mode(canvas):
    assert not canvas._holo_active()
    host = RecordingHost(ready=False)
    canvas.attach_hologram(host)
    canvas.hud_style = "face"
    assert not canvas._holo_active(), "a host that is not ready must leave the legacy painters on"
    host.is_ready = True
    assert canvas._holo_active()
    canvas.hud_style = "neural"
    assert not canvas._holo_active()
    canvas._place_hologram()
    assert host.isHidden(), "the engine is hidden outside face mode"


def test_profile_switch_goes_to_the_engine_and_back(canvas):
    host = RecordingHost()
    canvas.attach_hologram(host)
    canvas.set_hologram_profile("bihansa")
    assert host.profile == "bihansa"
    canvas.set_hologram_profile("jarvis")
    assert host.profile == "jarvis"


def test_engine_sits_inside_the_canvas_over_the_face_band(canvas):
    host = RecordingHost()
    canvas.attach_hologram(host)
    canvas.hud_style = "face"
    canvas._place_hologram()
    g = host.geometry()
    assert g.x() == 0 and g.width() == canvas.width()
    assert 0 <= g.y() and g.y() + g.height() <= canvas.height()
    assert g.height() > canvas.height() * 0.4


def test_shutdown_is_idempotent_and_stops_the_host(canvas):
    host = RecordingHost()
    canvas.attach_hologram(host)
    canvas.shutdown_hologram()
    canvas.shutdown_hologram()
    assert host.shut_down


def test_driving_without_a_host_is_a_noop(canvas):
    canvas._drive_hologram(0.5, None, None, None)


def test_bridge_publishes_output_level_separately_from_the_microphone():
    bridge = VisualizerBridge()
    out, mic, ended = [], [], []
    bridge.sig_output_energy.connect(lambda a, b, c: out.append((a, b, c)))
    bridge.sig_audio_energy.connect(mic.append)
    bridge.sig_output_ended.connect(lambda: ended.append(1))
    bridge.push_output_energy(0.5, 0.3, -0.1)
    bridge.push_output_energy(7.0)
    bridge.push_output_energy("bad")
    bridge.end_output()
    assert out == [(0.5, 0.3, -0.1), (1.0, -1.0, 0.0)]
    assert mic == [], "playback level must not leak into the microphone signal"
    assert ended == [1]


def test_null_hologram_records_and_clamps():
    host = NullHologram()
    host.set_state("PRIVACY_LOCK")
    host.set_audio_energy(5)
    host.set_output_level(-3)
    host.set_profile("nonsense")
    assert (host.state, host.input_level, host.output_level, host.profile) == ("locked", 1.0, 0.0, "jarvis")
