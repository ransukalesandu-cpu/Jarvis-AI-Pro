"""Generic calendar tool: read and create events through any CalendarProvider.

Hidden from Gemini until a provider is configured (core/mail_calendar.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from core import injection_guard
from core.mail_calendar import calendar_provider


def calendar(parameters: dict, **_ctx) -> str:
    p = parameters or {}
    provider = calendar_provider()
    if provider is None:
        return "No calendar is connected yet. Connect one in Plugin Settings first."
    action = str(p.get("action") or "list").strip().lower()
    if action == "list":
        rows = provider.list_events(int(p.get("days") or 1), int(p.get("max_results") or 10))
        if not rows:
            return "Nothing on the calendar in that window."
        text = "\n".join(f"- {r['start']}: {r['title']}" + (f" @ {r['location']}" if r.get("location") else "")
                         for r in rows)
        # Event titles and invites come from other people: treat as content.
        return injection_guard.wrap_untrusted(text, "calendar")
    if action == "create":
        title = str(p.get("title") or "").strip()
        start = str(p.get("start") or "").strip()
        if not title or not start:
            return "I need a title and a start time (ISO format, e.g. 2026-11-03T15:00:00)."
        try:
            start_dt = datetime.fromisoformat(start)
        except ValueError:
            return "The start time must be ISO format, e.g. 2026-11-03T15:00:00."
        end = str(p.get("end") or "").strip()
        if not end:
            end = (start_dt + timedelta(minutes=int(p.get("duration_minutes") or 60))).isoformat()
        if start_dt.tzinfo is None:
            local = datetime.now().astimezone().tzinfo
            start = start_dt.replace(tzinfo=local).isoformat()
            end_dt = datetime.fromisoformat(end)
            end = (end_dt if end_dt.tzinfo else end_dt.replace(tzinfo=local)).isoformat()
        ev = provider.create_event(title, start, end, str(p.get("description") or ""),
                                   str(p.get("location") or ""))
        return f"Created '{ev['title']}' from {ev['start']} to {ev['end']}."
    return f"Unknown calendar action '{action}'. Use list or create."


TOOL = {
    "name": "calendar",
    "description": (
        "The owner's calendar. action=list shows events for the next `days` days; "
        "action=create adds an event (title, start as ISO local time, optional end "
        "or duration_minutes, description, location)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "list | create"},
            "days": {"type": "INTEGER"},
            "max_results": {"type": "INTEGER"},
            "title": {"type": "STRING"},
            "start": {"type": "STRING"},
            "end": {"type": "STRING"},
            "duration_minutes": {"type": "INTEGER"},
            "description": {"type": "STRING"},
            "location": {"type": "STRING"},
        },
        "required": ["action"],
    },
    "handler": calendar,
    "risk": "write",
    "timeout": 60,
    "available": lambda: calendar_provider() is not None,
}
