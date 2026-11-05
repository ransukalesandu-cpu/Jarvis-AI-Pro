"""Read-only self-evaluation: what has been failing, reconnecting or misfiring."""
from __future__ import annotations

from jarvis.core import failsoft, live_health


def _agent_line() -> str:
    try:
        from jarvis.agent.integration import get_service
        unfinished = get_service().store.unfinished()
        return f"Autonomous tasks waiting to resume: {len(unfinished)}." if unfinished else "No unfinished autonomous tasks."
    except Exception:
        failsoft.suppress("self_check:agent")
        return "Autonomous task state unavailable."


def _trigger_line() -> str:
    try:
        from jarvis.core.triggers import get_trigger_registry
        broken = [t.name for t in get_trigger_registry().list() if getattr(t, "consecutive_failures", 0)]
        return ("Triggers with recent failures: " + ", ".join(broken[:5]) + ".") if broken else "All triggers healthy."
    except Exception:
        failsoft.suppress("self_check:triggers")
        return "Trigger state unavailable."


def self_check(parameters: dict, **_ctx) -> str:
    parts = [live_health.describe(), _agent_line(), _trigger_line()]
    swallowed = failsoft.count()
    parts.append(f"Handled internal errors this run: {swallowed}." + (f" Top: {failsoft.report(limit=3)}" if swallowed else ""))
    return "\n".join(parts)


TOOL = {
    "name": "self_check",
    "description": ("Report Jarvis's own health: voice connection stability, unfinished autonomous tasks, "
                    "failing triggers and handled internal errors. Use when the owner asks how you are "
                    "running, why you disconnected, or whether anything is broken."),
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": self_check,
    "risk": "read",
}
