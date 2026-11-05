"""The Python side of the typed bridge contract: shape validation only, no Qt."""
from __future__ import annotations

import json
import math

from jarvis.webui import contract as c


def test_encode_valid_events():
    assert json.loads(c.encode_event("assistant.state_changed", state="speaking")) == {"type": "assistant.state_changed", "state": "speaking"}
    ev = c.encode_event("system.metrics_updated", cpu=10.0, ram=20.0, disk=None, battery={"percent": 50.0, "charging": True}, net=None)
    assert ev and json.loads(ev)["battery"]["charging"] is True


def test_encode_rejects_bad_events():
    assert c.encode_event("nope", x=1) is None
    assert c.encode_event("assistant.state_changed", state="dancing") is None
    assert c.encode_event("assistant.state_changed", state="idle", extra=1) is None      # unknown key
    assert c.encode_event("assistant.state_changed") is None                              # missing key
    assert c.encode_event("assistant.audio_level", level=1.5, source="output") is None
    assert c.encode_event("assistant.audio_level", level=math.nan, source="output") is None
    assert c.encode_event("assistant.audio_level", level=True, source="output") is None  # bool is not a number
    assert c.encode_event("system.metrics_updated", cpu=101, ram=1, disk=None, battery=None, net=None) is None
    assert c.encode_event("system.metrics_updated", cpu=1, ram=1, disk=None, battery={"percent": 5}, net=None) is None
    assert c.encode_event("provider.changed", provider="x" * 200, model="m", connected=True, fallback=False) is None


def test_no_bulk_payload_can_cross():
    # An event may never carry arbitrary extra data (for example raw audio) beside its fields.
    assert c.encode_event("assistant.audio_level", level=0.2, source="input", pcm=[0] * 100) is None


def test_parse_request():
    assert c.parse_request('{"kind":"ready"}') == {"kind": "ready"}
    assert c.parse_request('{"kind":"ping","n":3}')["n"] == 3
    assert c.parse_request('{"kind":"ping","n":-1}') is None
    assert c.parse_request('{"kind":"ping","n":true}') is None
    assert c.parse_request('{"kind":"open_app","path":"C:/x.exe"}') is None             # not an allowlisted request
    assert c.parse_request('{"kind":"ready","extra":1}') is None
    assert c.parse_request("x" * 600) is None
    assert c.parse_request("not json") is None
    assert c.parse_request(None) is None
    assert c.parse_request("[1]") is None
