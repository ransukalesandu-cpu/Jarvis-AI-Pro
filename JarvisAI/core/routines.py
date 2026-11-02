"""Saved routines: a named sequence of tool calls replayed on request.

"Save this as work mode" stores the tool calls JARVIS made this session since
the last save (or an explicit step list). "Start work mode" replays them in
order through the normal tool registry, so every step is logged like any
other call.

Storage lives behind :class:`RoutineStore` so the backend can change: Module 6
keeps routines in the owner's SQLite store (core/owner_store.py).
"""
from __future__ import annotations

import re
from typing import Callable, Optional

#: Tools that never belong in a saved routine.
NOT_REPLAYABLE = {"routine", "show_recent_actions", "job_status", "start_job",
                  "proactive_triggers", "owner_memory", "shutdown_jarvis"}
_NAME_RE = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    key = _NAME_RE.sub(" ", str(name or "").lower()).strip()
    if not key:
        raise ValueError("a routine needs a name")
    return key


def steps_from_session(calls: list[dict], since_index: int = 0) -> list[dict]:
    """Replayable steps from this session's successful, state-changing calls."""
    steps = []
    for call in calls[since_index:]:
        if call.get("status") != "ok" or call.get("tool") in NOT_REPLAYABLE:
            continue
        if call.get("risk") == "read":
            continue       # looking something up is not part of "the routine"
        steps.append({"tool": call["tool"], "args": dict(call.get("args") or {})})
    return steps


def validate_steps(steps) -> list[dict]:
    if not isinstance(steps, list) or not steps:
        raise ValueError("a routine needs at least one step")
    clean = []
    for row in steps:
        if not isinstance(row, dict) or not str(row.get("tool") or "").strip():
            raise ValueError("each step needs a tool name")
        if row["tool"] in NOT_REPLAYABLE:
            continue
        clean.append({"tool": str(row["tool"]).strip(), "args": dict(row.get("args") or {})})
    if not clean:
        raise ValueError("none of those steps can be replayed")
    return clean


def replay(steps: list[dict], dispatch: Callable[[str, dict], str], *,
           cancel_event=None) -> list[str]:
    """Run each step through ``dispatch(tool, args)``; return one line per step."""
    out = []
    for i, step in enumerate(steps, 1):
        if cancel_event is not None and cancel_event.is_set():
            out.append(f"{i}. stopped on request")
            break
        result = dispatch(step["tool"], dict(step.get("args") or {}))
        out.append(f"{i}. {step['tool']}: {str(result)[:160]}")
    return out


class RoutineStore:
    """Interface: save/get/list/delete routines keyed by normalized name."""

    def save(self, name: str, steps: list[dict], description: str = "") -> None:
        raise NotImplementedError

    def get(self, name: str) -> Optional[dict]:
        raise NotImplementedError

    def list(self) -> list[dict]:
        raise NotImplementedError

    def delete(self, name: str) -> bool:
        raise NotImplementedError


def get_routine_store() -> RoutineStore:
    from core.owner_store import get_owner_store
    return get_owner_store().routines
