"""Typed message contract between Python and the page (mirror of frontend/src/bridge/contract.ts).

Closed set of message types, bounded values, no bulk payloads. Anything else is rejected, never coerced.
No Qt in this module.
"""
from __future__ import annotations

import json
import math
from typing import Any

from jarvis.core import brain_shapes
from jarvis.core.task_flow import FLOW_SOURCES, FLOW_STATES, MAX_STEPS, STEP_STATES, VIEWS as FLOW_VIEWS

from .command_gate import ACTIONS, AVAILABILITY, MAX_TEXT, REASONS
from .features_feed import FEATURES, MAX_DETAIL, MAX_ITEMS as FEATURE_MAX_ITEMS, MAX_SUMMARY, MAX_TITLE
from .memory_status import CLOUD_STATES
from .redact import KINDS as LOG_KINDS, MAX_LINE
from .workspace_store import clean_name, validate_layout, validate_prefs

MAX_EVENT_CHARS = 16384
MAX_REQUEST_CHARS = 16384          # upper bound; each request kind has a tighter cap below

ASSISTANT_STATES = frozenset({"idle", "sleeping", "listening", "thinking", "searching", "executing", "speaking", "warning", "error"})
PERSONAS = frozenset({"jarvis", "bihansa"})
JOB_STATES = frozenset({"running", "done", "failed", "cancelled"})
PERF_TIERS = frozenset({"full", "balanced", "lite"})


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


_FLOW_KEYS = {"id", "title", "source", "state", "startedAt", "finishedAt", "steps"}
_STEP_KEYS = {"id", "tool", "label", "status", "detail", "startedAt", "finishedAt"}


def _time_ok(v: Any, nullable: bool = True) -> bool:
    return (nullable and v is None) or _num(v, 0, 4e12)


def _step_ok(s: Any) -> bool:
    return (isinstance(s, dict) and set(s) == _STEP_KEYS and _str(s["id"], 8) and _str(s["tool"], 48)
            and _str(s["label"], 80) and s["status"] in STEP_STATES
            and isinstance(s["detail"], str) and len(s["detail"]) <= 100
            and _time_ok(s["startedAt"]) and _time_ok(s["finishedAt"]))


def flow_ok(f: Any) -> bool:
    """One Task Flow snapshot (core/task_flow.py): bounded text, closed state sets, no arguments."""
    return (isinstance(f, dict) and set(f) == _FLOW_KEYS and _str(f["id"], 40) and _str(f["title"], 120)
            and f["source"] in FLOW_SOURCES and f["state"] in FLOW_STATES
            and _time_ok(f["startedAt"], nullable=False) and _time_ok(f["finishedAt"])
            and isinstance(f["steps"], list) and len(f["steps"]) <= MAX_STEPS
            and all(_step_ok(s) for s in f["steps"]))


_EVENTS = {
    "assistant.state_changed": ({"state"}, lambda m: m["state"] in ASSISTANT_STATES),
    "assistant.audio_level": ({"level", "source"}, lambda m: _num(m["level"], 0, 1) and m["source"] in ("input", "output")),
    "system.metrics_updated": ({"cpu", "ram", "disk", "battery", "net"},
                               lambda m: _num(m["cpu"], 0, 100) and _num(m["ram"], 0, 100)
                               and (m["disk"] is None or _num(m["disk"], 0, 100))
                               and _battery_ok(m["battery"]) and _net_ok(m["net"])),
    "memory.status": ({"cloud", "personal", "encrypted"},
                      lambda m: m["cloud"] in CLOUD_STATES and isinstance(m["personal"], bool) and isinstance(m["encrypted"], bool)),
    "provider.changed": ({"provider", "model", "connected", "fallback"},
                         lambda m: _str(m["provider"]) and _str(m["model"], 120)
                         and isinstance(m["connected"], bool) and isinstance(m["fallback"], bool)),
    "assistant.muted": ({"muted"}, lambda m: isinstance(m["muted"], bool)),
    "ui.persona": ({"persona"}, lambda m: m["persona"] in PERSONAS),
    "ui.perf": ({"tier"}, lambda m: m["tier"] in PERF_TIERS),
    "workspace.list": ({"names"}, lambda m: isinstance(m["names"], list) and len(m["names"]) <= 24
                       and all(isinstance(n, str) and 0 < len(n) <= 32 for n in m["names"])),
    "workspace.loaded": ({"name", "layout"}, lambda m: isinstance(m["name"], str) and 0 < len(m["name"]) <= 32
                         and (m["layout"] is None or validate_layout(m["layout"]) is not None)),
    "command.availability": ({"state"}, lambda m: m["state"] in AVAILABILITY),
    "log.line": ({"tag", "text"}, lambda m: m["tag"] in LOG_KINDS and isinstance(m["text"], str) and 0 < len(m["text"]) <= MAX_LINE),
    "control.result": ({"reason"}, lambda m: m["reason"] in REASONS),
    "command.result": ({"reason"}, lambda m: m["reason"] in REASONS),
    "news.items": ({"heading", "items"}, lambda m: isinstance(m["heading"], str) and len(m["heading"]) <= 80
                   and isinstance(m["items"], list) and len(m["items"]) <= 20
                   and all(isinstance(i, dict) and set(i) == {"title", "source", "link"} and isinstance(i["title"], str) and 0 < len(i["title"]) <= 200
                           and isinstance(i["source"], str) and len(i["source"]) <= 80 and isinstance(i["link"], bool) for i in m["items"])),
    "jobs.updated": ({"jobs"}, lambda m: isinstance(m["jobs"], list) and len(m["jobs"]) <= 20
                     and all(isinstance(j, dict) and set(j) == {"id", "name", "status", "startedAt", "finishedAt"}
                             and isinstance(j["id"], str) and 0 < len(j["id"]) <= 24
                             and isinstance(j["name"], str) and 0 < len(j["name"]) <= 80
                             and j["status"] in JOB_STATES and _num(j["startedAt"], 0, 4e12)
                             and (j["finishedAt"] is None or _num(j["finishedAt"], 0, 4e12)) for j in m["jobs"])),
    "task.flow": ({"flow"}, lambda m: flow_ok(m["flow"])),
    "ui.task_flow": ({"view"}, lambda m: m["view"] in FLOW_VIEWS),
    "ui.prefs": ({"prefs"}, lambda m: m["prefs"] is None or validate_prefs(m["prefs"]) is not None),
    "hologram.shape": ({"shape", "text"},
                       lambda m: m["shape"] in brain_shapes.SHAPES and brain_shapes.valid_text(m["text"])
                       and (m["text"] != "") == (m["shape"] == "text")),
    "hologram.perf_report": ({"cpu", "ramMb", "processes"},
                             lambda m: _num(m["cpu"], 0, 100) and _num(m["ramMb"], 0, 1e6)
                             and isinstance(m["processes"], int) and _num(m["processes"], 0, 64)),
    "host.hello": ({"version"}, lambda m: _num(m["version"], 0, 1000)),
    "feature.snapshot": ({"feature", "summary", "items"},
                         lambda m: m["feature"] in FEATURES and _str(m["summary"], MAX_SUMMARY)
                         and isinstance(m["items"], list) and len(m["items"]) <= FEATURE_MAX_ITEMS
                         and all(isinstance(i, dict) and set(i) == {"title", "detail"} and _str(i["title"], MAX_TITLE)
                                 and isinstance(i["detail"], str) and len(i["detail"]) <= MAX_DETAIL for i in m["items"])),
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


_NAME_OK = lambda m: clean_name(m["name"], allow_internal=True) is not None  # noqa: E731

_REQUESTS = {
    "ready": (set(), lambda m: True),
    "workspace.list": (set(), lambda m: True),
    "workspace.load": ({"name"}, _NAME_OK),
    "workspace.delete": ({"name"}, lambda m: clean_name(m["name"]) is not None),
    "workspace.save": ({"name", "layout"}, lambda m: _NAME_OK(m) and validate_layout(m["layout"]) is not None),
    "command.submit": ({"text"}, lambda m: isinstance(m["text"], str) and len(m["text"]) <= 4 * MAX_TEXT),
    "control.do": ({"action"}, lambda m: m["action"] in ACTIONS),
    "news.open": ({"index"}, lambda m: isinstance(m["index"], int) and not isinstance(m["index"], bool) and 0 <= m["index"] < 20),
    "job.cancel": ({"id"}, lambda m: isinstance(m["id"], str) and 0 < len(m["id"]) <= 24),
    "ping": ({"n"}, lambda m: isinstance(m["n"], int) and not isinstance(m["n"], bool) and 0 <= m["n"] < 2 ** 31),
    "hologram.capability": ({"webgl2"}, lambda m: isinstance(m["webgl2"], bool)),
    "hologram.perf": ({"fps", "frameMs", "drawCalls", "triangles", "heapMb", "dpr"},
                      lambda m: _num(m["fps"], 0, 1000) and _num(m["frameMs"], 0, 10000)
                      and isinstance(m["drawCalls"], int) and _num(m["drawCalls"], 0, 1e6)
                      and isinstance(m["triangles"], int) and _num(m["triangles"], 0, 1e9)
                      and (m["heapMb"] is None or _num(m["heapMb"], 0, 1e5)) and _num(m["dpr"], 0.25, 4)),
    "feature.refresh": ({"feature"}, lambda m: m["feature"] in FEATURES),
    "prefs.load": (set(), lambda m: True),
    "prefs.save": ({"prefs"}, lambda m: validate_prefs(m["prefs"]) is not None),
}


def parse_request(raw: Any) -> dict | None:
    """Validate a page -> Python request. Returns {'kind': ..., ...} or None.

    This only checks the shape. Anything that does something goes through the existing authorisation
    checks in Python; the page is never trusted to decide.
    """
    if not isinstance(raw, str) or not raw or len(raw) > MAX_REQUEST_CHARS:
        return None
    head = raw[:40]
    if len(raw) > 512 and '"kind":"workspace.save"' not in head and not (len(raw) <= 8 * MAX_TEXT and '"kind":"command.submit"' in head):   # only a layout or a typed command may be large
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
