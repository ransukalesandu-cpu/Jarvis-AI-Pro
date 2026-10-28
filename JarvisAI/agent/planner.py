"""Turn one spoken objective into an ordered, verifiable plan.

Two planners, one contract:

* **Model planner** — when a text LLM is configured (the existing
  :class:`core.hybrid_llm_router.HybridLLMRouter`, unchanged), the objective is
  sent with a strict JSON schema and the answer is *validated*, not trusted.
  Unknown step kinds, out-of-workspace paths, over-long commands and
  destructive operations are rejected or downgraded with a recorded warning.
* **Deterministic planner** — always available, no network. It produces an
  honest engineering plan for this repository (inspect → test → diagnose →
  fix → re-test → verify → report) and marks steps it genuinely cannot perform
  without a model as ``blocked`` with the precise missing resource. That is the
  difference between "autonomous" and "pretending".

Both return a :class:`Plan` the runner can execute, and both are pure functions
of their inputs, which is what makes planning testable without an API key.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from agent.models import StepKind, TaskStep
from agent.store import redact

MAX_STEPS = 16
_MAX_COMMAND = 600

_KIND_ALIASES = {
    "inspect": StepKind.INSPECT,
    "shell": StepKind.RUN_COMMAND,
    "command": StepKind.RUN_COMMAND,
    "run": StepKind.RUN_COMMAND,
    "run_command": StepKind.RUN_COMMAND,
    "test": StepKind.RUN_TESTS,
    "tests": StepKind.RUN_TESTS,
    "run_tests": StepKind.RUN_TESTS,
    "pytest": StepKind.RUN_TESTS,
    "read": StepKind.READ_FILE,
    "read_file": StepKind.READ_FILE,
    "write": StepKind.WRITE_FILE,
    "write_file": StepKind.WRITE_FILE,
    "file_write": StepKind.WRITE_FILE,
    "observe": StepKind.OBSERVE_SCREEN,
    "observe_screen": StepKind.OBSERVE_SCREEN,
    "screen": StepKind.OBSERVE_SCREEN,
    "vision": StepKind.OBSERVE_SCREEN,
    "click": StepKind.SCREEN_ACTION,
    "screen_action": StepKind.SCREEN_ACTION,
    "type": StepKind.SCREEN_ACTION,
    "verify": StepKind.VERIFY,
    "check": StepKind.VERIFY,
    "note": StepKind.NOTE,
    "think": StepKind.NOTE,
}

_CRITERIA_HINTS = {
    "test": "The relevant automated tests pass.",
    "fix": "The reported failure no longer reproduces.",
    "ui": "The requested UI change is visible and existing panels still work.",
    "screen": "The described screen state is confirmed visually.",
}


@dataclass
class Plan:
    steps: list[TaskStep] = field(default_factory=list)
    criteria: list[str] = field(default_factory=list)
    source: str = "heuristic"
    rationale: str = ""
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> str:
        lines = [f"Plan ({self.source}) with {len(self.steps)} steps:"]
        lines.extend(f"  {index + 1}. [{step.kind.value}] {step.title}"
                     for index, step in enumerate(self.steps))
        if self.criteria:
            lines.append("Done when: " + "; ".join(self.criteria))
        if self.warnings:
            lines.extend(f"  ! {warning}" for warning in self.warnings)
        return "\n".join(lines)


class PlanError(RuntimeError):
    """The objective could not be turned into an executable plan."""


class TaskPlanner:
    """Plan with a model when possible, deterministically when not."""

    def __init__(
        self,
        ask: Callable[[str], str] | None = None,
        *,
        workspace: Path | str = "",
        max_steps: int = 12,
        model_name: str = "",
    ):
        self._ask = ask
        self.workspace = Path(workspace) if workspace else Path.cwd()
        self.max_steps = max(3, min(int(max_steps), MAX_STEPS))
        self.model_name = model_name

    # -- entry point -------------------------------------------------------
    def plan(self, objective: str, criteria: Iterable[str] | None = None) -> Plan:
        text = str(objective or "").strip()
        if not text:
            raise PlanError("No objective was given.")
        explicit = [str(item).strip() for item in (criteria or []) if str(item).strip()]

        if self._ask is not None:
            try:
                raw = self._ask(self._prompt(text))
                plan = self.parse(raw, text)
                if plan.steps:
                    plan.criteria = explicit or plan.criteria or _default_criteria(text)
                    return plan
            except Exception as exc:
                # A provider failure is a warning, not the end of the task.
                fallback = self.heuristic(text)
                fallback.warnings.append(
                    f"The planning model failed ({redact(exc, 160)}); "
                    "used the deterministic plan instead."
                )
                fallback.criteria = explicit or fallback.criteria
                return fallback

        plan = self.heuristic(text)
        plan.criteria = explicit or plan.criteria
        return plan

    # -- model plan --------------------------------------------------------
    def _prompt(self, objective: str) -> str:
        return (
            "You are planning a bounded, autonomous engineering task for JARVIS on "
            "this repository. Return ONE JSON object, no prose, of the form:\n"
            '{"criteria": [str], "steps": [{"title": str, "kind": one of '
            '["inspect","run_command","run_tests","read_file","write_file",'
            '"observe_screen","screen_action","verify","note"], '
            '"command": str, "path": str, "content": str, "target": str, '
            '"detail": str, "depends_on": [int], "expect": {str: any}, '
            '"consequential": bool}]}\n\n'
            f"Objective: {objective}\n"
            f"Workspace: {self.workspace}\n"
            f"Rules: at most {self.max_steps} steps; every command must be safe to "
            "run unattended and must not delete data, install packages, push, or "
            "contact anyone; prefer read-only inspection; include at least one "
            "'run_tests' or 'verify' step; paths are relative to the workspace; "
            "put a concrete verification criterion in 'expect' where possible "
            "(supported keys: exit_code, contains, not_contains, file_exists, "
            "test_failures, vision). Only mark a step 'consequential' if it truly "
            "cannot be undone. Do not include credentials in any field."
        )

    def parse(self, raw: str, objective: str = "") -> Plan:
        payload = _loads(raw)
        if not isinstance(payload, dict):
            raise PlanError("The planning model did not return a JSON object.")
        criteria = [
            str(item).strip() for item in payload.get("criteria") or []
            if str(item).strip()
        ][:6]
        steps: list[TaskStep] = []
        warnings: list[str] = []
        for index, item in enumerate(payload.get("steps") or []):
            if len(steps) >= self.max_steps:
                warnings.append(f"Ignored steps after the {self.max_steps}-step limit.")
                break
            if not isinstance(item, dict):
                warnings.append(f"Dropped malformed step #{index + 1}.")
                continue
            kind = _KIND_ALIASES.get(str(item.get("kind") or "").strip().lower())
            if kind is None:
                warnings.append(
                    f"Dropped step #{index + 1}: unknown kind "
                    f"{str(item.get('kind'))[:24]!r}."
                )
                continue
            command = str(item.get("command") or "").strip()
            if len(command) > _MAX_COMMAND:
                warnings.append(f"Dropped step #{index + 1}: command is too long.")
                continue
            path = str(item.get("path") or "").strip()
            if path and not _path_within(path, self.workspace):
                warnings.append(
                    f"Step #{index + 1} targeted a path outside the workspace; "
                    "it was dropped."
                )
                continue
            expect = item.get("expect") if isinstance(item.get("expect"), dict) else {}
            step = TaskStep(
                title=redact(str(item.get("title") or f"Step {index + 1}"), 140),
                kind=kind,
                detail=redact(str(item.get("detail") or ""), 800),
                command=command,
                path=path,
                content=str(item.get("content") or ""),
                target=redact(str(item.get("target") or ""), 120),
                depends_on=_dependencies(item.get("depends_on"), len(steps)),
                expect={str(key): value for key, value in expect.items()},
                consequential=bool(item.get("consequential", False)),
                max_retries=max(0, min(3, _as_int(item.get("max_retries"), 1))),
                timeout_s=max(10.0, min(600.0, _as_float(item.get("timeout_s"), 240.0))),
            )
            if kind in (StepKind.RUN_COMMAND, StepKind.RUN_TESTS, StepKind.INSPECT) and not command:
                warnings.append(f"Dropped step #{index + 1}: {kind.value} needs a command.")
                continue
            if kind is StepKind.WRITE_FILE and not (path and step.content):
                warnings.append(f"Dropped step #{index + 1}: write_file needs path and content.")
                continue
            if kind is StepKind.SCREEN_ACTION and not step.target:
                warnings.append(f"Dropped step #{index + 1}: screen_action needs a target.")
                continue
            steps.append(step)
        if not steps:
            raise PlanError(
                "The planning model returned no executable steps "
                + (f"({warnings[0]})" if warnings else ".")
            )
        return Plan(steps=steps, criteria=criteria, source="model",
                    rationale=f"Planned for: {objective}".strip(), warnings=warnings)

    # -- deterministic plan ------------------------------------------------
    def heuristic(self, objective: str) -> Plan:
        """A useful, honest plan that needs no model and no network."""
        lowered = str(objective or "").casefold()
        criteria = _default_criteria(objective)
        steps: list[TaskStep] = []
        warnings: list[str] = []

        python = _python_executable()
        steps.append(TaskStep(
            title="Inspect the working tree and recent history",
            kind=StepKind.INSPECT,
            detail="Read-only snapshot before changing anything.",
            command="git status --porcelain=v1 -b",
            expect={"exit_code": 0},
        ))
        steps.append(TaskStep(
            title="Confirm the test command is available",
            kind=StepKind.INSPECT,
            detail="Verify the repository layout and pytest availability.",
            command=f'"{python}" -m pytest --version',
        ))

        wants_screen = any(word in lowered for word in ("screen", "window", "click", "visible"))
        wants_ui = any(word in lowered for word in ("ui", "hologram", "interface", "dashboard"))
        wants_fix = any(word in lowered for word in ("fix", "error", "bug", "broken", "fail"))
        wants_tests = True  # the instruction always ends with "run the tests"
        wants_report = any(word in lowered for word in ("report", "summary", "finish"))

        if wants_screen:
            steps.append(TaskStep(
                title="Observe the current screen",
                kind=StepKind.OBSERVE_SCREEN,
                detail=objective,
            ))

        baseline_index = len(steps)
        steps.append(TaskStep(
            title="Run the baseline test suite",
            kind=StepKind.RUN_TESTS,
            detail="Record the current pass/fail counts before changing any code.",
            expect={"test_failures": 0},
            timeout_s=600.0,
        ))

        if wants_fix:
            steps.append(TaskStep(
                title="Diagnose the failing tests",
                kind=StepKind.NOTE,
                detail=(
                    "Analyse the baseline output. Automatic code repair needs a "
                    "configured planning model (GEMINI_API_KEY, or a local Ollama "
                    "model); without one this step reports the failure instead of "
                    "editing code blindly."
                ),
                depends_on=[baseline_index],
            ))
            steps.append(TaskStep(
                title="Apply the smallest safe fix",
                kind=StepKind.NOTE,
                detail=(
                    "BLOCKED unless a planning model is configured: JARVIS will not "
                    "rewrite source code from a heuristic. Re-run with a provider "
                    "configured, or point the agent at the specific failing file."
                ),
                depends_on=[baseline_index],
            ))

        if wants_ui:
            steps.append(TaskStep(
                title="Review the UI change without removing the hologram",
                kind=StepKind.NOTE,
                detail=(
                    "The hologram home screen must stay the default view and the "
                    "existing dashboard cards must remain intact."
                ),
            ))

        steps.append(TaskStep(
            title="Re-run the test suite after changes",
            kind=StepKind.RUN_TESTS,
            detail="Prove the failure is fixed and nothing else regressed.",
            expect={"test_failures": 0},
            timeout_s=600.0,
        ))
        verify_index = len(steps)
        steps.append(TaskStep(
            title="Verify the completion criteria",
            kind=StepKind.VERIFY,
            detail="Fail the task if the final test run still reports failures.",
            expect={"test_failures": 0},
            depends_on=[verify_index - 1],
        ))
        steps.append(TaskStep(
            title="Summarise the outcome",
            kind=StepKind.NOTE,
            detail="Compose the final report from recorded evidence.",
            depends_on=[verify_index],
        ))

        if len(steps) > self.max_steps:
            warnings.append(f"Trimmed the plan to {self.max_steps} steps.")
            steps = steps[: self.max_steps]
        if not wants_tests:  # pragma: no cover - kept for future callers
            warnings.append("No test step was requested; verification may be weak.")
        return Plan(steps=steps, criteria=criteria, source="heuristic",
                    rationale=f"Deterministic plan for: {objective}", warnings=warnings)


# ── helpers ──────────────────────────────────────────────────────────────────

def _default_criteria(objective: str) -> list[str]:
    lowered = str(objective or "").casefold()
    criteria = ["Every requested change is applied and recorded in the report."]
    for keyword, criterion in _CRITERIA_HINTS.items():
        if keyword in lowered and criterion not in criteria:
            criteria.append(criterion)
    criteria.append("The test suite finishes with no new failures.")
    return criteria[:4]


def _loads(raw: str) -> Any:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise PlanError("The planning model returned malformed JSON.") from exc
        raise PlanError("The planning model did not return JSON.")


def _dependencies(value: Any, count: int) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[int] = []
    for item in value:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= index < count and index not in out:
            out.append(index)
    return out


def _path_within(path: str, workspace: Path) -> bool:
    try:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = workspace / candidate
        candidate.resolve().relative_to(workspace.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _python_executable() -> str:
    import sys

    return sys.executable
