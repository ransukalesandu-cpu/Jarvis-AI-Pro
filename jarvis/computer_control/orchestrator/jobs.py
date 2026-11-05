"""Computer-control tasks as JobManager jobs, with live status on the StateBus.

``cc_task`` is a ``long_running`` tool: the existing registry layer
(core/runtime/live_tools.py) starts it as a JobManager job, so the task shows
up in the Background Jobs window and the Island chip, can be cancelled from
there (``JobManager.request_cancel`` sets the job's ``cancel_event``, which
every step checks), and its result is announced through the normal
completion-notice path. Progress is published on the StateBus key
``computer_control`` (core/ui_state.py) — never by blocking the Qt thread.
"""
from __future__ import annotations

import threading
from typing import Optional

from jarvis.computer_control.contract import SpecRegistry, ToolSpec
from jarvis.computer_control.orchestrator.host import HostAgent, TaskReport
from jarvis.computer_control.orchestrator.plan import PlanError
from jarvis.computer_control.orchestrator.planner import ModelPlanner, make_plan
from jarvis.computer_control.runner import ActionContext, ActionOutcome

_last_report: Optional[TaskReport] = None
_lock = threading.Lock()


def publish(event: dict) -> None:
    """Thread-safe: the StateBus queues values set from worker threads."""
    try:
        from jarvis.core import ui_state
        ui_state.bus().set(ui_state.COMPUTER_CONTROL, dict(event))
    except Exception:
        from jarvis.core import failsoft
        failsoft.suppress("computer_control.orchestrator.jobs:publish")


def run_objective(objective: str, specs: SpecRegistry, *, cancel_event: threading.Event | None = None,
                  job_id: str = "", model: ModelPlanner | None = None) -> TaskReport:
    global _last_report
    host = HostAgent(specs, progress=publish)
    publish({"job_id": job_id, "status": "planning", "objective": objective[:120], "message": "planning"})
    try:
        plan = make_plan(objective, specs, model=model)
    except PlanError as exc:
        report = TaskReport(objective=objective, success=False, status="planning_failed",
                            summary=f"I could not plan that: {exc}", steps_total=0, steps_ok=0,
                            steps_verified=0, recoveries=0, duration_s=0.0)
        publish({"job_id": job_id, "status": "failed", "objective": objective[:120],
                 "message": report.summary[:200]})
        return report
    publish({"job_id": job_id, "status": "running", "objective": objective[:120],
             "message": plan.describe()[:200], "steps": len(plan.steps)})
    report = host.run(plan, cancel_event=cancel_event, job_id=job_id)
    with _lock:
        _last_report = report
    return report


def last_report() -> Optional[TaskReport]:
    with _lock:
        return _last_report


def run_detached(ctx: ActionContext, fn):
    """Run ``fn(cancel_event)`` on its own thread (not a runner worker) and wait.

    Steps started from it then go through the runner's pool with their own
    timeouts instead of running inline; the caller's stop (job cancel or the
    emergency stop) is relayed into ``cancel_event``.
    """
    cancel = threading.Event()
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn(cancel)
        except Exception as exc:          # re-raised below, never swallowed
            box["error"] = exc
    worker = threading.Thread(target=run, name="cc-task-host", daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.05)
            if ctx.stopped():
                cancel.set()
        worker.join(5.0)
    finally:
        cancel.set()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def register(reg: SpecRegistry) -> None:
    def handler(ctx: ActionContext) -> ActionOutcome:
        objective = str(ctx.params.get("objective") or "").strip()
        if not objective:
            return ActionOutcome(False, "Say what you want done on the computer.")
        report = run_detached(ctx, lambda cancel: run_objective(objective, reg, cancel_event=cancel,
                                                                job_id=ctx.job_id))
        if report is None:
            return ActionOutcome(False, "The task was stopped before it reported back.")
        return ActionOutcome(report.success, report.summary,
                             data={"report": {k: v for k, v in report.as_dict().items() if k != "trace"},
                                   "trace": [t.as_dict() for t in report.trace][-25:]},
                             verified=report.success and report.steps_verified > 0 or None,
                             evidence=f"{report.steps_verified}/{report.steps_total} steps verified")

    reg.register(ToolSpec(
        id="cc_task", action="task.run",
        description=("Do a multi-step task on the owner's computer (apps, windows, controls): plans it, "
                     "runs every step through the safety policy, verifies results and reports what really "
                     "happened. Runs as a background job that can be cancelled."),
        input_schema={"type": "OBJECT", "properties": {
            "objective": {"type": "STRING", "description": "The owner's request, in their words."}},
            "required": ["objective"]},
        handler=handler, timeout=1800.0, long_running=True))
