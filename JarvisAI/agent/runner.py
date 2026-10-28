"""The autonomous worker: plan → act → verify → recover → continue.

One :class:`TaskRunner` owns at most one active task and a bounded queue. It is
safe to drive from the app (a background thread) and from tests (a synchronous
``run_task`` call), because all the moving parts — clock, sleep, executor,
planner, store, bus, approval — are injected.

Guarantees, all covered by tests:

* A task never exceeds its step, attempt, retry and wall-clock budgets.
* ``pause`` blocks between steps without busy-waiting; ``resume`` continues from
  the persisted cursor; ``cancel`` stops before the next action and inside a
  running command.
* Every step is checkpointed, so a crash or app restart resumes the unfinished
  task instead of starting over.
* A failing step is retried only when the failure is transient, and the same
  failure three times in a row is treated as a loop, not as progress.
* Blockers (missing credential, no display, denied approval) are reported with
  their real reason and the runner continues with independent steps.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent import policy as policy_module
from agent.events import EventBus, event_from_task
from agent.executor import ExecutionContext, StepExecutor, StepResult
from agent.models import (
    StepState,
    Task,
    TaskReport,
    TaskState,
    TaskStep,
)
from agent.planner import PlanError, TaskPlanner
from agent.store import TaskStore, redact


@dataclass
class RunnerConfig:
    max_runtime_s: float = 1800.0
    retry_budget: int = 12
    retry_backoff_s: float = 2.0
    max_retry_backoff_s: float = 30.0
    progress_min_interval_s: float = 2.0
    loop_detection_repeats: int = 3
    max_steps: int = 16
    resume_unfinished: bool = True


class TaskRunner:
    """Execute planned tasks with bounded retries, persistence and cancellation."""

    def __init__(
        self,
        *,
        store: TaskStore | None = None,
        planner: TaskPlanner | None = None,
        executor: StepExecutor | None = None,
        policy_engine: policy_module.PolicyEngine | None = None,
        bus: EventBus | None = None,
        config: RunnerConfig | None = None,
        workspace: Path | str | None = None,
        vision: Any | None = None,
        computer: Any | None = None,
        request_approval: Callable[[TaskStep, policy_module.Decision], bool] | None = None,
        on_milestone: Callable[[str], None] | None = None,
        logger: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wait_cancel: Callable[[float], bool] | None = None,
    ):
        self.workspace = Path(workspace).resolve() if workspace else _default_workspace()
        self.store = store or TaskStore()
        self.bus = bus or EventBus()
        self.config = config or RunnerConfig()
        self.engine = policy_engine or policy_module.PolicyEngine(
            policy_module.ExecutionPolicy(
                workspace_root=str(self.workspace),
                max_runtime_s=self.config.max_runtime_s,
                retry_budget=self.config.retry_budget,
            )
        )
        self.planner = planner or TaskPlanner(workspace=self.workspace,
                                              max_steps=self.config.max_steps)
        self.executor = executor or StepExecutor(engine=self.engine)
        self.vision = vision
        self.computer = computer
        self._approval = request_approval
        self._milestone = on_milestone
        self._logger = logger or (lambda message: None)
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        # Injectable so tests can assert the backoff schedule without waiting it
        # out. The default returns True when the wait was interrupted by cancel.
        self._wait_cancel = wait_cancel

        self._cancel = threading.Event()
        self._cancel_for: str | None = None
        self._pause = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._active: Task | None = None
        self._last_emit = 0.0
        self._failure_signatures: list[str] = []
        self._queue: list[str] = []
        # Live task objects, so the caller that called submit()/start() sees the
        # same instance the worker is updating (the store keeps the durable copy).
        self._tasks: dict[str, Task] = {}

    # ── public API ────────────────────────────────────────────────────────
    @property
    def active_task(self) -> Task | None:
        return self._active

    def submit(self, objective: str, *, criteria: list[str] | None = None,
               source: str = "voice") -> Task:
        """Create a pending task and make it durable before anything runs."""
        text = str(objective or "").strip()
        if not text:
            raise ValueError("An autonomous task needs an objective.")
        task = Task(
            objective=text[:1200],
            criteria=[str(item) for item in (criteria or [])][:6],
            source=source,
            max_runtime_s=float(self.config.max_runtime_s),
            retry_budget=int(self.config.retry_budget),
        )
        task.transition(TaskState.PLANNING, "queued")
        self.store.save(task)
        self.store.append_event(task.id, {"kind": "submitted", "objective": task.objective})
        with self._lock:
            self._remember(task)
            self._queue.append(task.id)
        self._emit("queued", task, message=f"Queued: {task.objective[:100]}")
        return task

    def start(self, objective: str, *, criteria: list[str] | None = None,
              source: str = "voice") -> Task:
        """Submit and start the background worker. Returns immediately."""
        task = self.submit(objective, criteria=criteria, source=source)
        self._ensure_worker()
        return task

    def resume_task(self, task_id: str, *, background: bool = True) -> Task:
        """Load an interrupted task and queue it to continue from its cursor."""
        task = self.store.load(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} was not found.")
        if task.state.terminal:
            raise ValueError(f"Task {task_id} already finished ({task.state.value}).")
        if task.state in (TaskState.PAUSED, TaskState.WAITING):
            task.state = TaskState.PENDING
        if task.state is TaskState.PENDING:
            task.transition(TaskState.RUNNING, "resumed")
        else:
            task.note(f"resumed from {task.state.value}")
        task.resume_count += 1
        self.store.save(task)
        self.store.append_event(task.id, {"kind": "resumed", "cursor": task.cursor})
        with self._lock:
            self._remember(task)
        if background:
            with self._lock:
                if task.id not in self._queue:
                    self._queue.insert(0, task.id)
            self._ensure_worker()
        return task

    def pause(self) -> bool:
        task = self._active
        if task is None or task.state.terminal:
            return False
        self._pause.set()
        self._resume.clear()
        self._emit("paused", task, message="Paused by the owner.")
        self._announce("Pausing the task.")
        return True

    def resume(self) -> bool:
        if not self._pause.is_set() and self._active is None:
            return False
        self._pause.clear()
        self._resume.set()
        task = self._active
        if task is not None and not task.state.terminal:
            self._emit("resumed", task, message="Continuing the task.")
            self._announce("Continuing.")
        return True

    def cancel(self, reason: str = "Stopped by the owner.") -> bool:
        task = self._active
        with self._lock:
            # Cancel may arrive before the worker picks the task up.
            target = task.id if task is not None else (self._queue[0] if self._queue else None)
        self._cancel_for = target
        self._cancel.set()
        self._resume.set()
        with self._lock:
            queued = bool(self._queue)
        if task is not None:
            task.cancel_reason = str(reason)
            task.note(f"cancel requested: {reason}")
            self.store.append_event(task.id, {"kind": "cancel_requested", "reason": reason})
            self._announce("Stopping.")
        with self._lock:
            self._queue.clear()
        return task is not None or queued

    def wait(self, timeout: float | None = None) -> Task | None:
        """Block until the worker stops (tests and shutdown use this)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return self._active

    def shutdown(self) -> None:
        self.cancel("JARVIS is shutting down.")
        self.wait(timeout=10.0)

    def status(self) -> dict[str, Any]:
        with self._lock:
            queued = list(self._queue)
        task = self._active
        if task is not None and task.state.terminal:
            task = None  # a finished task is history, not "active"
        return {
            "active": task.to_dict() if task else None,
            "queued": queued,
            "paused": self._pause.is_set(),
            "cancel_requested": self._cancel.is_set(),
            "vision": bool(self.vision is not None),
            "desktop_control": bool(self.computer is not None),
        }

    # ── worker ------------------------------------------------------------
    def _remember(self, task: Task) -> None:
        """Track a live task object, keeping the in-memory set small."""
        self._tasks[task.id] = task
        if len(self._tasks) > 8:
            for stale in [item.id for item in self._tasks.values()
                          if item.state.terminal and item.id != task.id][:4]:
                self._tasks.pop(stale, None)

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker_loop, name="jarvis-agent-worker", daemon=True
            )
            self._thread.start()

    def _worker_loop(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._thread = None
                    return
                task_id = self._queue.pop(0)
            with self._lock:
                task = self._tasks.get(task_id)
            if task is None:
                task = self.store.load(task_id)
            if task is None:
                continue
            try:
                self.run_task(task)
            except Exception as exc:  # never let one task kill the worker
                self._logger(f"Agent worker: task {task_id} crashed: {exc}")
                try:
                    task.transition(TaskState.FAILED, f"engine error: {exc}")
                    task.blockers.append(f"The task engine crashed: {redact(exc, 200)}")
                    self._finalize(task)
                except Exception:
                    pass
            if self._cancel.is_set():
                with self._lock:
                    self._queue.clear()

    # ── synchronous execution --------------------------------------------
    def run_task(self, task: Task) -> Task:
        """Execute one task to a terminal or waiting state. Blocking."""
        with self._lock:
            self._active = task
        # A cancel request belongs to one task; it must never pre-cancel the next.
        if self._cancel.is_set() and self._cancel_for != task.id:
            self._cancel.clear()
        started_monotonic = self._monotonic()
        self._failure_signatures = []
        task.max_runtime_s = float(task.max_runtime_s or self.config.max_runtime_s)
        task.retry_budget = int(task.retry_budget or self.config.retry_budget)
        if task.started_at is None:
            task.started_at = self._clock()

        if task.state is TaskState.PENDING:
            # A caller may hand over a task that already carries a plan; it still
            # has to pass through PLANNING so the state machine stays honest.
            task.transition(TaskState.PLANNING, "worker started")

        if not task.steps:
            self._plan(task)
            if task.state.terminal or not task.steps:
                self._finalize(task, started_monotonic)
                with self._lock:
                    self._active = None
                return task

        if task.state in (TaskState.PENDING, TaskState.PLANNING):
            task.transition(TaskState.RUNNING, "worker started")
        elif task.state is TaskState.PAUSED:
            task.transition(TaskState.RUNNING, "resumed")
        self.store.save(task)
        self._emit("started", task, message="Working on it.")

        while True:
            if self._cancel.is_set():
                self._close_cancelled(task)
                break
            if task.deadline_exceeded(self._clock()):
                task.blockers.append(
                    f"Stopped after the {task.max_runtime_s:.0f}s task deadline."
                )
                task.transition(TaskState.FAILED, "deadline exceeded")
                break
            if task.state is TaskState.PAUSED or self._pause.is_set():
                self._enter_pause(task)
                continue

            index = task.next_pending_index()
            if index is None:
                break
            task.cursor = index
            step = task.steps[index]

            blocked_dependency = self._unmet_dependency(task, step)
            if blocked_dependency is not None:
                step.mark(StepState.SKIPPED, error=f"dependency {blocked_dependency} failed")
                self.store.append_event(task.id, {
                    "kind": "step_skipped", "index": index, "step": step.title,
                    "reason": f"dependency {blocked_dependency} did not complete",
                })
                continue

            self._emit("step_started", task, message=step.title,
                       step={"index": index, "title": step.title,
                             "kind": step.kind.value})
            ctx = self._context(task)
            outcome = self._run_with_retries(task, step, ctx)
            self._record(task, step, outcome)
            if outcome.blocked:
                task.blockers.append(f"{step.title}: {outcome.blocked_reason}")
                self._emit("blocked", task, message=outcome.blocked_reason,
                           step={"index": index, "title": step.title})
                self._announce(f"I'm blocked on {step.title}. {outcome.blocked_reason}")
            elif outcome.ok:
                self._emit("step_done", task, message=step.title,
                           step={"index": index, "title": step.title,
                                 "kind": step.kind.value})
            else:
                self._emit("step_failed", task, message=outcome.error,
                           step={"index": index, "title": step.title})
                if outcome.cancelled:
                    self._close_cancelled(task)
                    break
                if self._loop_detected(step, outcome):
                    task.blockers.append(
                        f"Loop detected: '{step.title}' failed the same way "
                        f"{self.config.loop_detection_repeats} times."
                    )
                    task.transition(TaskState.FAILED, "repeated identical failure")
                    break

        self._finalize(task, started_monotonic)
        with self._lock:
            self._active = None
        return task

    # ── internals ---------------------------------------------------------
    def _plan(self, task: Task) -> None:
        self._emit("planning", task, message="Working out the plan.")
        try:
            plan = self.planner.plan(task.objective, task.criteria or None)
        except PlanError as exc:
            task.blockers.append(str(exc))
            task.transition(TaskState.FAILED, "planning failed")
            return
        except Exception as exc:
            task.blockers.append(f"Planning failed: {redact(exc, 200)}")
            task.transition(TaskState.FAILED, "planning failed")
            return
        task.set_plan(plan.steps, plan.criteria or task.criteria)
        task.note(f"plan from {plan.source}: {len(plan.steps)} steps")
        for warning in plan.warnings:
            task.note(warning)
        self.store.save(task)
        self.store.append_event(task.id, {
            "kind": "planned",
            "source": plan.source,
            "steps": [{"title": step.title, "kind": step.kind.value}
                      for step in plan.steps],
            "warnings": plan.warnings,
        })
        self._emit("planned", task, message=plan.rationale or "Plan ready.",
                   plan={"source": plan.source, "warnings": plan.warnings})
        if plan.source == "heuristic" and any(
            "BLOCKED unless" in (step.detail or "") for step in plan.steps
        ):
            self._announce(
                "I can inspect and test the project, but I need a planning model "
                "configured before I change code."
            )

    def _context(self, task: Task) -> ExecutionContext:
        return ExecutionContext(
            task=task,
            workspace=self.workspace,
            cancel=self._cancel,
            pause=self._pause,
            logger=self._logger,
            vision=self.vision,
            computer=self.computer,
            policy=self.engine.policy,
            request_approval=self._approval,
            sleep=self._sleep,
            clock=self._monotonic,
            emit=lambda kind, data: self.store.append_event(task.id, {"kind": kind, **data}),
        )

    def _run_with_retries(self, task: Task, step: TaskStep,
                          ctx: ExecutionContext) -> StepResult:
        attempt = 0
        while True:
            attempt += 1
            step.mark_running()
            self.store.save(task)
            result = self.executor.execute(step, ctx)
            if result.cancelled:
                # A step interrupted by the owner is not a failure: recording it
                # as one would show a red ✘ and inflate the retry/failure counts
                # in the report of a task the user simply stopped.
                step.mark(StepState.SKIPPED, error="Stopped by the owner.")
                return result
            if result.ok or result.blocked or not result.retryable:
                return result
            if attempt > step.max_retries:
                return result
            if task.retries_used >= task.retry_budget:
                result.blocked_reason = (
                    result.error + " (retry budget exhausted)"
                    if result.error else "Retry budget exhausted."
                )
                result.blocked = True
                return result
            task.retries_used += 1
            delay = min(
                self.config.max_retry_backoff_s,
                self.config.retry_backoff_s * (2 ** (attempt - 1)),
            )
            self.store.append_event(task.id, {
                "kind": "step_retry", "index": step.index, "attempt": attempt,
                "delay_s": delay, "error": result.error,
            })
            self._emit("retrying", task,
                       message=f"Retrying {step.title} in {delay:.0f}s.")
            # Interruptible wait: cancellation must not sit out the backoff.
            if self._backoff(delay):
                return StepResult.stopped()

    def _backoff(self, delay: float) -> bool:
        """Wait out a retry delay. Returns True when cancelled."""
        if delay <= 0:
            return self._cancel.is_set()
        if self._wait_cancel is not None:
            return bool(self._wait_cancel(delay))
        return self._cancel.wait(delay)

    def _record(self, task: Task, step: TaskStep, result: StepResult) -> None:
        if result.cancelled:
            step.mark(StepState.SKIPPED, output=result.output,
                      error="Stopped by the owner.", evidence=result.evidence)
        elif result.ok:
            step.mark(StepState.COMPLETED, output=result.output, evidence=result.evidence)
        elif result.blocked:
            step.mark(StepState.BLOCKED, output=result.output, error=result.error,
                      evidence=result.evidence, blocked_reason=result.blocked_reason)
        else:
            step.mark(StepState.FAILED, output=result.output, error=result.error,
                      evidence=result.evidence)
        self.store.save(task)
        self.store.append_event(task.id, {
            "kind": "step_result",
            "index": step.index,
            "title": step.title,
            "state": step.state.value,
            "attempts": step.attempts,
            "error": step.last_error,
            "evidence": step.evidence,
        })

    def _loop_detected(self, step: TaskStep, result: StepResult) -> bool:
        signature = f"{step.kind.value}|{step.command}|{step.target}|{result.error}"[:400]
        if not self._failure_signatures or self._failure_signatures[-1] != signature:
            self._failure_signatures = [signature]
            return False
        self._failure_signatures.append(signature)
        return len(self._failure_signatures) >= max(2, self.config.loop_detection_repeats)

    def _unmet_dependency(self, task: Task, step: TaskStep) -> int | None:
        for dependency in step.depends_on:
            if dependency >= len(task.steps):
                return dependency
            if task.steps[dependency].state in (StepState.FAILED, StepState.BLOCKED,
                                                StepState.SKIPPED):
                return dependency
        return None

    def _enter_pause(self, task: Task) -> None:
        if task.state is not TaskState.PAUSED:
            try:
                task.transition(TaskState.PAUSED, "paused by owner")
            except Exception:
                task.state = TaskState.PAUSED
            self.store.save(task)
            self.store.append_event(task.id, {"kind": "paused", "cursor": task.cursor})
        # Wait without burning CPU; cancellation also releases the wait.
        while self._pause.is_set() and not self._cancel.is_set():
            self._resume.wait(timeout=0.5)
        if self._cancel.is_set():
            return
        try:
            task.transition(TaskState.RUNNING, "resumed by owner")
        except Exception:
            task.state = TaskState.RUNNING
        self.store.save(task)
        self.store.append_event(task.id, {"kind": "resumed", "cursor": task.cursor})

    def _close_cancelled(self, task: Task) -> None:
        if task.state.terminal:
            return
        # Work that never ran must look like work that never ran, not like work
        # that is still queued behind a task the owner has stopped.
        for step in task.steps:
            if step.state in (StepState.PENDING, StepState.RUNNING, StepState.VERIFYING):
                step.mark(StepState.SKIPPED, error="Task stopped before this step ran.")
        try:
            task.transition(TaskState.CANCELLED, task.cancel_reason or "stopped")
        except Exception:
            task.state = TaskState.CANCELLED

    def _finalize(self, task: Task, started_monotonic: float | None = None) -> TaskReport:
        counts = task.counts()
        failed_steps = [step for step in task.steps if step.state is StepState.FAILED]
        blocked_steps = [step for step in task.steps if step.state is StepState.BLOCKED]
        tests: dict[str, Any] = {}
        for step in task.steps:
            if step.kind.value == "run_tests" and step.evidence:
                for key in ("passed", "failed", "errors", "skipped", "total"):
                    if key in step.evidence:
                        tests[key] = step.evidence[key]

        if task.state not in (TaskState.CANCELLED, TaskState.FAILED):
            if failed_steps:
                task.transition(TaskState.FAILED, "one or more steps failed")
            elif blocked_steps:
                try:
                    task.transition(TaskState.WAITING, "blocked on owner input")
                except Exception:
                    task.state = TaskState.WAITING
                task.wait_reason = blocked_steps[0].blocked_reason or "waiting for input"
            else:
                task.transition(TaskState.COMPLETED, "all steps completed")

        duration = 0.0
        if task.started_at:
            duration = max(0.0, self._clock() - float(task.started_at))
        elif started_monotonic is not None:
            duration = 0.0
        report = TaskReport(
            task_id=task.id,
            objective=task.objective,
            state=task.state,
            completed=[step.title for step in task.steps
                       if step.state is StepState.COMPLETED],
            failed=[f"{step.title}: {step.last_error}" for step in failed_steps],
            blocked=[(step.title, step.blocked_reason or "blocked") for step in blocked_steps],
            skipped=[step.title for step in task.steps if step.state is StepState.SKIPPED],
            tests=tests,
            blockers=list(dict.fromkeys(task.blockers))[:8],
            attempts=task.retries_used + sum(step.attempts for step in task.steps),
            duration_s=duration,
        )
        task.report = report
        task.note(f"finished: {task.state.value}")
        # Journal the report first, then the snapshot that says "finished": a
        # reader who sees a terminal task can rely on its report already being
        # in the journal, instead of catching a finished task with no report.
        self.store.save_report(report)
        self.store.save(task)
        self.bus.publish_report(task, report)
        self.store.append_event(task.id, {
            "kind": "finished", "state": task.state.value,
            "counts": counts, "tests": tests,
        })
        self._milestone_safe(report.headline())
        return report

    # ── notifications -----------------------------------------------------
    def _emit(self, kind: str, task: Task, *, message: str = "",
              **data: Any) -> None:
        now = self._monotonic()
        milestone = kind in {"started", "planned", "blocked", "finished", "paused",
                             "step_failed"}
        if not milestone and (now - self._last_emit) < self.config.progress_min_interval_s:
            return
        self._last_emit = now
        event = event_from_task(kind, task, message=message, **data)
        self.bus.publish(event)

    def _milestone_safe(self, message: str) -> None:
        try:
            if self._milestone:
                self._milestone(message)
        except Exception:
            pass

    def _announce(self, message: str) -> None:
        """Speak a milestone through the injected callback (throttled by caller)."""
        self._milestone_safe(message)


def _default_workspace() -> Path:
    """The repository root (the folder that contains ``JarvisAI``)."""
    return Path(__file__).resolve().parent.parent.parent


def is_restartable(task: Task) -> bool:
    """True when a persisted task can be resumed instead of re-planned."""
    return bool(task.steps) and not task.state.terminal
