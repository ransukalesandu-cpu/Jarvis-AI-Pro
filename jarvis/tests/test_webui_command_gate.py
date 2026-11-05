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


# ── controls ────────────────────────────────────────────────────────────────
from jarvis.webui.command_gate import ACTIONS, ControlGate  # noqa: E402


def ctl(mgr=None, guest=False, muted=False):
    calls, t, state = [], [0.0], {"muted": muted}
    gate, _, _ = rig(mgr, guest)
    acts = {a: (lambda a=a: calls.append(a)) for a in ACTIONS}
    return ControlGate(gate, acts, lambda: state["muted"], clock=lambda: t[0]), calls, t, state


def test_stop_actions_are_always_allowed_even_when_locked():
    c, calls, t, _ = ctl(Mgr(lock=True), guest=True)
    assert c.do("interrupt") == "done"
    t[0] += 1
    assert c.do("mute") == "done"
    t[0] += 1
    assert c.do("fullscreen") == "done"
    assert calls == ["interrupt", "mute", "fullscreen"]


@pytest.mark.parametrize("mgr,guest,reason", [(Mgr(lock=True), False, "locked"), (Mgr(pin=True), False, "auth_required"),
                                              (Mgr(silent=True), False, "silent"), (Mgr(), True, "guest")])
def test_turning_the_mic_back_on_needs_an_unlocked_session(mgr, guest, reason):
    c, calls, _, _ = ctl(mgr, guest, muted=True)
    assert c.do("unmute") == reason and calls == []


def test_unmute_works_when_available_and_noop_when_already_in_state():
    c, calls, t, st = ctl(muted=True)
    assert c.do("unmute") == "done" and calls == ["unmute"]
    st["muted"] = False
    t[0] += 1
    assert c.do("unmute") == "noop" and c.do("mute") == "done"
    st["muted"] = True
    t[0] += 1
    assert c.do("mute") == "noop"


def test_controls_rate_limit_unknown_and_missing_actions():
    c, calls, t, _ = ctl()
    assert c.do("interrupt") == "done" and c.do("interrupt") == "rate_limited"
    assert c.do("format_disk") == "unavailable" and c.do(None) == "unavailable"
    gate, _, _ = rig()
    assert ControlGate(gate, {}, lambda: False).do("interrupt") == "unavailable"
    assert calls == ["interrupt"]


def test_control_contract_and_bridge():
    pytest.importorskip("PyQt6.QtCore")
    from jarvis.webui.bridge import WebUIBridge
    ok = lambda m: contract.parse_request(json.dumps(m)) is not None   # noqa: E731
    assert ok({"kind": "control.do", "action": "mute"})
    assert not ok({"kind": "control.do", "action": "shutdown"})
    assert not ok({"kind": "control.do", "action": "mute", "x": 1})
    c, calls, _, _ = ctl()
    b = WebUIBridge(controls=c)
    got = []
    b.event.connect(lambda s: got.append(json.loads(s)))
    b.request(json.dumps({"kind": "control.do", "action": "interrupt"}))
    assert calls == ["interrupt"] and got == [{"type": "control.result", "reason": "done"}]
    got.clear()
    WebUIBridge().request(json.dumps({"kind": "control.do", "action": "interrupt"}))   # no controls -> nothing happens


@pytest.mark.parametrize("action", ["mode_bihansa", "perf_lite", "perf_auto"])
@pytest.mark.parametrize("mgr,guest,reason", [(Mgr(lock=True), False, "locked"), (Mgr(pin=True), False, "auth_required"),
                                              (Mgr(silent=True), False, "silent"), (Mgr(), True, "guest")])
def test_persona_and_performance_changes_need_an_unlocked_session(action, mgr, guest, reason):
    c, calls, _, _ = ctl(mgr, guest)
    assert c.do(action) == reason and calls == []


def test_persona_and_performance_apply_and_report_noop():
    gate, _, _ = rig()
    calls, t, cur = [], [0.0], {"persona": "jarvis"}
    acts = {a: (lambda a=a: calls.append(a)) for a in ACTIONS}
    already = {"mode_jarvis": lambda: cur["persona"] == "jarvis", "mode_bihansa": lambda: cur["persona"] == "bihansa"}
    c = ControlGate(gate, acts, lambda: False, clock=lambda: t[0], already=already)
    assert c.do("mode_jarvis") == "noop"
    t[0] += 1
    assert c.do("mode_bihansa") == "done" and calls == ["mode_bihansa"]
    t[0] += 1
    assert c.do("perf_full") == "done"          # no "already" check registered: it simply applies
