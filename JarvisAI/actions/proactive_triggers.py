"""Voice access to proactive triggers: "remind me at 7:30 every day to ...".

The scheduler in core/runtime/live_services.py fires due triggers by injecting
their prompt as a turn, so JARVIS speaks first. See core/triggers.py.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from core.triggers import get_trigger_registry
from memory.config_manager import get_quiet_hours, save_quiet_hours


def _describe(trig) -> str:
    if trig.daily_at:
        when = f"daily at {trig.daily_at}"
    elif trig.every_seconds:
        when = f"every {int(trig.every_seconds // 60)} min"
    elif trig.once_at:
        when = "once at " + datetime.fromtimestamp(trig.once_at).strftime("%Y-%m-%d %H:%M")
    else:
        when = "on a condition"
    state = "" if trig.enabled else " (disabled)"
    return f"{trig.name}: {when}{state} — {trig.prompt or trig.description}"


def _parse_once(value: str) -> float:
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%H:%M":
            # A bare time means the next occurrence: today, or tomorrow if passed.
            today = datetime.now().replace(hour=parsed.hour, minute=parsed.minute,
                                           second=0, microsecond=0)
            stamp = today.timestamp()
            return stamp if stamp > time.time() else (today + timedelta(days=1)).timestamp()
        return parsed.timestamp()
    raise ValueError("once_at must look like 'YYYY-MM-DD HH:MM' or 'HH:MM'")


def proactive_triggers(parameters: dict, **_ctx) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    registry = get_trigger_registry()
    if action == "list":
        rows = [_describe(t) for t in registry.list()]
        quiet = get_quiet_hours() or "none"
        return ("Triggers:\n" + "\n".join(rows) if rows else "No triggers.") + f"\nQuiet hours: {quiet}"
    if action == "delete":
        name = str(p.get("name") or "").strip()
        return f"Deleted trigger '{name}'." if registry.unregister(name) else (
            f"No user trigger named '{name}'.")
    if action == "set_quiet_hours":
        value = str(p.get("quiet_hours") or "").strip()
        save_quiet_hours(value)
        return f"Quiet hours set to {value}." if value else "Quiet hours turned off."
    if action == "create":
        row = {
            "name": str(p.get("name") or "").strip(),
            "prompt": str(p.get("prompt") or "").strip(),
            "description": str(p.get("description") or "").strip(),
            "respect_quiet_hours": bool(p.get("respect_quiet_hours", True)),
        }
        if p.get("daily_at"):
            row["daily_at"] = str(p["daily_at"]).strip()
        if p.get("every_minutes"):
            row["every_seconds"] = float(p["every_minutes"]) * 60
        if p.get("once_at"):
            row["once_at"] = _parse_once(p["once_at"])
        trig = registry.register(row, source="user", persist=True)
        return f"Trigger saved. {_describe(trig)}"
    return f"Unknown action '{action}'. Use create, list, delete or set_quiet_hours."


TOOL = {
    "name": "proactive_triggers",
    "description": (
        "Create, list or delete things that make JARVIS speak first: reminders, "
        "a morning briefing, periodic check-ins. Use create with a short "
        "identifier name, the prompt JARVIS should act on when it fires, and "
        "exactly one of daily_at (HH:MM), every_minutes, or once_at "
        "('YYYY-MM-DD HH:MM' or 'HH:MM'). set_quiet_hours takes 'HH:MM-HH:MM' "
        "or an empty string to turn quiet hours off."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "create | list | delete | set_quiet_hours"},
            "name": {"type": "STRING", "description": "Identifier, e.g. morning_briefing"},
            "prompt": {"type": "STRING", "description": "What JARVIS should do or say when it fires"},
            "daily_at": {"type": "STRING", "description": "HH:MM, every day"},
            "every_minutes": {"type": "NUMBER", "description": "Repeat interval in minutes (min 1)"},
            "once_at": {"type": "STRING", "description": "One time: 'YYYY-MM-DD HH:MM' or 'HH:MM'"},
            "respect_quiet_hours": {"type": "BOOLEAN", "description": "Hold during quiet hours (default true)"},
            "quiet_hours": {"type": "STRING", "description": "For set_quiet_hours: 'HH:MM-HH:MM'"},
            "description": {"type": "STRING"},
        },
        "required": ["action"],
    },
    "handler": proactive_triggers,
}
