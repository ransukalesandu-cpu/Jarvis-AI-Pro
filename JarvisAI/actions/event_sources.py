"""Built-in event sources for owner rules: new email and file changes.

Both are lightweight pollers registered as condition triggers
(core/triggers.py), so they run inside the existing scheduler and cost nothing
when no rule uses them. They emit events (core/events.py); they never speak
by themselves. The schedule source is emitted when a trigger fires.

* email — every 5 minutes, when a mail provider is configured and an email
  rule exists: each unread message not seen before is emitted once.
* file  — every 30 seconds, for folders named by file rules
  (``action_args.folder`` or a ``path`` condition): new and changed files
  are emitted with {path, name, change}.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from core import events

EMAIL_EVERY = 300.0
FILE_EVERY = 30.0
_state = {"email_at": 0.0, "file_at": 0.0, "seen_mail": set(), "snapshots": {}}


def _rules_for(source: str) -> list[dict]:
    try:
        from core.owner_store import get_owner_store
        return [r for r in get_owner_store().rules.list(source) if r["enabled"]
                and r["source"] == source]
    except Exception:
        return []


def check_email(now: float | None = None) -> None:
    now = time.time() if now is None else now
    if now - _state["email_at"] < EMAIL_EVERY or not _rules_for("email"):
        return None
    _state["email_at"] = now
    from core.mail_calendar import mail_provider
    provider = mail_provider()
    if provider is None:
        return None
    try:
        rows = provider.list_messages("is:unread", 15)
    except Exception as exc:
        print(f"[EventSources] email check failed: {exc}")
        return None
    for row in rows:
        if row["id"] in _state["seen_mail"]:
            continue
        _state["seen_mail"].add(row["id"])
        events.emit("email", {k: row.get(k, "") for k in ("id", "from", "subject", "date", "snippet")})
    return None


def _watched_folders() -> set[str]:
    folders = set()
    for rule in _rules_for("file"):
        folder = (rule.get("action_args") or {}).get("folder") or rule["conditions"].get("path")
        if folder:
            folders.add(os.path.expandvars(os.path.expanduser(str(folder))))
    return folders


def _snapshot(folder: str, limit: int = 5000) -> dict[str, float]:
    out: dict[str, float] = {}
    try:
        for entry in os.scandir(folder):
            if entry.is_file():
                out[entry.path] = entry.stat().st_mtime
                if len(out) >= limit:
                    break
    except OSError:
        pass
    return out


def check_files(now: float | None = None) -> None:
    now = time.time() if now is None else now
    if now - _state["file_at"] < FILE_EVERY:
        return None
    _state["file_at"] = now
    snaps = _state["snapshots"]
    for folder in _watched_folders():
        current = _snapshot(folder)
        previous = snaps.get(folder)
        snaps[folder] = current
        if previous is None:
            continue           # first look only records the baseline
        for path, mtime in current.items():
            change = "created" if path not in previous else (
                "modified" if mtime != previous[path] else "")
            if change:
                events.emit("file", {"path": path, "name": Path(path).name,
                                     "folder": folder, "change": change})
        for path in previous.keys() - current.keys():
            events.emit("file", {"path": path, "name": Path(path).name,
                                 "folder": folder, "change": "deleted"})
    return None


TRIGGERS = [
    {"name": "event_source_email", "check": check_email, "respect_quiet_hours": False,
     "description": "Emit new unread email to owner rules."},
    {"name": "event_source_files", "check": check_files, "respect_quiet_hours": False,
     "description": "Emit file changes in folders that file rules watch."},
]
