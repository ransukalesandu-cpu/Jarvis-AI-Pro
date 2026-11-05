"""Host <-> page protocol (Python side): strict validation, no raw audio, bounded sizes."""
import json
import math

import pytest

from jarvis.hologram import protocol


def test_valid_messages_encode():
    assert json.loads(protocol.encode("state", v="speaking")) == {"t": "state", "v": "speaking"}
    assert protocol.encode("input", v=0.5) is not None
    assert protocol.encode("output", v=0.4, open=0.7, width=-0.2) is not None
    assert protocol.encode("profile", v="bihansa") is not None
    assert protocol.encode("budget", frame_ms=33, particles=0.6, glow=0.5) is not None
    assert protocol.encode("output_end") is not None
    assert protocol.encode("ping", n=7) is not None


@pytest.mark.parametrize("kind,fields", [
    ("state", {"v": "dance"}),
    ("state", {"v": 3}),
    ("input", {"v": 1.5}),
    ("input", {"v": -0.1}),
    ("input", {"v": float("nan")}),
    ("input", {"v": float("inf")}),
    ("input", {"v": True}),
    ("output", {"v": 0.5, "open": 2}),
    ("output", {"v": 0.5, "width": -3}),
    ("profile", {"v": "evil"}),
    ("quality", {"v": "ultra"}),
    ("budget", {"frame_ms": 1, "particles": 0.6, "glow": 0.5}),
    ("budget", {"frame_ms": 33, "particles": 5, "glow": 0.5}),
    ("motion", {"reduced": "yes"}),
    ("ping", {"n": -1}),
    ("ping", {"n": 2 ** 40}),
    ("exec", {"code": "x"}),
    ("navigate", {"url": "https://example.com"}),
])
def test_invalid_messages_are_rejected_not_coerced(kind, fields):
    assert protocol.encode(kind, **fields) is None


def test_normalize_state_maps_hud_names_and_unknowns():
    assert protocol.normalize_state("PRIVACY_LOCK") == "locked"
    assert protocol.normalize_state("LOCKED") == "locked"
    assert protocol.normalize_state("STANDBY") == "idle"
    assert protocol.normalize_state("SPEAKING") == "speaking"
    assert protocol.normalize_state("INITIALISING") == "idle"
    assert protocol.normalize_state("") == "idle"
    assert protocol.normalize_state(None) == "idle"
    assert protocol.normalize_state("<script>") == "idle"


def test_every_page_state_is_reachable_from_the_hud():
    reachable = set(protocol.HUD_STATE_ALIASES.values())
    assert {"idle", "listening", "thinking", "processing", "speaking", "responding",
            "error", "disconnected", "recovery"} <= reachable


def test_messages_cannot_carry_audio_or_other_extra_fields():
    """Only scalar levels cross the bridge; unknown keys (e.g. samples) reject the whole message."""
    for kind in ("input", "output"):
        assert protocol.encode(kind, v=0.5) is not None
        assert protocol.encode(kind, v=0.5, samples=[0.1, 0.2]) is None
        assert protocol.encode(kind, v=0.5, blob="x" * 5000) is None
    assert protocol.encode("state", v="idle", text="hello") is None


def test_report_parsing_is_strict():
    ok = protocol.parse_report('HOLO:{"t":"ready","renderer":"ANGLE","tier":"low","webgl2":true}')
    assert ok == {"t": "ready", "renderer": "ANGLE", "tier": "low", "webgl2": True}
    assert protocol.parse_report("hello") is None
    assert protocol.parse_report("HOLO:not json") is None
    assert protocol.parse_report('HOLO:{"t":"evil"}') is None
    assert protocol.parse_report('HOLO:[1,2]') is None
    assert protocol.parse_report("HOLO:" + "x" * 5000) is None
    assert protocol.parse_report(None) is None
    clean = protocol.parse_report('HOLO:{"t":"error","code":"' + "a" * 500 + '","nested":{"a":1}}')
    assert len(clean["code"]) == 80 and "nested" not in clean
    assert not any(isinstance(v, float) and math.isnan(v) for v in clean.values())
