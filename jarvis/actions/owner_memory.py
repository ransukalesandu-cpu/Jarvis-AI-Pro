"""Owner rules and facts by voice (Module 6). Routines: see actions/routines.py.

rules — "flag every email from my bank", "when a file appears in Downloads,
         tell me", "every time the morning trigger fires, open my mail".
facts — "remember that my car is a blue Corolla".

Both live in the owner's SQLite store and are loaded into every session.
"""
from __future__ import annotations

import json

from jarvis.core import events
from jarvis.core.owner_store import get_owner_store
from jarvis.core.tool_runtime import json_object_arg


def _describe_rule(r: dict) -> str:
    cond = ", ".join(f"{k} contains '{v}'" for k, v in r["conditions"].items()) or "any event"
    extra = f" {json.dumps(r['action_args'])}" if r["action_args"] else ""
    state = "" if r["enabled"] else " (disabled)"
    return (f"{r['name']}: on {r['source']} where {cond} -> {r['action']}{extra}{state}; "
            f"fired {r['fire_count']} time(s)")


def rules(parameters: dict, **_ctx) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    store = get_owner_store().rules
    name = str(p.get("name") or "").strip()
    if action == "list":
        rows = store.list()
        return "\n".join(_describe_rule(r) for r in rows) if rows else "No rules yet."
    if action in ("add", "edit"):
        existing = store.get(name) if action == "edit" else None
        if action == "edit" and existing is None:
            return f"No rule named '{name}'."
        base = existing or {}
        rule = store.save(
            name,
            p.get("source") or base.get("source") or "*",
            json_object_arg(p["conditions"]) if p.get("conditions") is not None
            else base.get("conditions", {}),
            p.get("rule_action") or base.get("action") or "notify",
            json_object_arg(p["action_args"]) if p.get("action_args") is not None
            else base.get("action_args", {}),
            bool(p.get("enabled", base.get("enabled", True))),
        )
        return f"Rule saved. {_describe_rule(rule)}"
    if action == "delete":
        return f"Deleted rule '{name}'." if store.delete(name) else f"No rule named '{name}'."
    if action in ("enable", "disable"):
        ok = store.set_enabled(name, action == "enable")
        return f"Rule '{name}' {action}d." if ok else f"No rule named '{name}'."
    if action == "test":
        payload = json_object_arg(p.get("payload"))
        fired = events.emit(str(p.get("source") or "test"), payload)
        return f"Test event fired: {', '.join(fired)}." if fired else "No rule matched the test event."
    return "Use action add, edit, list, delete, enable, disable or test."


def facts(parameters: dict, **_ctx) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    store = get_owner_store().facts
    key = str(p.get("key") or "").strip()
    if action in ("remember", "add", "edit"):
        fact = store.remember(key, str(p.get("value") or ""))
        return f"Remembered: {fact['key']} = {fact['value']}."
    if action == "list":
        rows = store.list()
        return "\n".join(f"{r['key']}: {r['value']}" for r in rows) if rows else "No saved facts."
    if action in ("forget", "delete"):
        return f"Forgot '{key}'." if store.delete(key) else f"No fact named '{key}'."
    return "Use action remember, edit, list or forget."


TOOLS = [
    {
        "name": "rules",
        "description": (
            "Owner rules that run automatically when an event happens. add/edit with "
            "name, source (email | schedule | file | * for any), conditions "
            "({field: text the field must contain}; email fields: from, subject, snippet; "
            "file fields: path, name, change; schedule: name; 'text' = any field), "
            "rule_action (notify | flag | tool) and action_args ({message} for notify/flag, "
            "{tool, args} for tool, {folder} to watch for file rules; args may use "
            "{field} placeholders). list, delete, enable, disable, test (source + payload)."),
        "parameters": {"type": "OBJECT", "properties": {
            "action": {"type": "STRING", "description": "add | edit | list | delete | enable | disable | test"},
            "name": {"type": "STRING"},
            "source": {"type": "STRING"},
            "conditions": {"type": "STRING", "description": 'JSON object, e.g. {"from": "mybank"}'},
            "rule_action": {"type": "STRING", "description": "notify | flag | tool"},
            "action_args": {"type": "STRING", "description": 'JSON object, e.g. {"message": "..."}'},
            "enabled": {"type": "BOOLEAN"},
            "payload": {"type": "STRING", "description": "JSON object for action=test"},
        }, "required": ["action"]},
        "handler": rules, "risk": "write", "timeout": 15,
    },
    {
        "name": "facts",
        "description": (
            "Short facts the owner explicitly asks JARVIS to remember (key + value), "
            "loaded into every session. action: remember | edit | list | forget."),
        "parameters": {"type": "OBJECT", "properties": {
            "action": {"type": "STRING"},
            "key": {"type": "STRING"},
            "value": {"type": "STRING"},
        }, "required": ["action"]},
        "handler": facts, "risk": "write", "timeout": 10,
    },
]
