"""Shared rules every tool call goes through, whatever registry it came from.

* ``device`` — every tool takes an optional ``device`` argument. Only
  ``"laptop"`` exists in Phase 1; anything else is refused with a sentence
  JARVIS can speak. Phase 2 will route other values over the network.
* ``risk`` — ``read``, ``write`` or ``destructive``. Used only for the action
  log; it never blocks anything.
* ``timeout`` — seconds the voice loop waits for a result. When it expires the
  owner hears that the tool is still running instead of silence.
* ``long_running`` — the call returns a job id at once and finishes in the
  background (core/jobs.py); JARVIS announces the result when it is done.

A tool declares these next to its other fields::

    TOOL = {"name": ..., "description": ..., "parameters": ..., "handler": ...,
            "risk": "write", "timeout": 60, "long_running": False}
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

DEFAULT_DEVICE = "laptop"
SUPPORTED_DEVICES = frozenset({DEFAULT_DEVICE})
RISKS = ("read", "write", "destructive")
DEFAULT_TIMEOUT = 120.0
MAX_TIMEOUT = 3600.0

DEVICE_PARAMETER = {
    "type": "STRING",
    "description": "Which device runs this: laptop (default), tablet, phone...",
}


@dataclass(frozen=True)
class ToolMeta:
    risk: str = ""                 # "" = not declared; inferred for the log
    timeout: float = DEFAULT_TIMEOUT
    long_running: bool = False


def normalize_risk(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in RISKS else ""


def normalize_timeout(value) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return min(max(seconds, 1.0), MAX_TIMEOUT)


def meta_from_declaration(decl: dict) -> ToolMeta:
    return ToolMeta(
        risk=normalize_risk(decl.get("risk")),
        timeout=normalize_timeout(decl.get("timeout", DEFAULT_TIMEOUT)),
        long_running=bool(decl.get("long_running", False)),
    )


def json_object_arg(value) -> dict:
    """A free-form object argument. Declarations use a JSON *string* for these
    because Gemini rejects nested OBJECT schemas that have no properties."""
    if isinstance(value, dict):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    import json
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    return parsed


def with_device_parameter(declaration: dict) -> dict:
    """A copy of a function declaration with the optional ``device`` argument."""
    decl = copy.deepcopy(declaration)
    params = decl.get("parameters")
    if not isinstance(params, dict):
        params = {"type": "OBJECT", "properties": {}}
        decl["parameters"] = params
    props = params.setdefault("properties", {})
    if isinstance(props, dict) and "device" not in props:
        props["device"] = dict(DEVICE_PARAMETER)
    return decl


_DEVICE_RESOLVER = None


def set_device_resolver(resolver) -> None:
    """Hub mode: ``resolver(device) -> error sentence or ''`` decides which
    device names exist (devices.json). Without one only "laptop" is valid."""
    global _DEVICE_RESOLVER
    _DEVICE_RESOLVER = resolver


def take_device(args: dict) -> tuple[str, str]:
    """Remove ``device`` from ``args``. Returns (device, error_sentence_or_empty)."""
    raw = args.pop("device", None)
    device = str(raw or DEFAULT_DEVICE).strip().lower() or DEFAULT_DEVICE
    if _DEVICE_RESOLVER is not None:
        return device, _DEVICE_RESOLVER(device) or ""
    if device not in SUPPORTED_DEVICES:
        return device, (
            f"I can't run that on the {device} yet. Only the laptop is connected right now."
        )
    return device, ""


def infer_risk(name: str, args: dict | None = None) -> str:
    """Best-effort risk label for tools that did not declare one (logging only)."""
    try:
        from jarvis.core import security
        tier = security.tier_for(name, args or {})
    except Exception:
        return "write"
    return {"safe": "read", "sensitive": "write", "dangerous": "destructive"}.get(
        str(tier).lower(), "write")


def speakable_error(name: str, exc: BaseException) -> str:
    """A short sentence about a failure that JARVIS can say out loud."""
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    if len(detail) > 160:
        detail = detail[:157] + "..."
    return f"The {name.replace('_', ' ')} tool failed: {detail}"


def timeout_message(name: str, seconds: float) -> str:
    return (
        f"The {name.replace('_', ' ')} tool did not finish within {int(seconds)} seconds. "
        "It may still be running; ask me again in a moment or use a background job."
    )


def result_status(result: str) -> str:
    """'error' when a result is one of the failure sentences above, else 'ok'."""
    text = str(result or "")
    failed = (
        text.startswith("Unknown tool")
        or (text.startswith("Tool '") and "' failed" in text[:200])
        or (text.startswith("The ") and " tool failed:" in text[:200])
    )
    return "error" if failed else "ok"
