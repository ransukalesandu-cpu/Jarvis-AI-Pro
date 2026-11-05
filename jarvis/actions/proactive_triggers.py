"""Voice access to proactive triggers: "remind me at 7:30 every day to ...".

The scheduler in core/runtime/live_services.py fires due triggers by injecting
their prompt as a turn, so JARVIS speaks first. See core/triggers.py.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from jarvis.core.triggers import get_trigger_registry
from jarvis.memory.config_manager import get_quiet_hours, save_quiet_hours


def _describe(trig) -> str:
    if trig.cron:
        when = f"cron '{trig.cron}'" + (f" ({trig.tz})" if trig.tz else "")
    elif trig.daily_at:
        when = f"daily at {trig.daily_at}"
    elif trig.every_seconds:
        when = f"every {int(trig.every_seconds // 60)} min"
    elif trig.once_at:
        when = "once at " + datetime.fromtimestamp(trig.once_at).strftime("%Y-%m-%d %H:%M")
    else:
        when = "on a condition"
    state = "" if trig.enabled else " (disabled)"
    kind = " [background task]" if trig.mode == "task" else ""
    return f"{trig.name}: {when}{state}{kind} — {trig.prompt or trig.description}"


def _called_by_scheduled_task() -> bool:
    """True while a task started by a trigger is running.

    Such a task may read triggers but not change them, so an automation can never
    create more automation on its own.
    """
    try:
        from jarvis.agent.integration import get_service
        task = get_service().runner.active_task
        return bool(task and not task.state.terminal and task.source == "trigger")
    except Exception:
        return False


def _describe_run(row: dict) -> str:
    when = datetime.fromtimestamp(row["started"]).strftime("%Y-%m-%d %H:%M")
    extra = f" — {row['detail']}" if row.get("detail") else ""
    return f"{when} {row['name']} [{row['mode']}] {row['status']}{extra}"


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
    if action in ("create", "delete", "enable", "disable", "run_now", "set_quiet_hours") \
            and _called_by_scheduled_task():
        return "A scheduled task cannot change triggers."
    if action == "runs":
        from jarvis.core import trigger_runs
        name = str(p.get("name") or "").strip() or None
        rows = trigger_runs.runs(name, int(p.get("limit") or 10))
        return "\n".join(_describe_run(r) for r in rows) if rows else "No runs recorded yet."
    if action in ("enable", "disable"):
        name = str(p.get("name") or "").strip()
        return (f"Trigger '{name}' {'enabled' if action == 'enable' else 'disabled'}."
                if registry.set_enabled(name, action == "enable") else f"No trigger named '{name}'.")
    if action == "run_now":
        name = str(p.get("name") or "").strip()
        return (f"Trigger '{name}' will run in a few seconds."
                if registry.request_run(name) else f"No runnable trigger named '{name}'.")
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
        if p.get("cron"):
            row["cron"] = str(p["cron"]).strip()
        for key in ("tz", "catch_up", "mode"):
            if p.get(key):
                row[key] = str(p[key]).strip().lower() if key != "tz" else str(p[key]).strip()
        if row.get("daily_at") and row.get("tz"):
            # A daily time in another zone is just a cron expression in that zone.
            hh, mm = str(row.pop("daily_at")).split(":")
            row["cron"] = f"{int(mm)} {int(hh)} * * *"
        if p.get("max_per_hour"):
            row["max_per_hour"] = int(p["max_per_hour"])
        trig = registry.register(row, source="user", persist=True)
        return f"Trigger saved. {_describe(trig)}"
    return (f"Unknown action '{action}'. Use create, list, runs, run_now, enable, "
            "disable, delete or set_quiet_hours.")


TOOL = {
    "name": "proactive_triggers",
    "description": (
        "Create, list or delete things that make JARVIS speak first: reminders, "
        "a morning briefing, periodic check-ins. Use create with a short "
        "identifier name, the prompt JARVIS should act on when it fires, and "
        "exactly one of daily_at (HH:MM), every_minutes, once_at "
        "('YYYY-MM-DD HH:MM' or 'HH:MM'), or cron (5-field expression such as "
        "'30 7 * * 1-5', optional tz like 'Asia/Colombo'). mode 'task' runs the prompt "
        "as a silent background task and announces the result; catch_up 'skip' drops "
        "missed runs. runs lists recent run history, run_now fires a trigger at once, "
        "enable/disable switch one. set_quiet_hours takes 'HH:MM-HH:MM' "
        "or an empty string to turn quiet hours off."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "create | list | runs | run_now | enable | disable | delete | set_quiet_hours"},
            "name": {"type": "STRING", "description": "Identifier, e.g. morning_briefing"},
            "prompt": {"type": "STRING", "description": "What JARVIS should do or say when it fires"},
            "daily_at": {"type": "STRING", "description": "HH:MM, every day"},
            "every_minutes": {"type": "NUMBER", "description": "Repeat interval in minutes (min 1)"},
            "once_at": {"type": "STRING", "description": "One time: 'YYYY-MM-DD HH:MM' or 'HH:MM'"},
            "cron": {"type": "STRING", "description": "5-field cron expression, e.g. '0 9 * * mon'"},
            "tz": {"type": "STRING", "description": "IANA time zone for cron/daily_at, e.g. Asia/Colombo"},
            "mode": {"type": "STRING", "description": "turn (speak, default) | task (silent background task)"},
            "catch_up": {"type": "STRING", "description": "once (fire late, default) | skip (drop missed runs)"},
            "max_per_hour": {"type": "NUMBER", "description": "Fire budget per hour (default 12)"},
            "limit": {"type": "NUMBER", "description": "For runs: how many entries"},
            "respect_quiet_hours": {"type": "BOOLEAN", "description": "Hold during quiet hours (default true)"},
            "quiet_hours": {"type": "STRING", "description": "For set_quiet_hours: 'HH:MM-HH:MM'"},
            "description": {"type": "STRING"},
        },
        "required": ["action"],
    },
    "handler": proactive_triggers,
}
