"""ToolSpec ↔ MCP / JSON Schema (Project 7, evaluated against mediar-ai/terminator).

terminator (MIT) exposes Windows automation as an MCP server backed by a Rust
UIA engine. JARVIS already has a full UIA path (pywinauto) and must keep every
action behind its own policy/approval, so terminator is not adopted as a
dependency. What is taken: the *shape* — every computer-control function is one
tool with a JSON Schema input, a JSON result and an explicit risk annotation.

This module converts the engine's ToolSpecs to MCP tool descriptors
(``name``, ``description``, ``inputSchema``, ``annotations``) so they can be
listed, documented or exported. JARVIS does **not** run an MCP *server* for
them: an external MCP client is not the owner, so exposing these tools would
let another program drive the PC. That stays off until the owner decides
otherwise (documented in SECURITY_MODEL.md); calls from external MCP *servers*
JARVIS connects to keep going through ``core/security`` (DANGEROUS unless the
server marks the tool read-only).
"""
from __future__ import annotations

from typing import Any, Mapping

from jarvis.computer_control.contract import SpecRegistry, ToolSpec
from jarvis.computer_control.policy import Level

_TYPE = {"STRING": "string", "NUMBER": "number", "INTEGER": "integer", "BOOLEAN": "boolean",
         "ARRAY": "array", "OBJECT": "object"}


def json_schema(gemini: Mapping[str, Any]) -> dict:
    """Gemini function-declaration schema → standard JSON Schema."""
    out: dict = {"type": _TYPE.get(str(gemini.get("type")), "string")}
    for key in ("description", "enum"):
        if key in gemini:
            out[key] = gemini[key]
    if out["type"] == "object":
        out["properties"] = {k: json_schema(v) for k, v in (gemini.get("properties") or {}).items()}
        if gemini.get("required"):
            out["required"] = list(gemini["required"])
        out["additionalProperties"] = True
    if out["type"] == "array":
        out["items"] = json_schema(gemini.get("items") or {"type": "STRING"})
    return out


def mcp_descriptor(spec: ToolSpec) -> dict:
    level = spec.level
    return {
        "name": spec.id,
        "description": spec.description,
        "inputSchema": json_schema(spec.input_schema),
        "outputSchema": spec.output_schema,
        "annotations": {
            "readOnlyHint": level is Level.LOW and spec.action not in ("engine.stop",),
            "destructiveHint": level is Level.HIGH,
            "openWorldHint": spec.id in ("cc_browser", "cc_screen"),
            "x-jarvis-risk": level.value,
            "x-jarvis-timeout-s": spec.timeout,
            "x-jarvis-cancellable": spec.cancellable,
            "x-jarvis-long-running": spec.long_running,
        },
    }


def mcp_tools(specs: SpecRegistry) -> list[dict]:
    return [mcp_descriptor(s) for s in specs.specs()]


def validate_args(spec: ToolSpec, args: Mapping[str, Any]) -> list[str]:
    """Minimal JSON-Schema check (required, enum, primitive types) for one call."""
    schema = json_schema(spec.input_schema)
    errors = []
    for name in schema.get("required", []):
        if name not in args:
            errors.append(f"missing required argument '{name}'")
    py = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list,
          "object": dict}
    for name, value in args.items():
        prop = schema["properties"].get(name)
        if prop is None:
            continue
        expected = py.get(prop["type"])
        if expected and not isinstance(value, expected) or (prop["type"] == "integer" and isinstance(value, bool)):
            errors.append(f"'{name}' should be {prop['type']}")
        if "enum" in prop and value not in prop["enum"]:
            errors.append(f"'{name}' must be one of {prop['enum']}")
    return errors
