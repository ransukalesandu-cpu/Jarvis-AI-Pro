"""Live "what is JARVIS doing right now" flows for the Task Flow window and page.

A *flow* is one thing the owner asked for, shown as a brain node with one node
per step. Two sources feed it, both without changing how they work:

* live tool calls (``core/runtime/live_tools._execute_tool``): consecutive calls
  in one exchange are grouped into one flow, one step per call;
* autonomous tasks (``agent.integration.AgentService``): one flow per task, one
  step per planned step, kept in sync with the live ``Task`` object.

The owner's own words become the flow title when they are known (typed or
transcribed ``You: …`` lines, see ``note_command``); otherwise the first tool
names it. Only short, redacted text is kept: tool names, step titles and the
first few words of a result. Arguments are never stored.

No Qt. Thread-safe: tool calls finish on worker threads. Listeners are called
outside the lock and a broken listener never breaks a tool call.
"""
from __future__ import annotations

import itertools
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

MAX_FLOWS = 20
MAX_STEPS = 24
GROUP_GAP_S = 4.0          # a tool call this soon after the last one joins the same flow
TITLE_WINDOW_S = 20.0      # the owner's words name a flow that started this recently
TITLE_CHARS = 120
LABEL_CHARS = 80
DETAIL_CHARS = 100
TOOL_CHARS = 48
VIEWS = ("window", "page", "hide")

# UI-only tools: showing the task window is not itself a task worth a window.
HIDDEN_TOOLS = frozenset({"show_task_progress"})

FLOW_STATES = ("running", "done", "failed", "cancelled")
FLOW_SOURCES = ("command", "agent")
STEP_STATES = ("pending", "running", "done", "error", "skipped")

Listener = Callable[[str, Any], None]          # ("flow", snapshot) | ("view", "window"/"page"/"hide")


def _scrub(text: Any, limit: int) -> str:
    try:
        from jarvis.webui.redact import scrub
        text = scrub(str(text or ""))
    except Exception:
        text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def pretty_tool(name: str) -> str:
    """'open_app' -> 'Open app', 'cc.click' -> 'Cc click'."""
    words = str(name or "").replace(".", " ").replace("_", " ").split()
    text = " ".join(words) or "Tool"
    return (text[:1].upper() + text[1:])[:LABEL_CHARS]


_TOOL_STATUS = {"ok": "done", "job_started": "done", "error": "error", "timeout": "error",
                "cancelled": "skipped"}
_STEP_STATE = {"pending": "pending", "running": "running", "verifying": "running", "completed": "done",
               "failed": "error", "blocked": "error", "skipped": "skipped"}
_TASK_STATE = {"completed": "done", "failed": "failed", "cancelled": "cancelled"}


def _ms(seconds: float | None) -> int | None:
    return None if seconds is None else int(float(seconds) * 1000)


class FlowTracker:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.RLock()
        self._flows: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._tokens: dict[str, tuple[str, int]] = {}      # tool-call token -> (flow id, step index)
        self._open: str | None = None                      # the tool flow new calls may join
        self._pending_title: tuple[str, float] | None = None
        self._listeners: list[Listener] = []
        self._ids = itertools.count(1)

    # ── listeners ───────────────────────────────────────────────────────
    def subscribe(self, fn: Listener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._listeners:
                    self._listeners.remove(fn)
        return unsubscribe

    def _notify(self, kind: str, payload: Any) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(kind, payload)
            except Exception:
                from jarvis.core import failsoft
                failsoft.suppress("task_flow:listener")

    # ── live tool calls ─────────────────────────────────────────────────
    def tool_started(self, name: str) -> str | None:
        """Record a tool call starting. Returns a token for ``tool_finished`` (None if not tracked)."""
        name = str(name or "").strip()
        if not name or name in HIDDEN_TOOLS:
            return None
        now = self._clock()
        with self._lock:
            flow = self._flows.get(self._open or "")
            if flow is None or not self._joinable(flow, now):
                flow = self._new_flow(now)
            if len(flow["steps"]) >= MAX_STEPS:
                return None
            flow["steps"].append({
                "id": f"s{len(flow['steps']) + 1}", "tool": name[:TOOL_CHARS], "label": pretty_tool(name),
                "status": "running", "detail": "working…", "startedAt": _ms(now), "finishedAt": None,
            })
            flow["state"], flow["finishedAt"], flow["last"] = "running", None, now
            if flow["generic"] and len(flow["steps"]) == 1:
                flow["title"] = pretty_tool(name)
            token = f"t{next(self._ids)}"
            self._tokens[token] = (flow["id"], len(flow["steps"]) - 1)
            snap = self._snapshot(flow)
        self._notify("flow", snap)
        return token

    def tool_finished(self, token: str | None, status: str, result: Any = "") -> None:
        if not token:
            return
        now = self._clock()
        with self._lock:
            ref = self._tokens.pop(token, None)
            flow = self._flows.get(ref[0]) if ref else None
            if flow is None:
                return
            step = flow["steps"][ref[1]]
            step["status"] = _TOOL_STATUS.get(str(status), "done")
            step["finishedAt"] = _ms(now)
            if status == "job_started":
                step["detail"] = "running in the background"
            else:
                step["detail"] = _scrub(result, DETAIL_CHARS) or {"done": "done", "error": "failed",
                                                                   "skipped": "stopped"}[step["status"]]
            flow["last"] = now
            if not any(s["status"] == "running" for s in flow["steps"]):
                flow["state"] = "failed" if step["status"] == "error" else (
                    "cancelled" if step["status"] == "skipped" else "done")
                flow["finishedAt"] = _ms(now)
            snap = self._snapshot(flow)
        self._notify("flow", snap)

    def _joinable(self, flow: dict, now: float) -> bool:
        if flow["source"] == "agent":
            return False
        running = any(s["status"] == "running" for s in flow["steps"])
        return running or (now - flow["last"]) <= GROUP_GAP_S

    def _new_flow(self, now: float) -> dict:
        title, source, generic = "Working…", "command", True
        pending = self._pending_title
        if pending and now - pending[1] <= TITLE_WINDOW_S:
            title, generic = pending[0], False
        self._pending_title = None
        flow = {"id": f"f{int(now * 1000)}-{next(self._ids)}", "title": title, "source": source,
                "state": "running", "startedAt": _ms(now), "finishedAt": None, "steps": [],
                "generic": generic, "last": now}
        self._store(flow)
        self._open = flow["id"]
        return flow

    # ── the owner's words ───────────────────────────────────────────────
    def note_command(self, text: str) -> None:
        """Name the current (or next) tool flow after what the owner said or typed."""
        title = _scrub(text, TITLE_CHARS)
        if not title:
            return
        now = self._clock()
        snap = None
        with self._lock:
            flow = self._flows.get(self._open or "")
            if flow is not None and flow["generic"] and now - flow["startedAt"] / 1000 <= TITLE_WINDOW_S:
                flow["title"], flow["generic"] = title, False
                snap = self._snapshot(flow)
            else:
                self._pending_title = (title, now)
        if snap:
            self._notify("flow", snap)

    # ── autonomous tasks ────────────────────────────────────────────────
    def agent_task(self, task: Any) -> None:
        """Mirror one autonomous ``agent.models.Task`` (called on its events and on a light poll)."""
        if task is None:
            return
        try:
            tid = str(task.id)
            state_value = getattr(task.state, "value", str(task.state))
            steps = []
            for i, st in enumerate(list(task.steps)[:MAX_STEPS]):
                status = _STEP_STATE.get(getattr(st.state, "value", str(st.state)), "pending")
                kind = getattr(getattr(st, "kind", None), "value", "") or "step"
                detail = st.blocked_reason or st.last_error or st.output or ""
                steps.append({
                    "id": f"s{i + 1}", "tool": str(st.tool or kind)[:TOOL_CHARS],
                    "label": _scrub(st.title, LABEL_CHARS) or pretty_tool(kind),
                    "status": status,
                    "detail": _scrub(detail, DETAIL_CHARS) or {"pending": "queued", "running": "working…",
                                                                "done": "done", "error": "failed",
                                                                "skipped": "skipped"}[status],
                    "startedAt": _ms(st.started_at), "finishedAt": _ms(st.finished_at),
                })
            flow = {"id": f"a-{tid}"[:40], "title": _scrub(task.objective, TITLE_CHARS) or "Autonomous task",
                    "source": "agent", "state": _TASK_STATE.get(state_value, "running"),
                    "startedAt": _ms(task.started_at or task.created_at) or _ms(self._clock()),
                    "finishedAt": _ms(task.finished_at) if state_value in _TASK_STATE else None,
                    "steps": steps, "generic": False, "last": self._clock()}
        except (AttributeError, TypeError, ValueError):
            return
        with self._lock:
            old = self._flows.get(flow["id"])
            if old is not None and self._public(old) == self._public(flow):
                return                                      # poll with no change: stay quiet
            self._store(flow)
            snap = self._snapshot(flow)
        self._notify("flow", snap)

    # ── view requests (voice tool / palette) ────────────────────────────
    def request_view(self, view: str) -> bool:
        if view not in VIEWS:
            return False
        self._notify("view", view)
        return True

    # ── reading ─────────────────────────────────────────────────────────
    def flows(self) -> list[dict]:
        with self._lock:
            return [self._snapshot(f) for f in self._flows.values()]

    def latest(self) -> dict | None:
        with self._lock:
            return self._snapshot(next(reversed(self._flows.values()))) if self._flows else None

    def describe_latest(self) -> str:
        flow = self.latest()
        if flow is None:
            return "I haven't worked on any task yet this session."
        done = sum(1 for s in flow["steps"] if s["status"] == "done")
        return f"{flow['title']}: {flow['state']}, {done} of {len(flow['steps'])} steps done."

    def clear(self) -> None:
        with self._lock:
            self._flows.clear()
            self._tokens.clear()
            self._open = None
            self._pending_title = None

    # ── internals ───────────────────────────────────────────────────────
    def _store(self, flow: dict) -> None:
        self._flows[flow["id"]] = flow
        self._flows.move_to_end(flow["id"])
        while len(self._flows) > MAX_FLOWS:
            old_id, _ = self._flows.popitem(last=False)
            if old_id == self._open:
                self._open = None

    @staticmethod
    def _public(flow: dict) -> dict:
        return {k: flow[k] for k in ("id", "title", "source", "state", "startedAt", "finishedAt")} | {
            "steps": [dict(s) for s in flow["steps"]]}

    def _snapshot(self, flow: dict) -> dict:
        return self._public(flow)


_TRACKER: FlowTracker | None = None
_TRACKER_LOCK = threading.Lock()


def tracker() -> FlowTracker:
    global _TRACKER
    with _TRACKER_LOCK:
        if _TRACKER is None:
            _TRACKER = FlowTracker()
        return _TRACKER


def reset_for_tests(new: FlowTracker | None = None) -> None:
    global _TRACKER
    with _TRACKER_LOCK:
        _TRACKER = new
