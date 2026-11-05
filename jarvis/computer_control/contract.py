"""Tool contract: one :class:`ToolSpec` per computer-control function.

A spec carries everything the master prompt asks of a tool — id, description,
input schema, output schema, permission level, timeout, cancellation, logging
and error handling — and converts itself into the declaration format the
existing action registry (core/action_loader.py) already discovers. There is no
second tool system: ``jarvis/actions/computer_control_engine.py`` exposes
``TOOLS = [spec.to_declaration() for spec in specs]`` and the registry, the
Tool Catalog (core/tool_catalog.py), the planner and Gemini Live all see them
like any other action.

Calls made through a declaration go through :class:`runner.ActionRunner`, so
logging (action log + ``cc.*`` audit), policy, approval, emergency stop and
timeout are applied whatever the caller.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from jarvis.computer_control import flags
from jarvis.computer_control.policy import BASE_LEVELS, Level
from jarvis.computer_control.runner import ActionContext, ActionResult, Verifier, get_runner

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_GEMINI_TYPES = {"STRING", "NUMBER", "INTEGER", "BOOLEAN", "ARRAY", "OBJECT"}

#: The result shape every computer-control tool returns (as JSON text).
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "status": {"type": "string", "enum": ["ok", "failed", "denied", "cancelled", "timeout",
                                               "dry_run", "disabled", "unverified", "busy", "error"]},
        "message": {"type": "string"},
        "level": {"type": "string", "enum": ["low", "medium", "high"]},
        "verified": {"type": ["boolean", "null"]},
        "evidence": {"type": "string"},
        "duration_ms": {"type": "integer"},
        "data": {"type": "object"},
    },
    "required": ["action", "status", "message", "level"],
}


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    id: str                                    # registry name, e.g. "cc_window_list"
    action: str                                # policy action id, e.g. "window.list"
    description: str
    handler: Callable[[ActionContext], Any]
    input_schema: dict = field(default_factory=lambda: {"type": "OBJECT", "properties": {}})
    output_schema: dict = field(default_factory=lambda: dict(RESULT_SCHEMA))
    timeout: float = 30.0
    cancellable: bool = True
    long_running: bool = False
    verify: Optional[Verifier] = None
    #: maps the call's arguments to a more specific policy action, e.g.
    #: cc_file with op="delete" -> "file.delete". Default: ``action``.
    action_for: Optional[Callable[[Mapping[str, Any]], str]] = None
    summary_for: Optional[Callable[[Mapping[str, Any]], str]] = None
    #: Only for ``engine.stop``: stopping must work even while a stop is held,
    #: so it is logged but not routed through the runner's stop check.
    bypass_runner: bool = False
    #: Read-only lookup run before the policy so it judges what will really be
    #: touched (e.g. a control given only by ref gets its accessible name added
    #: as ``label``, so a "Delete" button is HIGH however it was referenced).
    enrich: Optional[Callable[[dict], dict]] = None

    @property
    def level(self) -> Level:
        """Static permission level (the runtime policy may raise it)."""
        return BASE_LEVELS.get(self.action, Level.HIGH)

    def validate(self) -> None:
        if not _ID_RE.match(self.id):
            raise ContractError(f"bad tool id {self.id!r}")
        if not self.description.strip():
            raise ContractError(f"{self.id}: description is empty")
        if self.action not in BASE_LEVELS:
            raise ContractError(f"{self.id}: unknown policy action {self.action!r}")
        if not callable(self.handler):
            raise ContractError(f"{self.id}: handler is not callable")
        _check_schema(self.id, self.input_schema)
        if self.bypass_runner and self.action != "engine.stop":
            raise ContractError(f"{self.id}: only engine.stop may bypass the runner")
        if not (0 < float(self.timeout) <= 3600):
            raise ContractError(f"{self.id}: timeout out of range")

    def resolve_action(self, params: Mapping[str, Any]) -> str:
        if self.action_for is None:
            return self.action
        try:
            return str(self.action_for(params) or self.action)
        except Exception:
            return "unknown"           # -> HIGH in the policy (fail closed)

    def call(self, params: Mapping[str, Any] | None, *, cancel_event=None, job_id: str = "",
             origin: str = "owner", tainted: bool = False, progress=None) -> ActionResult:
        params = {k: v for k, v in dict(params or {}).items() if k != "device"}
        if self.bypass_runner:
            return _call_direct(self, params, job_id)
        if self.enrich is not None and flags.enabled() and not _stop_held():
            try:
                params = dict(self.enrich(dict(params)) or params)
            except Exception:
                from jarvis.core import failsoft
                failsoft.suppress("computer_control.contract:enrich")
        summary = ""
        if self.summary_for is not None:
            try:
                summary = str(self.summary_for(params))
            except Exception:
                summary = ""
        return get_runner().run_action(
            self.resolve_action(params), params, self.handler, timeout=self.timeout,
            verify=self.verify, origin=origin, tainted=tainted,
            cancel_event=cancel_event if self.cancellable else None, job_id=job_id,
            summary=summary or self.description.split(".")[0], progress=progress)

    def to_declaration(self) -> dict:
        """The ``TOOL`` dict core/action_loader.py discovers."""
        self.validate()
        spec = self

        def handler(parameters=None, cancel_event=None):
            result = spec.call(parameters or {}, cancel_event=cancel_event)
            return json.dumps(result.as_dict(), ensure_ascii=False, default=str)[:6000]

        handler.__name__ = f"cc_handler_{self.id}"
        return {
            "name": self.id,
            "description": self.description,
            "parameters": self.input_schema,
            "handler": handler,
            "risk": self.level.tool_risk,
            "timeout": float(self.timeout) + 5.0,     # the runner times out first
            "long_running": bool(self.long_running),
            "available": flags.enabled,
            "cc_output_schema": self.output_schema,
        }


def _stop_held() -> bool:
    from jarvis.computer_control import estop
    return estop.get().engaged


def _call_direct(spec: ToolSpec, params: dict, job_id: str) -> ActionResult:
    import time

    from jarvis.computer_control import audit, estop
    from jarvis.computer_control.runner import ActionOutcome

    started = time.monotonic()
    ctx = ActionContext(spec.action, params, estop.EmergencyStop().token(), job_id=job_id)
    try:
        outcome = ActionOutcome.coerce(spec.handler(ctx))
        status = "ok" if outcome.ok else "failed"
    except Exception as exc:
        from jarvis.computer_control.redaction import redact_text
        outcome = ActionOutcome(ok=False, message=redact_text(f"{spec.action} failed: {exc}", 300))
        status = "error"
    result = ActionResult(spec.action, status, outcome.message, Level.LOW, data=outcome.data,
                          verified=outcome.verified, evidence=outcome.evidence,
                          duration_ms=int((time.monotonic() - started) * 1000))
    audit.record(spec.action, params, result.message, status=status, level="low",
                 duration_ms=result.duration_ms, job_id=job_id or None)
    return result


def _check_schema(tool_id: str, schema: Mapping[str, Any], path: str = "") -> None:
    if not isinstance(schema, Mapping):
        raise ContractError(f"{tool_id}: schema at {path or '/'} is not an object")
    kind = schema.get("type")
    if kind not in _GEMINI_TYPES:
        raise ContractError(f"{tool_id}: schema type {kind!r} at {path or '/'} is not a Gemini type")
    if not path and kind != "OBJECT":
        raise ContractError(f"{tool_id}: top-level schema must be OBJECT")
    if kind == "OBJECT":
        props = schema.get("properties", {})
        if not isinstance(props, Mapping):
            raise ContractError(f"{tool_id}: properties must be a mapping")
        if path and not props:
            raise ContractError(f"{tool_id}: nested OBJECT at {path} needs properties (Gemini)")
        for name, sub in props.items():
            _check_schema(tool_id, sub, f"{path}/{name}")
        for name in schema.get("required", []) or []:
            if name not in props:
                raise ContractError(f"{tool_id}: required '{name}' is not a property")
    if kind == "ARRAY":
        _check_schema(tool_id, schema.get("items") or {"type": "STRING"}, f"{path}[]")


class SpecRegistry:
    """The engine's specs, in registration order; ids are unique."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        spec.validate()
        if spec.id in self._specs:
            raise ContractError(f"duplicate tool id {spec.id!r}")
        self._specs[spec.id] = spec
        return spec

    def get(self, tool_id: str) -> Optional[ToolSpec]:
        return self._specs.get(tool_id)

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def declarations(self) -> list[dict]:
        return [spec.to_declaration() for spec in self._specs.values()]
