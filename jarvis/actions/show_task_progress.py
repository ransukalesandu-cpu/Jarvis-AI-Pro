"""'Show the task progress window' — bring back the Task Flow window or page (core/task_flow.py)."""
from __future__ import annotations

from jarvis.core import task_flow


def show_task_progress(parameters: dict, **_ctx) -> str:
    p = parameters or {}
    view = str(p.get("view") or "window").strip().lower()
    if view not in task_flow.VIEWS:
        view = "window"
    task_flow.tracker().request_view(view)
    if view == "hide":
        return "Task progress window hidden."
    summary = task_flow.tracker().describe_latest()
    where = "page" if view == "page" else "window"
    return f"Showing the task progress {where}. {summary}"


TOOL = {
    "name": "show_task_progress",
    "description": (
        "Show or hide the Task Progress window that draws JARVIS's current or most recent task as a "
        "node flow (one node per step), or open the full Task Progress page with the task history. "
        "Use for 'show the task progress window', 'show task progress', 'what are you doing, show me', "
        "'open the task progress page', 'hide the task window'. Works only in the web UI."),
    "parameters": {"type": "OBJECT", "properties": {
        "view": {"type": "STRING", "description": "window (default) | page | hide"},
    }},
    "handler": show_task_progress,
    "risk": "read",
    "timeout": 5,
}
