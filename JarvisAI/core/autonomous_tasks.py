"""Bounded task planning and execution primitives for JARVIS.

This module deliberately does not discover tools or grant permissions. Callers
must supply the existing protected dispatcher and an authorization gate. Every
task result is classified as done, unverified, failed, or blocked.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import re
from typing import Any, Callable, Iterable

_TASK_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
_ACTION = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
MAX_PLAN_TASKS = 32
MAX_PARALLEL_TASKS = 4


class PlanValidationError(ValueError):
    """Raised when a proposed task graph is malformed or unsafe to schedule."""


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    description: str = ""
    requires_authorization: bool = True


@dataclass(frozen=True)
class TaskPlan:
    tasks: tuple[TaskSpec, ...]
    max_parallel: int = 1

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskPlan":
        if not isinstance(payload, dict):
            raise PlanValidationError("Plan must be an object.")
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise PlanValidationError("Plan must contain a non-empty tasks list.")
        if len(raw_tasks) > MAX_PLAN_TASKS:
            raise PlanValidationError(f"Plan exceeds the {MAX_PLAN_TASKS}-task limit.")

        tasks: list[TaskSpec] = []
        seen: set[str] = set()
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                raise PlanValidationError("Each task must be an object.")
            task_id = str(raw.get("id", "")).strip()
            action = str(raw.get("action", "")).strip()
            if not _TASK_ID.fullmatch(task_id):
                raise PlanValidationError("Task id is missing or invalid.")
            if task_id in seen:
                raise PlanValidationError(f"Duplicate task id: {task_id}")
            if not _ACTION.fullmatch(action):
                raise PlanValidationError(f"Invalid action name for task {task_id}.")
            params = raw.get("parameters", {})
            deps = raw.get("depends_on", [])
            if not isinstance(params, dict) or not isinstance(deps, list):
                raise PlanValidationError(f"Invalid parameters/dependencies for {task_id}.")
            if not all(isinstance(dep, str) and dep.strip() for dep in deps):
                raise PlanValidationError(f"Invalid dependency in task {task_id}.")
            seen.add(task_id)
            tasks.append(TaskSpec(
                task_id=task_id,
                action=action,
                parameters=dict(params),
                depends_on=tuple(dict.fromkeys(dep.strip() for dep in deps)),
                description=str(raw.get("description", ""))[:300],
                requires_authorization=bool(raw.get("requires_authorization", True)),
            ))

        ids = {task.task_id for task in tasks}
        for task in tasks:
            unknown = set(task.depends_on) - ids
            if unknown:
                raise PlanValidationError(
                    f"Task {task.task_id} has unknown dependencies: {', '.join(sorted(unknown))}"
                )
            if task.task_id in task.depends_on:
                raise PlanValidationError(f"Task {task.task_id} cannot depend on itself.")

        parallel = payload.get("max_parallel", 1)
        if isinstance(parallel, bool) or not isinstance(parallel, int):
            raise PlanValidationError("max_parallel must be an integer.")
        if not 1 <= parallel <= MAX_PARALLEL_TASKS:
            raise PlanValidationError(f"max_parallel must be between 1 and {MAX_PARALLEL_TASKS}.")

        plan = cls(tuple(tasks), parallel)
        plan.topological_layers()  # Reject cycles before any action can run.
        return plan

    def topological_layers(self) -> tuple[tuple[TaskSpec, ...], ...]:
        by_id = {task.task_id: task for task in self.tasks}
        completed: set[str] = set()
        layers: list[tuple[TaskSpec, ...]] = []
        while len(completed) < len(by_id):
            ready = tuple(
                task for task in self.tasks
                if task.task_id not in completed
                and set(task.depends_on).issubset(completed)
            )
            if not ready:
                raise PlanValidationError("Task graph contains a dependency cycle.")
            layers.append(ready)
            completed.update(task.task_id for task in ready)
        return tuple(layers)


@dataclass
class TaskResult:
    task_id: str
    action: str
    status: str
    output: str = ""
    error_type: str = ""


@dataclass
class ExecutionReport:
    results: list[TaskResult]
    stopped_reason: str = ""

    @property
    def successful(self) -> bool:
        return bool(self.results) and all(item.status == "done" for item in self.results)


class AutonomousTaskExecutor:
    """Execute a validated DAG through caller-supplied protected boundaries.

    authorize(task) must enforce the installation's current owner/auth/privacy
    policy. dispatch(...) must be the existing ActionDispatcher/ActionRegistry
    path, never a raw shell or arbitrary callable from model-generated content.
    verify(task, output) returns True only when an observable postcondition was
    checked. Missing/negative verification yields 'unverified', not 'done'.
    """

    def __init__(
        self,
        dispatch: Callable[[str, dict[str, Any], dict[str, Any]], Any],
        *,
        authorize: Callable[[TaskSpec], bool],
        verify: Callable[[TaskSpec, Any], bool] | None = None,
        max_parallel: int = MAX_PARALLEL_TASKS,
    ) -> None:
        if not callable(dispatch) or not callable(authorize):
            raise TypeError("dispatch and authorize callbacks are required.")
        self._dispatch = dispatch
        self._authorize = authorize
        self._verify = verify
        self._max_parallel = max(1, min(int(max_parallel), MAX_PARALLEL_TASKS))

    def _run_one(self, task: TaskSpec, context: dict[str, Any]) -> TaskResult:
        try:
            if not self._authorize(task):
                return TaskResult(task.task_id, task.action, "blocked",
                                  "Authorization was not granted.")
            output = self._dispatch(task.action, dict(task.parameters), dict(context))
            if self._verify is None or not self._verify(task, output):
                return TaskResult(task.task_id, task.action, "unverified", str(output or ""))
            return TaskResult(task.task_id, task.action, "done", str(output or ""))
        except Exception as exc:
            return TaskResult(task.task_id, task.action, "failed", error_type=type(exc).__name__)

    def execute(self, plan: TaskPlan, *, context: dict[str, Any] | None = None) -> ExecutionReport:
        if not isinstance(plan, TaskPlan):
            raise TypeError("execute() requires a validated TaskPlan.")
        ctx = dict(context or {})
        results: list[TaskResult] = []
        completed: set[str] = set()
        by_id = {task.task_id: task for task in plan.tasks}
        worker_limit = min(plan.max_parallel, self._max_parallel)

        for layer in plan.topological_layers():
            # Dependencies must be verified complete before dependent actions run.
            if any(task_id not in completed for task_id in {
                dep for task in layer for dep in task.depends_on
            }):
                return ExecutionReport(results, "A dependency did not complete successfully.")

            if worker_limit == 1 or len(layer) == 1:
                layer_results = [self._run_one(task, ctx) for task in layer]
            else:
                layer_results = []
                with ThreadPoolExecutor(max_workers=min(worker_limit, len(layer))) as pool:
                    futures = {pool.submit(self._run_one, task, ctx): task for task in layer}
                    for future in as_completed(futures):
                        layer_results.append(future.result())

            results.extend(layer_results)
            failed = [item for item in layer_results if item.status != "done"]
            if failed:
                return ExecutionReport(
                    results,
                    "Execution stopped because a task was blocked, failed, or unverified.",
                )
            completed.update(item.task_id for item in layer_results)

        return ExecutionReport(results)
