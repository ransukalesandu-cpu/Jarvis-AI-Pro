"""The typed-command gate: the web page must never become a credential entry point."""
from __future__ import annotations

import json

import pytest

from jarvis.webui import contract
from jarvis.webui.command_gate import MAX_PER_MINUTE, MAX_TEXT, CommandGate


class Mgr:
    def __init__(self, lock=False, pin=False, silent=False):
        self.lock, self.pin, self.silent = lock, pin, silent

    def is_privacy_lock_active(self): return self.lock
    def needs_pin(self): return self.pin
    def is_silent(self): return self.silent


def rig(mgr=None, guest=False, sink=True):
    sent, t = [], [0.0]
    gate = CommandGate((lambda s: sent.append(s)) if sink else None, lambda: mgr or Mgr(), lambda: guest, clock=lambda: t[0])
    return gate, sent, t


def test_normal_command_is_forwarded_once_cleaned():
    gate, sent, _ = rig()
    assert gate.submit("  what time is it\x00\x07 ") == "sent"
    assert sent == ["what time is it"]


@pytest.mark.parametrize("mgr,guest,reason", [
    (Mgr(lock=True), False, "locked"), (Mgr(pin=True), False, "auth_required"),
    (Mgr(silent=True), False, "silent"), (Mgr(), True, "guest"),
])
def test_never_forwards_while_locked_pin_silent_or_guest(mgr, guest, reason):
    gate, sent, _ = rig(mgr, guest)
    assert gate.availability() == reason
    assert gate.submit("1234") == reason          # a PIN typed into the page goes nowhere
    assert sent == []


@pytest.mark.parametrize("txt", ["/owner 1234", "  /OWNER 9", "/pin 1", "/login x", "/password hunter2"])
def test_credential_shaped_text_is_refused_even_when_available(txt):
    gate, sent, _ = rig()
    assert gate.submit(txt) == "credential" and sent == []


def test_empty_and_too_long():
    gate, sent, _ = rig()
    assert gate.submit("  \x01 ") == "empty"
    assert gate.submit("a" * (MAX_TEXT + 1)) == "too_long"
    assert sent == []


def test_rate_limits():
    gate, sent, t = rig()
    assert gate.submit("a") == "sent"
    assert gate.submit("b") == "rate_limited"
    for _ in range(MAX_PER_MINUTE - 1):
        t[0] += 0.6
        assert gate.submit("x") == "sent"
    t[0] += 0.6
    assert gate.submit("y") == "rate_limited"       # per-minute cap
    t[0] += 61
    assert gate.submit("z") == "sent"


def test_unprovable_safety_means_unavailable():
    class Broken:
        def is_privacy_lock_active(self): raise RuntimeError("boom")
    gate = CommandGate(lambda s: None, lambda: Broken(), lambda: False)
    assert gate.availability() == "unavailable" and gate.submit("hi") == "unavailable"
    assert rig(sink=False)[0].submit("hi") == "unavailable"


def test_contract_shapes():
    ok = lambda m: contract.parse_request(json.dumps(m, ensure_ascii=False)) is not None   # noqa: E731
    assert ok({"kind": "command.submit", "text": "hello"})
    assert ok({"kind": "command.submit", "text": "සිංහල ප්‍රශ්නයක් " * 20})
    assert not ok({"kind": "command.submit", "text": 5})
    assert not ok({"kind": "command.submit", "text": "x", "extra": 1})
    assert not ok({"kind": "command.submit", "text": "x" * 5000})
    assert contract.encode_event("command.result", reason="sent")
    assert contract.encode_event("command.result", reason="whatever") is None
    assert contract.encode_event("command.availability", state="auth_required")
    assert contract.encode_event("command.availability", state="nope") is None


def test_bridge_round_trip_and_availability_only_on_change():
    pytest.importorskip("PyQt6.QtCore")
    from jarvis.webui.bridge import WebUIBridge
    mgr = Mgr()
    gate, sent, _ = rig(mgr)
    b = WebUIBridge(gate=gate)
    got = []
    b.event.connect(lambda s: got.append(json.loads(s)))
    b.refresh_availability(); b.refresh_availability(); b.refresh_availability()
    assert got == [{"type": "command.availability", "state": "ok"}]        # published once, not every tick
    b.request(json.dumps({"kind": "command.submit", "text": "hello"}))
    assert sent == ["hello"] and {"type": "command.result", "reason": "sent"} in got
    mgr.pin = True
    b.refresh_availability()
    assert got[-1] == {"type": "command.availability", "state": "auth_required"}
    b.request(json.dumps({"kind": "command.submit", "text": "4321"}))
    assert sent == ["hello"] and {"type": "command.result", "reason": "auth_required"} in got


def test_bridge_without_a_gate_is_unavailable():
    pytest.importorskip("PyQt6.QtCore")
    from jarvis.webui.bridge import WebUIBridge
    b = WebUIBridge()
    got = []
    b.event.connect(lambda s: got.append(json.loads(s)))
    b.request(json.dumps({"kind": "command.submit", "text": "x"}))
    assert {"type": "command.result", "reason": "unavailable"} in got
