"""Local day planner, event memory, and alarm-backed reminders for JARVIS."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from actions.reminder import reminder as _reminder

_LOCK = threading.RLock()
_MAX_ITEMS = 1000
_MAX_PLAN_ITEMS = 30
_KINDS = {"task", "event", "note"}


def _store_path() -> Path:
    override = os.environ.get("JARVIS_PLANNER_FILE", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".jarvis" / "daily_planner.json"


def _load_state() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {"version": 1, "items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        # Do not replace a corrupt/unreadable file with an empty plan.
        raise ValueError("The saved planner file could not be read; it was left untouched.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
        raise ValueError("The saved planner file has an unsupported format; it was left untouched.")
    items = [row for row in data.get("items", []) if isinstance(row, dict) and row.get("id")]
    return {"version": 1, "items": items[-_MAX_ITEMS:]}


def _save_state(state: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "items": list(state.get("items", []))[-_MAX_ITEMS:],
    }
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(state, ensure_ascii=False, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _clean(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().casefold() not in {"false", "0", "no", "off", "disabled", ""}


def _validate_schedule(date_text: str, time_text: str) -> tuple[date | None, time | None, str]:
    if bool(date_text) != bool(time_text):
        return None, None, "A dated alarm needs both date (YYYY-MM-DD) and time (HH:MM)."
    if not date_text:
        return None, None, ""
    try:
        day = date.fromisoformat(date_text)
        clock = time.fromisoformat(time_text)
    except (TypeError, ValueError):
        return None, None, "I couldn't read that date/time. Use YYYY-MM-DD and HH:MM (24-hour time)."
    if clock.second or clock.microsecond:
        return None, None, "Use HH:MM without seconds for the alarm time."
    return day, clock, ""


def _scheduled_datetime(item: dict[str, Any]) -> datetime | None:
    try:
        if not item.get("date") or not item.get("time"):
            return None
        return datetime.combine(date.fromisoformat(item["date"]), time.fromisoformat(item["time"]))
    except (TypeError, ValueError):
        return None


def _set_alarm(item: dict[str, Any]) -> tuple[bool, str]:
    when = _scheduled_datetime(item)
    if when is None or not item.get("alarm_enabled", True):
        item["alarm_status"] = "none"
        return True, ""
    if when <= datetime.now():
        item["alarm_status"] = "failed"
        return False, "The item was saved, but its alarm time is in the past."
    result = _reminder({
        "action": "reminder",
        "date": item["date"],
        "time": item["time"],
        "message": item["title"],
    })
    if isinstance(result, str) and result.startswith("Reminder set for "):
        item["alarm_status"] = "scheduled"
        return True, ""
    item["alarm_status"] = "failed"
    return False, _clean(result, 240) or "The OS scheduler did not accept the alarm."


def _cancel_alarm(item: dict[str, Any]) -> bool:
    when = _scheduled_datetime(item)
    if not when or when <= datetime.now() or item.get("alarm_status") != "scheduled":
        return True
    result = _reminder({
        "action": "cancel",
        "date": item["date"],
        "time": item["time"],
        "message": item["title"],
    })
    ok = isinstance(result, str) and result.startswith("Reminder cancelled")
    if ok:
        item["alarm_status"] = "cancelled"
    return ok


def _new_item(data: dict[str, Any], fallback_date: str = "", default_kind: str = "task") -> tuple[dict[str, Any] | None, str]:
    title = _clean(data.get("title") or data.get("summary"), 160)
    if not title:
        return None, "Every plan item needs a title."
    day_text = _clean(data.get("date"), 10) or fallback_date
    time_text = _clean(data.get("time"), 5)
    day, clock, error = _validate_schedule(day_text, time_text)
    if error:
        return None, f"{title}: {error}"
    if day and clock and datetime.combine(day, clock) <= datetime.now():
        return None, f"{title}: that time has already passed. Nothing was scheduled."
    kind = _clean(data.get("kind"), 12).lower() or default_kind
    if kind not in _KINDS:
        kind = default_kind if default_kind in _KINDS else "task"
    alarm_enabled = _truthy(data.get("alarm"), default=bool(day and clock))
    try:
        duration = int(data.get("duration_minutes") or 0)
    except (TypeError, ValueError):
        duration = 0
    duration = max(0, min(duration, 24 * 60))
    now = datetime.now().isoformat(timespec="seconds")
    item = {
        "id": uuid.uuid4().hex[:10],
        "title": title,
        "kind": kind,
        "notes": _clean(data.get("notes") or data.get("details"), 500),
        "date": day.isoformat() if day else "",
        "time": clock.strftime("%H:%M") if clock else "",
        "duration_minutes": duration,
        "status": "pending",
        "alarm_enabled": bool(alarm_enabled and day and clock),
        "alarm_status": "none",
        "created_at": now,
        "updated_at": now,
    }
    if item["alarm_enabled"]:
        _, alarm_error = _set_alarm(item)
        if alarm_error:
            item["alarm_error"] = alarm_error[:240]
    return item, ""


def _find_item(items: list[dict[str, Any]], item_id: str = "", title: str = "") -> tuple[dict[str, Any] | None, str]:
    wanted_id = _clean(item_id, 40).casefold()
    wanted_title = _clean(title, 160).casefold()
    matches = [
        row for row in items
        if (wanted_id and str(row.get("id", "")).casefold().startswith(wanted_id))
        or (not wanted_id and wanted_title and str(row.get("title", "")).casefold() == wanted_title)
    ]
    if not matches:
        return None, "I couldn't find that saved item."
    if len(matches) > 1:
        return None, "More than one item has that title. Use the short item ID from the list."
    return matches[0], ""


def _sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (str(item.get("date") or "9999-99-99"), str(item.get("time") or "99:99"), str(item.get("created_at") or ""))


def _format_item(item: dict[str, Any]) -> str:
    ref = str(item.get("id", ""))[:6]
    when = ""
    if item.get("date"):
        when = str(item["date"])
        if item.get("time"):
            when += " at " + str(item["time"])
    elif item.get("time"):
        when = "at " + str(item["time"])
    status = str(item.get("status") or "pending")
    alarm = str(item.get("alarm_status") or "none")
    line = f"[{ref}] {when + ' — ' if when else ''}{item.get('title', '(untitled)')} ({status}"
    if item.get("alarm_enabled"):
        line += f", alarm: {alarm}"
    line += ")"
    if item.get("notes"):
        line += f" — {item['notes']}"
    if item.get("alarm_error") and alarm == "failed":
        line += f" [alarm issue: {item['alarm_error']}]"
    return line


def _display(items: list[dict[str, Any]], empty_message: str) -> str:
    if not items:
        return empty_message
    return "\n".join(_format_item(item) for item in sorted(items, key=_sort_key)[:30])


def daily_planner(parameters: dict, player=None, session_memory=None) -> str:
    """Save and recall local plans/events; schedule OS notifications for timed items."""
    operation = _clean(parameters.get("operation") or "today", 24).lower()
    try:
        with _LOCK:
            state = _load_state()
            items: list[dict[str, Any]] = state["items"]
            today = date.today().isoformat()

            if operation in {"plan", "add", "remember"}:
                if operation == "plan":
                    plan_items = parameters.get("items")
                    if not isinstance(plan_items, list) or not plan_items:
                        return "Give me the day's activities as items with a title and, when known, a time. No plan was changed."
                    if len(plan_items) > _MAX_PLAN_ITEMS:
                        return f"I can add up to {_MAX_PLAN_ITEMS} items in one plan request."
                    fallback_date = _clean(parameters.get("date"), 10) or today
                    # Validate the day once so a typo cannot silently schedule every item on the wrong day.
                    try:
                        date.fromisoformat(fallback_date)
                    except ValueError:
                        return "Use YYYY-MM-DD for the plan date. No plan was changed."
                    added: list[dict[str, Any]] = []
                    errors: list[str] = []
                    for raw in plan_items:
                        if not isinstance(raw, dict):
                            errors.append("Skipped one invalid plan item.")
                            continue
                        item, error = _new_item(raw, fallback_date=fallback_date, default_kind="task")
                        if error:
                            errors.append(error)
                            continue
                        if item is None:
                            continue
                        items.append(item)
                        added.append(item)
                    if not added:
                        return "I couldn't save any plan items. " + " ".join(errors[:3])
                    state["items"] = items[-_MAX_ITEMS:]
                    _save_state(state)
                    scheduled = sum(row.get("alarm_status") == "scheduled" for row in added)
                    lines = [f"Saved {len(added)} plan item(s); {scheduled} alarm(s) registered with the OS scheduler."]
                    if errors:
                        lines.append("Notes: " + " ".join(errors[:5]))
                    lines.extend(_format_item(row) for row in sorted(added, key=_sort_key))
                    return "\n".join(lines)

                item, error = _new_item(parameters, fallback_date=_clean(parameters.get("date"), 10), default_kind="task")
                if error:
                    return error
                if item is None:
                    return "Nothing was saved."
                items.append(item)
                state["items"] = items[-_MAX_ITEMS:]
                _save_state(state)
                if item.get("alarm_status") == "scheduled":
                    return "Remembered and alarm set: " + _format_item(item)
                if item.get("date") and item.get("time") and item.get("alarm_status") == "failed":
                    return "Saved, but I could not confirm the alarm: " + _format_item(item)
                return "Remembered for later: " + _format_item(item)

            if operation in {"today", "list", "upcoming", "recall", "checkin"}:
                pending = [row for row in items if row.get("status", "pending") == "pending"]
                if operation == "today":
                    target_day = _clean(parameters.get("date"), 10) or today
                    try:
                        date.fromisoformat(target_day)
                    except ValueError:
                        return "Use YYYY-MM-DD to choose a date."
                    selected = [row for row in pending if row.get("date") == target_day]
                    return f"Plan for {target_day}:\n" + _display(selected, "No saved items for that day.")
                if operation == "upcoming":
                    selected = [row for row in pending if row.get("date") and row.get("date") >= today]
                    return "Upcoming items:\n" + _display(selected, "No upcoming saved items.")
                if operation == "checkin":
                    overdue = [row for row in pending if row.get("date") and row.get("date") < today]
                    today_rows = [row for row in pending if row.get("date") == today]
                    unscheduled = [row for row in pending if not row.get("date")]
                    sections = ["Your check-in:"]
                    sections.append("Overdue / may have been missed:\n" + _display(overdue, "Nothing overdue in the saved planner."))
                    sections.append("Today's plan:\n" + _display(today_rows, "No saved items for today."))
                    sections.append("Remembered without a date:\n" + _display(unscheduled, "No undated tasks saved."))
                    return "\n\n".join(sections)
                return "Saved pending items:\n" + _display(pending, "There are no pending saved items.")

            if operation in {"complete", "done"}:
                item, error = _find_item(items, parameters.get("item_id", ""), parameters.get("title", ""))
                if error:
                    return error
                if item is None:
                    return "No item was changed."
                cancel_failed = not _cancel_alarm(item)
                item["status"] = "completed"
                item["updated_at"] = datetime.now().isoformat(timespec="seconds")
                _save_state(state)
                suffix = " The OS alarm could not be cancelled, so it may still fire." if cancel_failed else ""
                return f"Marked completed: {_format_item(item)}.{suffix}"

            if operation in {"reschedule", "move"}:
                item, error = _find_item(items, parameters.get("item_id", ""), parameters.get("title", ""))
                if error:
                    return error
                if item is None:
                    return "No item was changed."
                new_date = _clean(parameters.get("date"), 10)
                new_time = _clean(parameters.get("time"), 5)
                day, clock, schedule_error = _validate_schedule(new_date, new_time)
                if schedule_error:
                    return schedule_error
                if not day or not clock:
                    return "Provide both the new date and time."
                target = datetime.combine(day, clock)
                if target <= datetime.now():
                    return "That new time is in the past; the item was not changed."
                previous = dict(item)
                if not _cancel_alarm(item):
                    return "I couldn't cancel the previous OS alarm, so I left the item unchanged."
                item["date"] = day.isoformat()
                item["time"] = clock.strftime("%H:%M")
                item["alarm_enabled"] = _truthy(parameters.get("alarm"), default=previous.get("alarm_enabled", True))
                item["updated_at"] = datetime.now().isoformat(timespec="seconds")
                item.pop("alarm_error", None)
                _, alarm_error = _set_alarm(item)
                _save_state(state)
                if alarm_error:
                    return "Rescheduled, but the new alarm could not be confirmed: " + _format_item(item) + f" ({alarm_error})"
                return "Rescheduled: " + _format_item(item)

            if operation in {"forget", "delete", "remove"}:
                item, error = _find_item(items, parameters.get("item_id", ""), parameters.get("title", ""))
                if error:
                    return error
                if item is None:
                    return "No item was removed."
                if not _cancel_alarm(item):
                    return "I couldn't cancel its OS alarm, so I kept the item saved. Try again or manage the alarm in your OS scheduler."
                items.remove(item)
                _save_state(state)
                return f"Forgotten and removed: {_format_item(item)}"

            return "Choose operation: plan, add, remember, today, list, upcoming, checkin, complete, reschedule, or forget."
    except (OSError, ValueError) as exc:
        return f"The planner could not safely update its saved data: {_clean(exc, 240)}"


TOOL = {
    "name": "daily_planner",
    "description": (
        "JARVIS local day planner and remembered-to-do list. Use this when the user asks to plan a day, "
        "remember an event/task, list their plan, ask what they may have forgotten, reschedule an item, "
        "or mark/forget an item. A timed plan item automatically registers a native OS reminder alarm; "
        "the planner keeps pending items locally across restarts. For a multi-item day plan use operation='plan' "
        "with items containing title and optional date, time, duration_minutes, kind, notes, alarm. "
        "Use operation='checkin' for overdue unfinished items plus today's plan; 'complete' for done; "
        "'forget' to remove an item. Dates must be YYYY-MM-DD and times HH:MM in the computer's local time zone. "
        "Do not claim an alarm was set unless the tool result confirms it."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {
                "type": "STRING",
                "description": "plan | add | remember | today | list | upcoming | checkin | complete | reschedule | forget",
            },
            "date": {"type": "STRING", "description": "Date YYYY-MM-DD. For plan, defaults to today; for add/remember, optional. For today, the day to display."},
            "time": {"type": "STRING", "description": "Time HH:MM in local 24-hour time, e.g. 14:30. Required with date to set a timed alarm."},
            "title": {"type": "STRING", "description": "Short event/task/note title, used by add/remember/complete/reschedule/forget."},
            "item_id": {"type": "STRING", "description": "Short ID shown by the planner; safer than title if titles repeat."},
            "kind": {"type": "STRING", "description": "task | event | note"},
            "notes": {"type": "STRING", "description": "Optional brief context or details to remember with an item."},
            "duration_minutes": {"type": "INTEGER", "description": "Optional planned duration."},
            "alarm": {"type": "BOOLEAN", "description": "Whether to set an OS reminder for a timed item; defaults to true when date and time are supplied."},
            "items": {
                "type": "ARRAY",
                "description": "Activities for operation='plan'. One object per activity; include a time whenever a reminder is wanted.",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING"},
                        "date": {"type": "STRING"},
                        "time": {"type": "STRING"},
                        "duration_minutes": {"type": "INTEGER"},
                        "kind": {"type": "STRING"},
                        "notes": {"type": "STRING"},
                        "alarm": {"type": "BOOLEAN"},
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["operation"],
    },
    "handler": daily_planner,
}
