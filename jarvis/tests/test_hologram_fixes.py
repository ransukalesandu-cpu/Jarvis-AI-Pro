"""Fixes from the Hologram Engine V2 report: mic level reaches the page as "input", and a page
without WebGL2 hands the screen back to the classic HUD."""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6.QtCore")
from PyQt6.QtCore import QObject, pyqtSignal

from jarvis.core import ui_state
from jarvis.webui import contract
from jarvis.webui.live import AUDIO_MIN_INTERVAL, LiveLink


class Host(QObject):
    ready = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.levels = []

    def set_level(self, v, src="output"): self.levels.append((src, round(v, 3)))
    def set_state(self, s): pass
    def set_persona(self, p): pass
    def set_perf_tier(self, t): pass
    def set_muted(self, m): pass
    def set_provider(self, **kw): pass


@pytest.fixture
def rig():
    bus = ui_state.StateBus()
    t = [0.0]
    host = Host()
    LiveLink(host, bus, clock=lambda: t[0])
    return bus, host, t


def test_mic_level_goes_out_as_input_and_its_mirror_is_not_output(rig):
    bus, host, t = rig
    # what JarvisWindow._apply_audio_level does for the mic: INPUT_LEVEL, then the AUDIO_LEVEL mirror
    bus.set(ui_state.INPUT_LEVEL, 0.42)
    bus.set(ui_state.AUDIO_LEVEL, 0.42)
    assert host.levels == [("input", 0.42)]


def test_jarvis_voice_still_goes_out_as_output(rig):
    bus, host, t = rig
    bus.set(ui_state.INPUT_LEVEL, 0.3)
    t[0] += 1.0                                   # later, JARVIS speaks
    bus.set(ui_state.AUDIO_LEVEL, 0.3)            # same value, but not right after the mic: real output
    bus.set(ui_state.AUDIO_LEVEL, 0.0)
    assert host.levels == [("input", 0.3), ("output", 0.3), ("output", 0.0)]


def test_input_level_is_rate_limited_but_silence_always_passes(rig):
    bus, host, t = rig
    bus.set(ui_state.INPUT_LEVEL, 0.5)
    t[0] += AUDIO_MIN_INTERVAL / 3
    bus.set(ui_state.INPUT_LEVEL, 0.6)            # too soon: dropped
    bus.set(ui_state.INPUT_LEVEL, 0.0)            # silence: always
    assert host.levels == [("input", 0.5), ("input", 0.0)]


def test_capability_request_shape():
    assert contract.parse_request('{"kind":"hologram.capability","webgl2":false}') == {"kind": "hologram.capability", "webgl2": False}
    assert contract.parse_request('{"kind":"hologram.capability","webgl2":"no"}') is None
    assert contract.parse_request('{"kind":"hologram.capability"}') is None


def test_bridge_emits_capability():
    from PyQt6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    from jarvis.webui.bridge import WebUIBridge

    seen = []
    b = WebUIBridge()
    b.capability.connect(seen.append)
    b.request('{"kind":"hologram.capability","webgl2":true}')
    b.request('{"kind":"hologram.capability","webgl2":false}')
    assert seen == [True, False]


def test_host_steps_aside_once_without_webgl2():
    from jarvis.webui.fallback import on_capability

    class FakeHost:                                   # the real _on_capability on a stand-in widget
        fell_back = False
        hidden = 0
        def hide(self): self.hidden += 1
    h = FakeHost()
    assert on_capability(h, True) is False
    assert h.hidden == 0 and not h.fell_back
    assert on_capability(h, False) is True
    assert on_capability(h, False) is False
    assert h.hidden == 1 and h.fell_back


def test_window_tags_mic_levels_as_input(monkeypatch):
    """JarvisUI.set_audio_level passes the source through the GUI-thread signal."""
    from jarvis import ui as ui_mod

    emitted = []

    class Sig:
        def __init__(self, store): self.store = store
        def emit(self, *a): self.store.append(a)

    class Win:
        _audio_level_sig = Sig(emitted)
        _logo_level_sig = Sig([])

    fake = type("F", (), {"_win": Win()})()
    monkeypatch.setattr("jarvis.audio.visualizer_bridge.get_visualizer_bridge", lambda: type("B", (), {"push_audio_energy": lambda s, v: None})())
    ui_mod.JarvisUI.set_audio_level(fake, 0.5, source="input")
    ui_mod.JarvisUI.set_audio_level(fake, 0.25)
    assert emitted == [(0.5, "input"), (0.25, "output")]
