"""Voice tools for the dedicated worker node (core/nodes, jarvis/node).

* ``node_status`` (read-only): which nodes are configured, whether they answer,
  their coarse load, and the latest remote jobs.
* ``node_test`` (long-running job): send a harmless diagnostic job to the node and
  follow it to the end. It proves routing, progress, cancel and results end to end;
  real work (engineering, background tasks) uses the same path in later phases.

A remote job runs as an ordinary JARVIS background job, so it appears in the Jobs
window, is announced when it ends, and "cancel job …", the HUD stop button and the
stop word all reach the node through ``cancel_event`` / the emergency stop.
"""
from __future__ import annotations

import time

from jarvis.core import failsoft


def _start_registry(_event: str = "", _payload: dict | None = None) -> None:
    """Startup hook: begin heartbeats if any worker node is configured (no-op otherwise)."""
    try:
        from jarvis.core.nodes.jobs import get_remote_jobs
        from jarvis.core.nodes.registry import get_registry
        registry = get_registry()
        if registry.start_background():
            get_remote_jobs()                    # loads saved submissions so they show after a restart
    except Exception:
        failsoft.suppress("actions.node_jobs:start")


def _stop_registry(_event: str = "", _payload: dict | None = None) -> None:
    try:
        from jarvis.core.nodes.registry import reset_registry_for_tests
        reset_registry_for_tests(None)
    except Exception:
        failsoft.suppress("actions.node_jobs:stop")


def _age(ts) -> str:
    if not ts:
        return "never"
    seconds = max(0, int(time.time() - ts))
    return f"{seconds}s ago" if seconds < 120 else f"{seconds // 60} min ago"


def node_status(parameters: dict, **_ctx) -> str:
    from jarvis.core.nodes.jobs import describe, get_remote_jobs
    from jarvis.core.nodes.registry import get_registry
    registry = get_registry()
    registry.start_background()
    if not registry.names():
        return ("No dedicated node is configured. Add one to mcp_servers.json with \"role\": \"worker\" "
                "(see docs/architecture/MULTI_DEVICE.md).")
    action = str((parameters or {}).get("action") or "status").strip().lower()
    if action == "jobs":
        subs = get_remote_jobs().list(10)
        if not subs:
            return "No jobs have been sent to a node yet."
        return "\n".join(f"{s.local_id}: {describe(s)}" for s in subs)
    lines = []
    for state in registry.nodes():
        if state.status == "unknown":
            state = registry.poll(state.name) or state
        row = state.public()
        if state.usable:
            lines.append(f"{row['name']} is {row['status']}: CPU {row['cpu_percent']:.0f}%, "
                         f"{row['ram_available_mb'] / 1000:.1f} GB free, {row['running_jobs']} running, "
                         f"{row['queued_jobs']} queued; last answer {_age(row['last_ok'])}.")
        else:
            lines.append(f"{row['name']} is {row['status']}" + (f": {row['error']}" if row["error"] else "")
                         + f"; last answer {_age(row['last_ok'])}.")
    return "\n".join(lines)


def node_test(parameters: dict, cancel_event=None, **_ctx) -> str:
    from jarvis.computer_control import estop
    from jarvis.core.nodes.jobs import RoutingBlocked, describe, get_remote_jobs
    from jarvis.core.nodes.registry import get_registry
    registry = get_registry()
    registry.start_background()
    for state in registry.nodes():
        if not state.usable:
            registry.poll(state.name)
    p = parameters or {}
    seconds = p.get("seconds", 0)
    try:
        seconds = float(seconds or 0)
    except (TypeError, ValueError):
        return "seconds must be a number from 0 to 600."
    if not 0 <= seconds <= 600:
        return "seconds must be a number from 0 to 600."
    if seconds:
        kind, payload = "diag.sleep", {"seconds": seconds}
    else:
        kind, payload = "diag.echo", {"text": "JARVIS node test"}
    jobs = get_remote_jobs()
    try:
        sub = jobs.submit(kind, "assistant.orchestrate", payload, deadline_s=max(60.0, seconds + 60))
    except RoutingBlocked as exc:
        return f"I didn't send the test: {exc}."
    token = estop.token(cancel_event)
    sub = jobs.follow(sub, stopped=lambda: token.stopped)
    text = describe(sub)
    if sub.state == "succeeded" and kind == "diag.echo" and sub.result:
        text += f" It answered with Python {sub.result.get('python', '?')}."
    return text


TOOLS = [
    {
        "name": "node_status",
        "description": ("Status of the dedicated JARVIS worker node(s): online/offline, load, and recent "
                        "remote jobs. action='status' (default) or 'jobs'."),
        "parameters": {"type": "OBJECT", "properties": {
            "action": {"type": "STRING", "description": "status | jobs"}}},
        "handler": node_status,
        "risk": "read",
        "timeout": 40,
    },
    {
        "name": "node_test",
        "description": ("Send a harmless test job to the dedicated worker node and report the result. "
                        "seconds=0 (default) is a quick echo; 1-600 runs a timed job that reports progress "
                        "and can be cancelled."),
        "parameters": {"type": "OBJECT", "properties": {
            "seconds": {"type": "NUMBER", "description": "0 for an echo, or 1-600 for a timed test"}}},
        "handler": node_test,
        "risk": "read",
        "long_running": True,
        "timeout": 900,
    },
]

# Hook labels default to the handler names (_start_registry / _stop_registry). No "name" key here:
# the Security V2 completeness test reads every {"name", "handler"} dict in actions/ as a tool.
HOOKS = [
    {"event": "startup", "handler": _start_registry},
    {"event": "shutdown", "handler": _stop_registry},
]
