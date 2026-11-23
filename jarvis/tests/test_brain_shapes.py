"""Brain shapes: normalising requests, the form_shape tool, the bus -> page event, the contract."""
from __future__ import annotations

import json

import pytest

from jarvis.core import brain_shapes, security, ui_state
from jarvis.webui import contract


def test_normalise_maps_words_and_rejects_the_rest():
    assert brain_shapes.normalise("Heart") == ("heart", "")
    assert brain_shapes.normalise("DNA") == ("helix", "")
    assert brain_shapes.normalise("earth") == ("globe", "")
    assert brain_shapes.normalise("reset") == ("brain", "")
    assert brain_shapes.normalise("sphere", "ignored") == ("sphere", "")
    assert brain_shapes.normalise("text", "  lesandu  gamage ") == ("text", "LESANDU GAMAGE")
    assert brain_shapes.normalise("text", "") is None
    assert brain_shapes.normalise("text", "x" * 17) is None
    assert brain_shapes.normalise("text", "<script>") is None
    assert brain_shapes.normalise("cat") is None


def test_tool_sets_the_bus_and_repeats_retrigger():
    from jarvis.actions.form_shape import TOOL, form_shape
    assert TOOL["name"] == "form_shape" and security.tier_for("form_shape") == security.TIER_SAFE
    seen = []
    unsub = ui_state.bus().subscribe(ui_state.BRAIN_SHAPE, lambda k, v: seen.append(v))
    try:
        assert form_shape({"shape": "heart"}) == "Forming a heart."
        assert form_shape({"shape": "heart"}) == "Forming a heart."
        assert form_shape({"shape": "text", "text": "Jarvis"}) == "Forming 'JARVIS'."
        assert "can form" in form_shape({"shape": "dragon"})
        assert "16" in form_shape({"shape": "text", "text": "a" * 30})
    finally:
        unsub()
    assert [v[:2] for v in seen] == [("heart", ""), ("heart", ""), ("text", "JARVIS")]


def test_contract_event_is_closed():
    ok = contract.encode_event("hologram.shape", shape="heart", text="")
    assert ok is not None and json.loads(ok)["shape"] == "heart"
    assert contract.encode_event("hologram.shape", shape="text", text="JARVIS") is not None
    assert contract.encode_event("hologram.shape", shape="text", text="") is None
    assert contract.encode_event("hologram.shape", shape="heart", text="HI") is None
    assert contract.encode_event("hologram.shape", shape="dragon", text="") is None
    assert contract.encode_event("hologram.shape", shape="text", text="A" * 17) is None


def test_live_link_forwards_requests_but_does_not_replay_them():
    pytest.importorskip("PyQt6.QtCore")
    from jarvis.webui.live import LiveLink

    class Host:
        def __init__(self):
            self.shapes = []
            class Sig:
                def connect(self, _f): pass
            self.ready = Sig()
        def set_shape(self, s, t=""): self.shapes.append((s, t))
        def __getattr__(self, _n): return lambda *a, **k: None

    bus = ui_state.StateBus()
    host = Host()
    link = LiveLink(host, bus=bus)
    bus.set(ui_state.BRAIN_SHAPE, ("star", "", 1))
    link.push_snapshot()
    assert host.shapes == [("star", "")]
    link.close()
