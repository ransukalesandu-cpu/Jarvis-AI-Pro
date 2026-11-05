"""The Host Agent: run a plan, keep the shared context, recover, verify, report.

Lifecycle (master prompt §7): receive → plan → order by dependencies → for
each step: emergency-stop check → resolve references to earlier results →
route to the owning app agent → call the tool through the runner (policy,
approval, audit, timeout) → record in the trace → on a recoverable failure try
the agent's recovery once → final verification of every expectation → report
what actually happened.

Rules that keep it honest and safe:

* a step's result is *verified*, *unverified* or *failed* — never "done because
  it was attempted"; the task succeeds only if every required step is ok and no
  expectation failed;
* recovery runs at most ``max_recoveries`` times per task and never for a
  denied, cancelled or HIGH-risk step (no destructive automatic retries);
* arguments filled in from an earlier step's *result* (window titles, read
  text, page content) are marked ``tainted`` — the policy raises them a level;
* every step's result text is untrusted content for any later model call.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from jarvis.computer_control import estop
from jarvis.computer_control.contract import SpecRegistry
from jarvis.computer_control.orchestrator.agents import AgentRegistry, default_registry
from jarvis.computer_control.orchestrator.plan import Plan, PlanError, Step, build, resolve_refs
from jarvis.computer_control.policy import Level, Origin
from jarvis.computer_control.redaction import redact_params, redact_text
from jarvis.computer_control.runner import ActionResult

NOT_RETRIED = frozenset({"denied", "cancelled", "disabled", "dry_run"})


@dataclass
class TraceEntry:
    step: int
    tool: str
    action: str
    agent: str
    description: str
    status: str
    message: str
    verified: Optional[bool]
    level: str
    duration_ms: int
    recovery: bool = False
    args: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class TaskContext:
    """The shared blackboard every step can read (UFO²'s 'blackboard')."""

    objective: str
    job_id: str = ""
    started: float = field(default_factory=time.monotonic)
    outputs: dict = field(default_factory=dict)       # step index -> {"data":..., "message":...}
    trace: list = field(default_factory=list)
    active_app: str = ""
    current: str = ""
    recoveries: int = 0

    def elapsed(self) -> float:
        return time.monotonic() - self.started


@dataclass
class TaskReport:
    objective: str
    success: bool
    status: str                     # completed | failed | cancelled | denied | planning_failed
    summary: str
    steps_total: int
    steps_ok: int
    steps_verified: int
    recoveries: int
    duration_s: float
    trace: list = field(default_factory=list)
    plan_source: str = ""

    def speakable(self) -> str:
        return self.summary

    def as_dict(self) -> dict:
        data = dict(self.__dict__)
        data["trace"] = [t.as_dict() if hasattr(t, "as_dict") else t for t in self.trace]
        return data


class HostAgent:
    def __init__(self, specs: SpecRegistry, *, agents: AgentRegistry | None = None,
                 max_recoveries: int = 3, progress: Callable[[dict], None] | None = None) -> None:
        self.specs = specs
        self.agents = agents or default_registry()
        self.max_recoveries = max_recoveries
        self._progress = progress

    # ── public ────────────────────────────────────────────────────────────
    def plan_from(self, objective: str, raw_steps: list[dict], source: str = "model") -> Plan:
        from jarvis.computer_control.orchestrator.planner import plannable
        return build(objective, raw_steps, plannable(self.specs), source=source)

    def run(self, plan: Plan, *, cancel_event: threading.Event | None = None,
            job_id: str = "") -> TaskReport:
        ctx = TaskContext(objective=plan.objective, job_id=job_id)
        token = estop.token(cancel_event)
        failed_required: Optional[TraceEntry] = None
        stop_status = ""
        done: set[int] = set()
        for step in plan.steps:
            reason = token.reason()
            if reason:
                stop_status = "cancelled"
                ctx.current = f"stopped: {reason}"
                break
            if any(dep not in done for dep in step.depends_on):
                entry = self._record(ctx, step, "skipped", "skipped: an earlier step did not succeed",
                                     None, "low", 0, "", "")
                if not step.optional:
                    failed_required = failed_required or entry
                continue
            result, entry = self._run_step(ctx, step, cancel_event)
            if result.status in ("cancelled",):
                stop_status = "cancelled"
                break
            if not result.ok:
                result, entry = self._recover(ctx, step, result, entry, cancel_event, token)
            if result.ok and result.verified is not False:
                done.add(step.index)
                ctx.outputs[step.index] = {"data": result.data, "message": result.message,
                                           "status": result.status}
                continue
            if step.optional:
                continue
            failed_required = entry
            if result.status == "denied":
                stop_status = "denied"
            break
        return self._report(plan, ctx, failed_required, stop_status)

    # ── internals ─────────────────────────────────────────────────────────
    def _emit(self, ctx: TaskContext, **event) -> None:
        if self._progress is None:
            return
        try:
            self._progress({"job_id": ctx.job_id, "objective": ctx.objective[:120],
                            "active_app": ctx.active_app, **event})
        except Exception:
            from jarvis.core import failsoft
            failsoft.suppress("computer_control.orchestrator.host:progress")

    def _record(self, ctx: TaskContext, step: Step, status: str, message: str,
                verified: Optional[bool], level: str, duration_ms: int, action: str, agent: str,
                *, recovery: bool = False, args: dict | None = None) -> TraceEntry:
        entry = TraceEntry(step=step.index, tool=step.tool, action=action, agent=agent,
                           description=step.description, status=status,
                           message=redact_text(message, 300), verified=verified, level=level,
                           duration_ms=duration_ms, recovery=recovery,
                           args=redact_params(args if args is not None else step.args))
        ctx.trace.append(entry)
        self._emit(ctx, phase="step", step=step.index, total=None, status=status,
                   message=entry.message[:160], tool=step.tool)
        return entry

    def _expect_args(self, step: Step) -> dict:
        extra = {}
        if step.expect.get("window"):
            extra["expect_window"] = step.expect["window"]
        if step.expect.get("text"):
            extra["expect_text"] = step.expect["text"]
        return extra

    def _run_step(self, ctx: TaskContext, step: Step, cancel_event, *, recovery: bool = False,
                  args_override: dict | None = None) -> tuple[ActionResult, TraceEntry]:
        spec = self.specs.get(step.tool)
        agent = self.agents.for_tool(step.tool)
        if spec is None or agent is None:
            res = ActionResult(step.tool, "error", f"no agent owns tool {step.tool}", Level.HIGH)
            return res, self._record(ctx, step, "error", res.message, None, "high", 0, "", "")
        raw_args = dict(args_override if args_override is not None else step.args)
        args, tainted = resolve_refs(raw_args, ctx.outputs)
        if step.tool == "cc_control" and str(args.get("op")) in ("invoke", "click", "menu"):
            args = {**self._expect_args(step), **args}
        ctx.current = step.description or step.tool
        if args.get("window"):
            ctx.active_app = str(args["window"])
        self._emit(ctx, phase="start", step=step.index, tool=step.tool, message=ctx.current[:160])
        result = spec.call(args, cancel_event=cancel_event, job_id=ctx.job_id,
                           origin=Origin.PLAN.value, tainted=tainted)
        verified = result.verified
        if result.ok and step.expect.get("file"):
            verified, note = _check_file(step.expect)
            if verified is False:
                result.status, result.message = "unverified", f"{result.message} {note}"
            result.verified = verified
        # result.args is redacted after the call, so a field the handler found to be a
        # password is masked in the trace even when the plan did not say so
        entry = self._record(ctx, step, result.status, result.message, verified, result.level.value,
                             result.duration_ms, result.action, agent.name, recovery=recovery,
                             args=result.args or redact_params(args))
        return result, entry

    def _recover(self, ctx: TaskContext, step: Step, result: ActionResult, entry: TraceEntry,
                 cancel_event, token: estop.StopToken) -> tuple[ActionResult, TraceEntry]:
        if (result.status in NOT_RETRIED or result.level is Level.HIGH
                or ctx.recoveries >= self.max_recoveries):
            return result, entry
        agent = self.agents.for_tool(step.tool)
        if agent is None or agent.recover is None:
            return result, entry
        try:
            extra = agent.recover(self, step, result) or []
        except Exception:
            return result, entry
        if not extra:
            return result, entry
        ctx.recoveries += 1
        last_result, last_entry = result, entry
        for item in extra[:3]:
            if token.stopped():                 # the task's own token: a stop since it began
                break
            fake = Step(index=step.index, tool=str(item.get("tool")), args=dict(item.get("args") or {}),
                        description=str(item.get("description") or "recovery"), expect=step.expect,
                        optional=bool(item.get("optional", False)))
            if self.specs.get(fake.tool) is None:
                continue
            last_result, last_entry = self._run_step(ctx, fake, cancel_event, recovery=True)
            if not last_result.ok and not fake.optional:
                break
        return last_result, last_entry

    def _report(self, plan: Plan, ctx: TaskContext, failed: Optional[TraceEntry],
                stop_status: str) -> TaskReport:
        last_by_step: dict[int, TraceEntry] = {}
        for t in ctx.trace:
            last_by_step[t.step] = t
        ok = [t for t in last_by_step.values() if t.status in ("ok", "dry_run")]
        verified = [t for t in last_by_step.values() if t.verified is True]
        all_steps = len(plan.steps)
        if stop_status == "cancelled":
            status, success = "cancelled", False
            summary = f"Stopped after {len(ok)} of {all_steps} steps: {ctx.current}."
        elif failed is not None:
            status = "denied" if stop_status == "denied" or failed.status == "denied" else "failed"
            success = False
            summary = (f"Could not finish '{plan.objective[:80]}': step {failed.step + 1} "
                       f"({failed.description or failed.tool}) {failed.status} — {failed.message}")
        else:
            success = len(ok) == len(last_by_step) and not any(t.verified is False for t in last_by_step.values())
            status = "completed" if success else "failed"
            unchecked = len(ok) - len(verified)
            summary = (f"Done: {plan.objective[:80]} — {len(ok)} of {all_steps} steps succeeded, "
                       f"{len(verified)} verified" + (f", {unchecked} not independently verified"
                                                      if unchecked else "") + ".")
        self._emit(ctx, phase="end", status=status, message=summary[:200])
        return TaskReport(objective=plan.objective, success=success, status=status, summary=summary,
                          steps_total=all_steps, steps_ok=len(ok), steps_verified=len(verified),
                          recoveries=ctx.recoveries, duration_s=round(ctx.elapsed(), 2),
                          trace=list(ctx.trace), plan_source=plan.source)


def _check_file(expect: dict) -> tuple[Optional[bool], str]:
    """``expect.file`` (+ optional ``contains``): the file exists and has the content."""
    from pathlib import Path

    from jarvis.computer_control.policy import protected_path_reason
    path = Path(str(expect.get("file")))
    if protected_path_reason(path, write=False):
        return None, f"{path.name} is protected, so it was not opened to check it."
    try:
        if not path.is_file():
            return False, f"expected file {path.name} does not exist."
        want = expect.get("contains")
        if want:
            text = path.read_text(encoding="utf-8", errors="replace")
            if str(want) not in text:
                return False, f"{path.name} does not contain the expected text."
        return True, f"{path.name} exists" + (" with the expected text" if want else "")
    except OSError as exc:
        return False, f"could not check {path.name}: {exc}"


def plan_or_error(host: HostAgent, objective: str, raw: list[dict], source: str) -> Plan | str:
    try:
        return host.plan_from(objective, raw, source)
    except PlanError as exc:
        return f"The plan was not valid: {exc}"


def summarize_outputs(outputs: dict[int, Any]) -> str:
    return "; ".join(f"{k}: {str(v.get('message', ''))[:80]}" for k, v in sorted(outputs.items()))
