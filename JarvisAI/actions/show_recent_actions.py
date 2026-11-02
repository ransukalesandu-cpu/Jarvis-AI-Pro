"""'What did you just do?' — read back the action log (core/action_log.py)."""
from __future__ import annotations

from core import action_log


def show_recent_actions(parameters: dict, **_ctx) -> str:
    p = parameters or {}
    rows = action_log.recent(int(p.get("limit") or 10), str(p.get("tool") or "") or None)
    if not rows:
        return "I haven't run any tools yet."
    lines = []
    for row in rows:
        args = ", ".join(f"{k}={str(v)[:60]}" for k, v in (row.get("args") or {}).items())
        lines.append(f"{row['ts']} {row['tool']}({args}) -> {row['status']}: "
                     f"{str(row.get('result', ''))[:140]}")
    return "Most recent first:\n" + "\n".join(lines)


TOOL = {
    "name": "show_recent_actions",
    "description": (
        "List the tool calls JARVIS ran most recently (time, tool, arguments, "
        "result, status). Use for 'what did you just do?'."),
    "parameters": {"type": "OBJECT", "properties": {
        "limit": {"type": "INTEGER", "description": "default 10"},
        "tool": {"type": "STRING", "description": "only this tool"},
    }},
    "handler": show_recent_actions,
    "risk": "read",
    "timeout": 10,
}
