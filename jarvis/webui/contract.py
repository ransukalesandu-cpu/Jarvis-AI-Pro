"""Typed message contract between Python and the page (mirror of frontend/src/bridge/contract.ts).

Closed set of message types, bounded values, no bulk payloads. Anything else is rejected, never coerced.
No Qt in this module.
"""
from __future__ import annotations

import json
import math
from typing import Any

MAX_EVENT_CHARS = 4096
MAX_REQUEST_CHARS = 512

ASSISTANT_STATES = frozenset({"idle", "sleeping", "listening", "thinking", "searching", "executing", "speaking", "error"})
PERSONAS = frozenset({"jarvis", "bihansa"})


def _num(v: Any, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


def _str(v: Any, mx: int = 80) -> bool:
    return isinstance(v, str) and 0 < len(v) <= mx


def _battery_ok(b: Any) -> bool:
    return b is None or (isinstance(b, dict) and set(b) == {"percent", "charging"}
                         and _num(b["percent"], 0, 100) and isinstance(b["charging"], bool))


def _net_ok(n: Any) -> bool:
    return n is None or (isinstance(n, dict) and set(n) == {"upKBps", "downKBps"}
                         and _num(n["upKBps"], 0, 1e7) and _num(n["downKBps"], 0, 1e7))


_EVENTS = {
    "assistant.state_changed": ({"state"}, lambda m: m["state"] in ASSISTANT_STATES),
    "assistant.audio_level": ({"level", "source"}, lambda m: _num(m["level"], 0, 1) and m["source"] in ("input", "output")),
    "system.metrics_updated": ({"cpu", "ram", "disk", "battery", "net"},
                               lambda m: _num(m["cpu"], 0, 100) and _num(m["ram"], 0, 100)
                               and (m["disk"] is None or _num(m["disk"], 0, 100))
                               and _battery_ok(m["battery"]) and _net_ok(m["net"])),
    "provider.changed": ({"provider", "model", "connected", "fallback"},
                         lambda m: _str(m["provider"]) and _str(m["model"], 120)
                         and isinstance(m["connected"], bool) and isinstance(m["fallback"], bool)),
    "ui.persona": ({"persona"}, lambda m: m["persona"] in PERSONAS),
    "host.hello": ({"version"}, lambda m: _num(m["version"], 0, 1000)),
}


def encode_event(kind: str, **fields: Any) -> str | None:
    """Validate and serialise a Python -> page event. Returns None if it would be rejected."""
    spec = _EVENTS.get(kind)
    if spec is None:
        return None
    keys, check = spec
    if set(fields) != keys:
        return None
    msg = {"type": kind, **fields}
    try:
        if not check(msg):
            return None
        text = json.dumps(msg, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, KeyError):
        return None
    return text if len(text) <= MAX_EVENT_CHARS else None


_REQUESTS = {
    "ready": (set(), lambda m: True),
    "ping": ({"n"}, lambda m: isinstance(m["n"], int) and not isinstance(m["n"], bool) and 0 <= m["n"] < 2 ** 31),
}


def parse_request(raw: Any) -> dict | None:
    """Validate a page -> Python request. Returns {'kind': ..., ...} or None.

    This only checks the shape. Anything that does something goes through the existing authorisation
    checks in Python; the page is never trusted to decide.
    """
    if not isinstance(raw, str) or not raw or len(raw) > MAX_REQUEST_CHARS:
        return None
    try:
        m = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(m, dict) or m.get("kind") not in _REQUESTS:
        return None
    keys, check = _REQUESTS[m["kind"]]
    if set(m) - {"kind"} != keys:
        return None
    try:
        return m if check(m) else None
    except (TypeError, KeyError):
        return None
