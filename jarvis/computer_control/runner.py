"""The one pipeline every computer-control action goes through.

    flag -> emergency stop -> policy -> approval -> audit(start)
         -> dry-run? -> execute (timeout + cancel) -> verify -> audit(end)

:class:`ActionRunner.run_action` is the primitive; tools declared through
:mod:`contract` and the orchestrator's steps both call it, so there is no path
around the policy. Handlers receive an :class:`ActionContext` and must use
``ctx.wait()`` / ``ctx.check()`` instead of ``time.sleep`` so a stop is seen
within ``estop.POLL_S``.

Work runs on a small bounded thread pool (``MAX_WORKERS``) so a hung backend can
never block the Qt thread or the asyncio loop, and the number of outstanding
actions is capped (``MAX_PENDING``) — a runaway plan gets ``busy`` instead of an
ever-growing queue.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from jarvis.computer_control import approval as approval_mod
from jarvis.computer_control import audit, estop, flags
from jarvis.computer_control.policy import ActionPolicy, Level, Origin, PolicyDecision
from jarvis.computer_control.redaction import redact_params, redact_text

MAX_WORKERS = 4
MAX_PENDING = 16
DEFAULT_TIMEOUT_S = 30.0
_THREAD_PREFIX = "cc-action"

STATUSES = ("ok", "failed", "denied", "cancelled", "timeout", "dry_run", "disabled",
            "unverified", "busy", "error")


@dataclass
class ActionOutcome:
    """What a handler returns. ``verified`` None = nothing to verify / not checked."""

    ok: bool = True
    message: str = ""
    data: dict = field(default_factory=dict)
    verified: Optional[bool] = None
    evidence: str = ""

    @classmethod
    def coerce(cls, value: Any) -> "ActionOutcome":
        if isinstance(value, ActionOutcome):
            return value
        if isinstance(value, Mapping):
            data = dict(value)
            return cls(ok=bool(data.pop("ok", True)), message=str(data.pop("message", "")),
                       verified=data.pop("verified", None), evidence=str(data.pop("evidence", "")),
                       data=dict(data.pop("data", data)))
        if value is None:
            return cls(ok=True, message="Done.")
        return cls(ok=True, message=str(value))


@dataclass
class ActionResult:
    action: str
    status: str
    message: str
    level: Level = Level.LOW
    data: dict = field(default_factory=dict)
    verified: Optional[bool] = None
    evidence: str = ""
    duration_ms: int = 0
    approval: str = ""
    #: the call's arguments as finally seen by the handler, redacted (password
    #: fields marked during the call are already masked here)
    args: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "dry_run")

    def speakable(self) -> str:
        text = self.message or self.status
        if self.status == "ok" and self.verified is None and self.level is not Level.LOW:
            text += " (not independently verified)"
        if self.status not in ("ok",):
            text = f"[{self.status}] {text}"
        return text

    def as_dict(self) -> dict:
        return {"action": self.action, "status": self.status, "message": self.message,
                "level": self.level.value, "verified": self.verified, "evidence": self.evidence,
                "duration_ms": self.duration_ms, "data": self.data, "approval": self.approval}


class ActionContext:
    """Handed to every handler: stop checks, waits, dry-run state, progress."""

    def __init__(self, action: str, params: dict, token: estop.StopToken, *,
                 job_id: str = "", progress: Callable[[str], None] | None = None,
                 deadline: float | None = None, level: "Level | None" = None,
                 approval: str = "") -> None:
        self.action = action
        self.params = params
        self.token = token
        self.job_id = job_id
        self._progress = progress
        self.deadline = deadline
        self.timed_out = threading.Event()
        #: what the policy decided and how it was approved, so a handler that re-reads
        #: state can refuse when the state no longer matches what was approved
        self.level = level
        self.approval = approval

    def check(self) -> None:
        if self.timed_out.is_set():
            raise estop.EmergencyStopped("the action timed out")
        self.token.check()

    def wait(self, seconds: float) -> None:
        self.token.wait(seconds)
        self.check()

    def stopped(self) -> bool:
        return self.timed_out.is_set() or self.token.stopped()

    def progress(self, message: str) -> None:
        if self._progress is not None:
            try:
                self._progress(str(message))
            except Exception:
                from jarvis.core import failsoft
                failsoft.suppress("computer_control.runner:progress")


Handler = Callable[[ActionContext], Any]
Verifier = Callable[[ActionContext, ActionOutcome], "tuple[bool, str] | bool"]

_pool_lock = threading.Lock()
_pool: Optional[ThreadPoolExecutor] = None
_pending = 0
_listeners: list[Callable[[dict], None]] = []


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix=_THREAD_PREFIX)
        return _pool


def add_listener(fn: Callable[[dict], None]) -> Callable[[], None]:
    """Hear ``{"phase": "start"|"end", ...}`` for every action (UI status)."""
    _listeners.append(fn)

    def remove() -> None:
        if fn in _listeners:
            _listeners.remove(fn)
    return remove


def _emit(event: dict) -> None:
    for fn in list(_listeners):
        try:
            fn(dict(event))
        except Exception:
            from jarvis.core import failsoft
            failsoft.suppress("computer_control.runner:listener")


class ActionRunner:
    def __init__(self, policy: ActionPolicy | None = None, *,
                 approver: Callable[[], approval_mod.Approver] | None = None,
                 stop: Callable[[], estop.EmergencyStop] | None = None,
                 approval_timeout: float = approval_mod.DEFAULT_TIMEOUT_S) -> None:
        self.policy = policy or ActionPolicy()
        self._approver = approver or approval_mod.get_approver
        self._stop = stop or estop.get
        self.approval_timeout = approval_timeout

    # -- the pipeline --------------------------------------------------------
    def run_action(self, action: str, params: Mapping[str, Any] | None, handler: Handler, *,
                   timeout: float = DEFAULT_TIMEOUT_S, verify: Verifier | None = None,
                   origin: Origin | str = Origin.OWNER, tainted: bool = False,
                   cancel_event: threading.Event | None = None, job_id: str = "",
                   summary: str = "", progress: Callable[[str], None] | None = None,
                   token: estop.StopToken | None = None) -> ActionResult:
        started = time.monotonic()
        params = dict(params or {})
        action = str(action or "").strip().lower()

        def finish(status: str, message: str, level: Level = Level.LOW, **kw) -> ActionResult:
            result = ActionResult(action=action, status=status, message=message, level=level,
                                  duration_ms=int((time.monotonic() - started) * 1000),
                                  args=redact_params(params), **kw)
            audit.record(action, params, result.message, status=status, level=level.value,
                         duration_ms=result.duration_ms, job_id=job_id or None,
                         extra={"verified": result.verified, "approval": result.approval} if
                         status not in ("disabled",) else None)
            _emit({"phase": "end", "action": action, "status": status, "job_id": job_id,
                   "level": level.value, "verified": result.verified, "message": message[:200]})
            return result

        # 1. feature flag
        if not flags.enabled():
            return finish("disabled", flags.describe())

        # 2. emergency stop (taken before policy so a held stop blocks new work)
        token = token or self._stop().token(cancel_event)
        reason = token.reason()
        if reason:
            return finish("cancelled", f"Not started: {reason}.")

        # 3. policy
        decision: PolicyDecision = self.policy.decide(action, params, origin=origin, tainted=tainted)
        if not decision.allowed:
            audit.ledger("cc_policy", action, decision.level.value, "denied", decision.reason)
            return finish("denied", decision.reason, decision.level)

        # 4. approval (HIGH only; native prompt; fail closed)
        approval_note = "not required"
        if decision.needs_approval:
            request = approval_mod.ApprovalRequest(
                action=action, level=decision.level,
                summary=summary or f"JARVIS wants to run {action}",
                reason=decision.reason, details=redact_params(params), task_id=job_id)
            try:
                answer = self._approver().request(request, self.approval_timeout)
            except Exception as exc:
                answer = approval_mod.ApprovalResult(False, "error", f"approval failed: {type(exc).__name__}")
            audit.ledger("cc_approval", action, decision.level.value,
                         "approved" if answer.approved else "denied", f"{answer.method}: {answer.reason}")
            if not answer.approved:
                return finish("denied", f"Not approved: {answer.reason}", decision.level,
                              approval=answer.method)
            approval_note = answer.method
            reason = token.reason()           # the owner may have said stop while the prompt was up
            if reason:
                return finish("cancelled", f"Stopped before starting: {reason}.", decision.level,
                              approval=approval_note)

        # 5. dry run
        if flags.dry_run():
            return finish("dry_run", f"Dry run: would perform {action} ({decision.reason}).",
                          decision.level, approval=approval_note)

        # 6. execute with timeout + cancel
        timeout = max(0.1, float(timeout or DEFAULT_TIMEOUT_S))
        ctx = ActionContext(action, params, token, job_id=job_id, progress=progress,
                            deadline=time.monotonic() + timeout, level=decision.level,
                            approval=approval_note)
        _emit({"phase": "start", "action": action, "job_id": job_id, "level": decision.level.value})
        status, outcome, error = self._execute(handler, ctx, timeout)
        if status != "ok":
            return finish(status, error, decision.level, approval=approval_note)

        # 7. verify
        verified, evidence = outcome.verified, outcome.evidence
        if outcome.ok and verify is not None and not ctx.stopped():
            try:
                answer = verify(ctx, outcome)
                if isinstance(answer, tuple):
                    verified, evidence = bool(answer[0]), str(answer[1])
                else:
                    verified = bool(answer)
            except estop.EmergencyStopped as exc:
                return finish("cancelled", redact_text(f"Stopped during verification: {exc}.", 300),
                              decision.level,
                              approval=approval_note)
            except Exception as exc:
                verified, evidence = False, redact_text(
                    f"verification failed: {type(exc).__name__}: {exc}", 300)
        if not outcome.ok:
            status = "failed"
        elif verified is False:
            status = "unverified"
        message = outcome.message or ("Done." if outcome.ok else "The action failed.")
        if status == "unverified" and evidence:
            message = f"{message} Verification failed: {evidence}"
        return finish(status, message, decision.level, data=outcome.data, verified=verified,
                      evidence=evidence, approval=approval_note)

    def _execute(self, handler: Handler, ctx: ActionContext,
                 timeout: float) -> tuple[str, ActionOutcome, str]:
        global _pending

        def call() -> ActionOutcome:
            ctx.check()
            return ActionOutcome.coerce(handler(ctx))

        if threading.current_thread().name.startswith(_THREAD_PREFIX):
            # Nested call from inside an action: run inline (the outer action
            # already owns a worker and its timeout).
            try:
                return "ok", call(), ""
            except estop.EmergencyStopped as exc:
                return "cancelled", ActionOutcome(ok=False), redact_text(f"Stopped: {exc}.", 300)
            except Exception as exc:
                return "error", ActionOutcome(ok=False), _error_text(ctx.action, exc)

        with _pool_lock:
            if _pending >= MAX_PENDING:
                return "busy", ActionOutcome(ok=False), "Too many computer-control actions are waiting."
            _pending += 1
        try:
            future: Future = _get_pool().submit(call)
        except RuntimeError as exc:
            with _pool_lock:
                _pending -= 1
            return "error", ActionOutcome(ok=False), f"Could not start the action: {exc}"
        future.add_done_callback(_release_slot)

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            try:
                outcome = future.result(timeout=max(0.0, min(estop.POLL_S, remaining)))
                return "ok", outcome, ""
            except estop.EmergencyStopped as exc:
                return "cancelled", ActionOutcome(ok=False), redact_text(f"Stopped: {exc}.", 300)
            except TimeoutError as exc:
                if future.done():          # the handler raised it; not a poll timeout
                    return "error", ActionOutcome(ok=False), _error_text(ctx.action, exc)
            except Exception as exc:
                return "error", ActionOutcome(ok=False), _error_text(ctx.action, exc)
            reason = ctx.token.reason()
            if reason:
                ctx.timed_out.set()            # tell a cooperative handler to stop too
                return "cancelled", ActionOutcome(ok=False), f"Stopped: {reason}."
            if remaining <= 0:
                ctx.timed_out.set()
                return ("timeout", ActionOutcome(ok=False),
                        f"The action did not finish within {timeout:.0f} seconds and was abandoned.")


def _release_slot(_future: Future) -> None:
    global _pending
    with _pool_lock:
        _pending = max(0, _pending - 1)


def _error_text(action: str, exc: BaseException) -> str:
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return redact_text(f"{action} failed: {detail[:200]}", 300)


_default_runner: Optional[ActionRunner] = None


def get_runner() -> ActionRunner:
    global _default_runner
    if _default_runner is None:
        _default_runner = ActionRunner()
    return _default_runner


def set_runner(runner: Optional[ActionRunner]) -> None:
    global _default_runner
    _default_runner = runner
