"""Read-only log mirror: redaction, and nothing leaves while the assistant is locked / awaiting a PIN."""
from __future__ import annotations

import json

import pytest

from jarvis.core import log_tap
from jarvis.webui import contract, redact


def test_kinds_and_dropped_lines():
    assert redact.prepare("You: what is the weather") == ("you", "what is the weather")
    assert redact.prepare("JARVIS: It is sunny.") == ("ai", "It is sunny.")
    assert redact.prepare("SYS: Microphone muted.") == ("sys", "SYS: Microphone muted.")
    assert redact.prepare("ERR: could not save (OSError).")[0] == "err"
    assert redact.prepare("FILE: report.pdf")[0] == "file"
    for dropped in ("SEC: Owner credential verified.", "   ", "", "\x00\x01", "You: /owner 1234", "you: /PIN 9"):
        assert redact.prepare(dropped) is None


@pytest.mark.parametrize("secret", [
    "AIzaSyA1234567890abcdefghijklmnopqrstuv", "sk-proj-abcdef1234567890ABCDEF", "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghijk", "api_key=hunter2hunter2", "password: swordfish", "Bearer abcdef0123456789xyz",
    "x" * 60,
])
def test_secrets_are_redacted(secret):
    out = redact.prepare(f"SYS: using {secret} now")
    assert out and "[redacted]" in out[1]
    assert secret not in out[1]


def test_home_folders_and_length_and_whitespace():
    assert "alice" not in redact.prepare(r"SYS: opened C:\Users\alice\Documents\a.txt")[1]
    assert "alice" not in redact.prepare("SYS: opened /home/alice/notes.md")[1]
    long = redact.prepare("JARVIS: " + "word " * 300)[1]
    assert len(long) <= redact.MAX_LINE and long.endswith("…")
    assert redact.prepare("JARVIS: a\n\n   b\tc")[1] == "a b c"


def test_log_contract():
    assert contract.encode_event("log.line", tag="you", text="hello")
    assert contract.encode_event("log.line", tag="secret", text="x") is None
    assert contract.encode_event("log.line", tag="you", text="") is None
    assert contract.encode_event("log.line", tag="you", text="x" * 401) is None
    assert contract.encode_event("log.line", tag="you", text="x", extra=1) is None
    assert not contract.parse_request(json.dumps({"kind": "log.line", "text": "x"}))   # the page cannot write the log


@pytest.fixture
def feed():
    pytest.importorskip("PyQt6.QtCore")
    from jarvis.webui.log_feed import BURST, LogFeed
    state, t, got = {"v": "ok"}, [0.0], []
    f = LogFeed(lambda: state["v"], clock=lambda: t[0])
    f.line.connect(lambda k, x: got.append((k, x)))
    yield f, state, t, got, BURST
    f.close()


def test_feed_mirrors_log_lines(feed):
    f, state, t, got, _ = feed
    log_tap.publish("You: hello")
    log_tap.publish("JARVIS: hi there")
    assert got == [("you", "hello"), ("ai", "hi there")]


@pytest.mark.parametrize("blocked", ["locked", "auth_required", "silent", "guest", "unavailable"])
def test_nothing_leaves_while_locked_pin_silent_guest(feed, blocked):
    f, state, t, got, _ = feed
    state["v"] = blocked
    log_tap.publish("You: 482913")            # the native box logs a typed PIN before it knows it is one
    log_tap.publish("JARVIS: anything")
    assert got == []


def test_a_pin_logged_then_verified_never_leaks(feed):
    f, state, t, got, _ = feed
    state["v"] = "auth_required"
    log_tap.publish("You: 482913")            # judged now, at log time
    state["v"] = "ok"                         # PIN accepted a moment later
    assert got == []


def test_unprovable_state_is_treated_as_blocked():
    pytest.importorskip("PyQt6.QtCore")
    from jarvis.webui.log_feed import LogFeed
    def boom(): raise RuntimeError("x")
    f, got = LogFeed(boom), []
    f.line.connect(lambda k, x: got.append(x))
    log_tap.publish("You: hello")
    assert got == []
    f.close()


def test_rate_limit_and_unsubscribe(feed):
    f, state, t, got, burst = feed
    for i in range(burst + 25):
        log_tap.publish(f"SYS: line {i}")
    assert len(got) == burst                      # flood is capped
    t[0] += 1.0
    log_tap.publish("SYS: later")
    assert got[-1] == ("sys", "SYS: later")
    f.close()
    n = len(got)
    log_tap.publish("SYS: after close")
    assert len(got) == n


def test_broken_observer_does_not_break_logging():
    def bad(_t): raise ValueError("nope")
    un = log_tap.subscribe(bad)
    try:
        log_tap.publish("SYS: still fine")
    finally:
        un()
