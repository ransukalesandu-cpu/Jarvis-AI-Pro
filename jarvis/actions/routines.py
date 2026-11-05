"""Routines by voice: "save this as work mode", "start work mode".

Saving takes this session's successful state-changing tool calls since the
last save (or an explicit `steps` list); running replays them in order through
the normal tool registry. Stored in the owner's SQLite store.
"""
from __future__ import annotations

from jarvis.core.routines import get_routine_store, replay, steps_from_session
from jarvis.core.tool_runtime import json_object_arg

_session_marker = {"index": 0}


def routine(parameters: dict, dispatch=None, session_calls=None, cancel_event=None,
            **_ctx) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    store = get_routine_store()
    name = str(p.get("name") or "").strip()
    if action == "list":
        rows = store.list()
        if not rows:
            return "No routines saved yet."
        return "\n".join(f"{r['name']}: " + ", ".join(s["tool"] for s in r["steps"]) for r in rows)
    if action == "delete":
        return f"Deleted routine '{name}'." if store.delete(name) else f"No routine named '{name}'."
    if action == "show":
        r = store.get(name)
        if r is None:
            return f"No routine named '{name}'."
        return "\n".join(f"{i}. {s['tool']} {s['args']}" for i, s in enumerate(r["steps"], 1))
    if action in ("save", "edit"):
        steps = [{"tool": s.get("tool"), "args": json_object_arg(s.get("args"))}
                 for s in (p.get("steps") or []) if isinstance(s, dict)]
        if not steps:
            calls = list(session_calls or [])
            steps = steps_from_session(calls, _session_marker["index"])
            _session_marker["index"] = len(calls)
        if not steps:
            return "There is nothing to save yet: do the steps first, then ask me to save them."
        store.save(name, steps, str(p.get("description") or ""))
        return (f"Saved routine '{name}' with {len(steps)} step(s): "
                + ", ".join(s["tool"] for s in steps) + ".")
    if action == "run":
        r = store.get(name)
        if r is None:
            return f"No routine named '{name}'."
        if dispatch is None:
            return "Routines can only run inside a live session."
        lines = replay(r["steps"], dispatch, cancel_event=cancel_event)
        store.mark_run(name)
        return f"Ran routine '{r['name']}':\n" + "\n".join(lines)
    return "Use action save, run, list, show or delete."


TOOL = {
    "name": "routine",
    "description": (
        "Save and replay routines. action=save with a name stores the tool calls "
        "made since the last save (or pass steps=[{tool, args}]); action=run replays "
        "a routine by name; list, show and delete manage them."),
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "description": "save | edit | run | list | show | delete"},
        "name": {"type": "STRING"},
        "description": {"type": "STRING"},
        "steps": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "tool": {"type": "STRING"},
            "args": {"type": "STRING", "description": "JSON object of the tool's arguments"},
        }}},
    }, "required": ["action"]},
    "handler": routine,
    "risk": "write",
    "timeout": 900,
}
