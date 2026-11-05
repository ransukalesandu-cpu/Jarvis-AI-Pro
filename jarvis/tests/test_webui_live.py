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
    def set_muted(self, m): self.calls.append(("muted", m))
    def set_provider(self, **kw): self.calls.append(("provider", kw["provider"]))


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
    assert ("state", "thinking") in host.calls


def test_close_unsubscribes(rig):
    bus, host, link, _ = rig
    link.close()
    bus.set(ui_state.ASSISTANT, "idle")
    assert host.calls == []


def test_mute_is_forwarded(rig):
    bus, host, _, _ = rig
    bus.set(ui_state.MUTED, True)
    bus.set(ui_state.MUTED, False)
    assert host.calls == [("muted", True), ("muted", False)]


def test_provider_comes_from_real_settings_and_never_leaks_a_key(rig, monkeypatch):
    from jarvis.core import provider_settings as ps
    from jarvis.webui import provider_info

    monkeypatch.setattr(ps, "get_provider_settings", lambda: {
        "provider": "anthropic", "openai_model_reasoning": "x", "anthropic_model_reasoning": "claude-sonnet-5-5",
        "has_openai_key": False, "has_anthropic_key": True})
    info = provider_info.snapshot()
    assert info == {"provider": "Anthropic Claude", "model": "claude-sonnet-5-5", "connected": True, "fallback": False}
    bus, host, _, _ = rig
    bus.set(ui_state.PROVIDER, 1.0)
    assert ("provider", "Anthropic Claude") in host.calls


def test_provider_unknown_is_not_guessed(monkeypatch):
    from jarvis.core import provider_settings as ps
    from jarvis.webui import provider_info

    def boom(): raise OSError("no config")
    monkeypatch.setattr(ps, "get_provider_settings", boom)
    assert provider_info.snapshot() is None
