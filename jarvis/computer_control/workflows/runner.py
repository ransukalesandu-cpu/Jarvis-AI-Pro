"""Validate and run a saved workflow; record the result for trust tracking."""
from __future__ import annotations

import re
import threading
import time
from typing import Optional

from jarvis.computer_control.contract import SpecRegistry
from jarvis.computer_control.orchestrator.host import HostAgent, TaskReport
from jarvis.computer_control.orchestrator.plan import PlanError
from jarvis.computer_control.workflows.library import (
    PASSWORD_PARAM, LocalStore, Workflow, WorkflowError, cloud_sync,
)

_PARAM = re.compile(r"\{\{param:([a-z_][a-z0-9_]{0,30})\}\}")


def fill_params(value, params: dict):
    if isinstance(value, str):
        return _PARAM.sub(lambda m: str(params.get(m.group(1), m.group(0))), value)
    if isinstance(value, dict):
        return {k: fill_params(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [fill_params(v, params) for v in value]
    return value


def validate(wf: Workflow, specs: SpecRegistry, params: dict | None = None) -> list[str]:
    """Problems that stop the workflow from running now (empty list = ready)."""
    problems: list[str] = []
    params = params or {}
    missing = [p for p in wf.params if p not in params]
    if missing:
        problems.append(f"needs {', '.join(missing)} at run time")
    for i, step in enumerate(wf.steps):
        if specs.get(str(step.get("tool"))) is None:
            problems.append(f"step {i + 1} uses {step.get('tool')}, which no longer exists")
    if problems:
        return problems
    host = HostAgent(specs)
    try:
        host.plan_from(wf.objective, [{"tool": s["tool"], "args": fill_params(s["args"], params),
                                       "description": s.get("description", ""), "expect": s.get("expect") or {}}
                                      for s in wf.steps], source="workflow")
    except PlanError as exc:
        problems.append(f"the saved steps no longer form a valid plan: {exc}")
    return problems


def run_workflow(wf: Workflow, specs: SpecRegistry, store: LocalStore, *, params: dict | None = None,
                 cancel_event: Optional[threading.Event] = None, job_id: str = "") -> TaskReport:
    params = dict(params or {})
    problems = validate(wf, specs, params)
    if problems:
        raise WorkflowError("The workflow cannot run: " + "; ".join(problems))
    host = HostAgent(specs)
    raw = []
    for step in wf.steps:
        args = fill_params(step["args"], params)
        # a value that came from content when the workflow was recorded stays tainted on replay
        raw.append({"tool": step["tool"], "args": args, "description": step.get("description", ""),
                    "expect": step.get("expect") or {}, "tainted": bool(step.get("tainted"))})
    plan = host.plan_from(wf.objective, raw, source="workflow")
    started = time.monotonic()
    report = host.run(plan, cancel_event=cancel_event, job_id=job_id)
    record_result(wf, report, store, time.monotonic() - started)
    return report


def record_result(wf: Workflow, report: TaskReport, store: LocalStore, duration_s: float) -> Workflow:
    if report.status == "cancelled":
        wf.last_result = "cancelled"
    elif report.success:
        wf.successes += 1
        wf.streak += 1
        wf.last_result = "verified success"
    else:
        wf.failures += 1
        wf.streak = 0                    # one failure: back to supervised
        wf.last_result = f"failed: {report.summary[:160]}"
    wf.last_run = time.time()
    wf.last_duration_s = round(duration_s, 2)
    store.put(wf, new_version=False)
    cloud_sync(wf)
    return wf


__all__ = ["validate", "run_workflow", "record_result", "fill_params", "PASSWORD_PARAM"]
