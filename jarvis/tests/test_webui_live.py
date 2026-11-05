"""LiveLink: the web UI mirrors the state bus, honestly, and nothing flows back as a command."""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6.QtCore")
from PyQt6.QtCore import QObject, pyqtSignal

from jarvis.core import ui_state
from jarvis.webui.live import AUDIO_MIN_INTERVAL, LiveLink, map_state


class FakeHost(QObject):
    ready = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.calls = []

    def set_state(self, s): self.calls.append(("state", s))
    def set_level(self, v, src="output"): self.calls.append(("level", round(v, 3)))
    def set_persona(self, p): self.calls.append(("persona", p))


@pytest.fixture
def rig():
    bus = ui_state.StateBus()
    t = [0.0]
    host = FakeHost()
    link = LiveLink(host, bus, clock=lambda: t[0])
    return bus, host, link, t


def test_map_state_accepts_only_contract_states():
    assert map_state("LISTENING") == "listening"
    assert map_state("Thinking") == "thinking"
    for bad in ("muted", "disconnected", "", None, "bogus"):
        assert map_state(bad) is None


def test_state_is_forwarded_and_unknown_is_dropped(rig):
    bus, host, _, _ = rig
    bus.set(ui_state.ASSISTANT, "speaking")
    bus.set(ui_state.ASSISTANT, "muted")          # no contract name -> not forwarded, nothing invented
    assert host.calls == [("state", "speaking")]


def test_audio_is_throttled_but_silence_always_goes_through(rig):
    bus, host, _, t = rig
    bus.set(ui_state.AUDIO_LEVEL, 0.2)
    t[0] += AUDIO_MIN_INTERVAL / 4
    bus.set(ui_state.AUDIO_LEVEL, 0.4)             # too soon -> dropped
    t[0] += AUDIO_MIN_INTERVAL / 4
    bus.set(ui_state.AUDIO_LEVEL, 0.0)             # silence is never dropped
    t[0] += AUDIO_MIN_INTERVAL
    bus.set(ui_state.AUDIO_LEVEL, 0.5)
    assert [c for c in host.calls if c[0] == "level"] == [("level", 0.2), ("level", 0.0), ("level", 0.5)]


def test_persona_only_known_values(rig):
    bus, host, _, _ = rig
    bus.set(ui_state.PERSONA, "bihansa")
    bus.set(ui_state.PERSONA, "evil")
    assert host.calls == [("persona", "bihansa")]


def test_snapshot_is_resent_when_page_reloads(rig):
    bus, host, _, _ = rig
    bus.set(ui_state.ASSISTANT, "thinking")
    host.calls.clear()
    host.ready.emit()
    assert host.calls == [("state", "thinking")]


def test_close_unsubscribes(rig):
    bus, host, link, _ = rig
    link.close()
    bus.set(ui_state.ASSISTANT, "idle")
    assert host.calls == []
