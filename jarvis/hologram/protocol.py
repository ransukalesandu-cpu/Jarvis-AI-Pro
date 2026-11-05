"""Host <-> page message protocol (Python side).

Mirrors ``bridge/protocol.js``. Messages are small JSON objects with a closed set of types and
bounded values. Nothing here ever carries raw audio, user text, tokens or file paths.
"""
from __future__ import annotations

import json
import math
from typing import Any

MAX_MESSAGE_CHARS = 2048
REPORT_PREFIX = "HOLO:"

STATES = frozenset({
    "idle", "sleeping", "listening", "thinking", "processing", "speaking", "responding",
    "error", "disconnected", "recovery", "locked",
})
# Names used by the existing HUD state machine -> page state.
HUD_STATE_ALIASES = {
    "STANDBY": "idle", "IDLE": "idle", "SLEEPING": "sleeping", "LISTENING": "listening",
    "THINKING": "thinking", "PROCESSING": "processing", "SPEAKING": "speaking",
    "RESPONDING": "responding", "ERROR": "error", "DISCONNECTED": "disconnected",
    "RECOVERY": "recovery", "PRIVACY_LOCK": "locked", "LOCKED": "locked",
}
PROFILES = frozenset({"jarvis", "bihansa"})
QUALITIES = frozenset({"auto", "high", "balanced", "low"})
REPORTS = frozenset({"ready", "fps", "quality", "error", "contextlost", "contextrestored", "pong"})


def _num(v: Any, lo: float, hi: float) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and lo <= v <= hi)


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 2 ** 31


_CHECKS = {
    "state": lambda m: m.get("v") in STATES,
    "input": lambda m: _num(m.get("v"), 0, 1),
    "output": lambda m: _num(m.get("v"), 0, 1)
    and ("open" not in m or _num(m["open"], 0, 1))
    and ("width" not in m or _num(m["width"], -1, 1)),
    "output_end": lambda m: True,
    "profile": lambda m: m.get("v") in PROFILES,
    "quality": lambda m: m.get("v") in QUALITIES,
    "budget": lambda m: _num(m.get("frame_ms"), 8, 100) and _num(m.get("particles"), 0.2, 1)
    and _num(m.get("glow"), 0, 1.5),
    "motion": lambda m: isinstance(m.get("reduced"), bool),
    "glow": lambda m: _num(m.get("v"), 0, 1.5),
    "visible": lambda m: isinstance(m.get("v"), bool),
    "effects": lambda m: isinstance(m.get("v"), bool),
    "voice_reactive": lambda m: isinstance(m.get("v"), bool),
    "ping": lambda m: _int(m.get("n")),
}


# Exact key set per message type: anything else is rejected, so a bulk payload (for example raw
# audio samples) can never be smuggled across the bridge inside an otherwise valid message.
_KEYS = {
    "state": {"v"}, "input": {"v"}, "output": {"v", "open", "width"}, "output_end": set(),
    "profile": {"v"}, "quality": {"v"}, "budget": {"frame_ms", "particles", "glow"},
    "motion": {"reduced"}, "glow": {"v"}, "visible": {"v"}, "effects": {"v"},
    "voice_reactive": {"v"}, "ping": {"n"},
}


def normalize_state(name: str) -> str:
    """Map any HUD state name onto a page state; unknown names become ``idle``."""
    key = str(name or "").strip()
    return HUD_STATE_ALIASES.get(key.upper(), key.lower() if key.lower() in STATES else "idle")


def encode(kind: str, **fields: Any) -> str | None:
    """Validate and serialise a host message. Returns None when it would be rejected."""
    msg = {"t": kind, **fields}
    check = _CHECKS.get(kind)
    if check is None or not set(fields) <= _KEYS[kind] or not check(msg):
        return None
    text = json.dumps(msg, separators=(",", ":"), allow_nan=False)
    return text if len(text) <= MAX_MESSAGE_CHARS else None


def parse_report(console_line: str) -> dict | None:
    """Parse a ``HOLO:{json}`` console line from the page. Anything else is ignored."""
    if not isinstance(console_line, str) or not console_line.startswith(REPORT_PREFIX):
        return None
    body = console_line[len(REPORT_PREFIX):]
    if not body or len(body) > MAX_MESSAGE_CHARS:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("t") not in REPORTS:
        return None
    clean: dict[str, Any] = {"t": data["t"]}
    for k, v in data.items():
        if k == "t" or not isinstance(k, str) or len(k) > 32:
            continue
        if isinstance(v, bool) or (isinstance(v, (int, float)) and math.isfinite(v)):
            clean[k] = v
        elif isinstance(v, str):
            clean[k] = v[:80]
    return clean
