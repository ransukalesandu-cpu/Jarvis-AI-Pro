"""Routines by voice: "save this as work mode", "start work mode".

Saving takes this session's successful state-changing tool calls since the
last save (or an explicit `steps` list); running replays them in order through
the normal tool registry. Stored in the owner's SQLite store.
"""
from __future__ import annotations

from jarvis.core import routines_file
from jarvis.core.routines import get_routine_store, replay, steps_from_session
from jarvis.core.tool_runtime import json_object_arg

_session_marker = {"index": 0}


def routine(parameters: dict, dispatch=None, session_calls=None, cancel_event=None,
            **_ctx) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    store = get_routine_store()
    name = str(p.get("name") or "").strip()
    file_routines, file_errors = routines_file.load()
    if action == "list":
        rows = store.list()
        known = {r["name"] for r in rows}
        lines = [f"{r['name']}: " + ", ".join(s["tool"] for s in r["steps"]) for r in rows]
        for r in file_routines.values():
            if r["name"] not in known:
                said = f" (say: {', '.join(r['phrases'])})" if r["phrases"] else ""
                lines.append(f"{r['name']} [routines file]{said}: " + ", ".join(s["tool"] for s in r["steps"]))
        lines += [f"Routines file problem: {e}" for e in file_errors]
        return "\n".join(lines) if lines else "No routines saved yet."
    if action == "delete":
        if store.delete(name):
            return f"Deleted routine '{name}'."
        if routines_file.get(name):
            return f"'{name}' comes from the owner's routines file; only the owner can edit that file."
        return f"No routine named '{name}'."
    if action == "show":
        r = store.get(name) or routines_file.get(name)
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
        from_file = r is None
        if from_file:
            r = routines_file.get(name)
        if r is None:
            return f"No routine named '{name}'."
        if dispatch is None:
            return "Routines can only run inside a live session."
        lines = replay(r["steps"], dispatch, cancel_event=cancel_event)
        if not from_file:
            store.mark_run(name)
        return f"Ran routine '{r['name']}':\n" + "\n".join(lines)
    return "Use action save, run, list, show or delete."


TOOL = {
    "name": "routine",
    "description": (
        "Save and replay routines. action=save with a name stores the tool calls "
        "made since the last save (or pass steps=[{tool, args}]); action=run replays "
        "a routine by name (saved ones and the owner's routines file, e.g. 'morning', "
        "'work mode'); list, show and delete manage them."),
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
