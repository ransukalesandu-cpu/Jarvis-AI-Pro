"""Stage trace for planned tasks: what was offered, what was chosen, what came back.

Three stages per task, kept in a small in-memory ring (newest 10 tasks) so
``self_check`` can read the last one back, and also persisted by the runner as
task events (``planned`` / ``step_result``) in the normal task store:

    plan       -> objective, planner source, warnings
    selection  -> the tools offered to the planner and the tools it chose
    results    -> one line per step: state, tool, short outcome

Nothing here decides anything or changes a plan; it only records. Text is
clipped and passed through the same redaction the task store uses.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Iterable

MAX_TASKS = 10
_MAX_STEPS = 24
_TEXT = 140

_lock = threading.Lock()
_traces: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


def _clip(value: Any, limit: int = _TEXT) -> str:
    try:
        from jarvis.agent.store import redact
        return str(redact(str(value or ""), limit))
    except Exception:
        text = " ".join(str(value or "").split())
        return text if len(text) <= limit else text[: limit - 1] + "…"


def clear() -> None:
    with _lock:
        _traces.clear()


def record_plan(task_id: str, objective: str, *, source: str = "", offered: Iterable[str] = (),
                steps: Iterable[Any] = (), warnings: Iterable[str] = ()) -> None:
    """Stage 1+2: the plan, the tools offered, the tools chosen."""
    rows = []
    for step in list(steps)[:_MAX_STEPS]:
        kind = getattr(getattr(step, "kind", None), "value", str(getattr(step, "kind", "")))
        rows.append({
            "title": _clip(getattr(step, "title", ""), 80),
            "kind": kind,
            "tool": str(getattr(step, "tool", "") or ""),
            "depends_on": list(getattr(step, "depends_on", []) or []),
            "state": "pending",
            "result": "",
        })
    with _lock:
        _traces[str(task_id)] = {
            "objective": _clip(objective),
            "source": str(source or ""),
            "offered": [str(n) for n in offered][:60],
            "warnings": [_clip(w) for w in warnings][:10],
            "steps": rows,
        }
        _traces.move_to_end(str(task_id))
        while len(_traces) > MAX_TASKS:
            _traces.popitem(last=False)


def record_result(task_id: str, index: int, *, state: str, result: str = "") -> None:
    """Stage 3: how one step ended."""
    with _lock:
        trace = _traces.get(str(task_id))
        if trace is None or not 0 <= int(index) < len(trace["steps"]):
            return
        row = trace["steps"][int(index)]
        row["state"] = str(state)
        row["result"] = _clip(result, 100)


def last() -> tuple[str, dict[str, Any]] | None:
    with _lock:
        if not _traces:
            return None
        task_id, trace = next(reversed(_traces.items()))
        return task_id, {**trace, "steps": [dict(s) for s in trace["steps"]]}


def describe_last() -> str:
    """A short readable report of the newest traced task ('' when there is none)."""
    found = last()
    if found is None:
        return ""
    task_id, trace = found
    chosen = [s["tool"] for s in trace["steps"] if s["tool"]]
    lines = [f"Last planned task {task_id} ({trace['source'] or 'unknown planner'}): {trace['objective']}"]
    if trace["offered"]:
        lines.append(f"Tools offered to the planner: {len(trace['offered'])}; chosen: "
                     + (", ".join(dict.fromkeys(chosen)) if chosen else "none") + ".")
    if trace["warnings"]:
        lines.append(f"Planner dropped or changed {len(trace['warnings'])} item(s): {trace['warnings'][0]}")
    for i, step in enumerate(trace["steps"]):
        label = f"{step['kind']}:{step['tool']}" if step["tool"] else step["kind"]
        tail = f" - {step['result']}" if step["result"] else ""
        lines.append(f"  {i + 1}. [{step['state']}] {step['title']} ({label}){tail}")
    return "\n".join(lines)
