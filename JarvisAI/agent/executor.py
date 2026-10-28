"""Step handlers: the only place the agent is allowed to touch the machine.

Each handler returns a :class:`StepResult` instead of raising, so the runner can
distinguish the three failure modes that matter:

* ``retryable``  — transient (timeout, flaky test, provider hiccup): try again.
* ``blocked``    — a credential, permission, missing dependency or a human
  decision is required: stop this step, report it precisely, keep going with
  independent work.
* neither        — a real, deterministic failure: count it against the budget.

Commands run in a child process with a hard timeout, a merged output pipe read on
a helper thread (no deadlock on chatty builds), redacted/truncated output, and
cancellation that terminates and then kills the process group. There is no
"fire and forget" path: autonomy does not mean orphaned pip installs.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent import policy as policy_module
from agent.models import StepKind, Task, TaskStep
from agent.store import redact

_MAX_OUTPUT = 6000
_CLIP_HEAD = 1500
_CLIP_MARKER = "\n\u2026 [{} characters clipped] \u2026\n"
_FORBIDDEN_ENV = ("PYTHONINSPECT", "PYTHONSTARTUP")
# Variables that *configure* JARVIS. They must never reach a child process: a
# test run started by the agent has to observe the same configuration a human
# running `pytest` would, not the agent's own dry-run/runtime/task-directory
# settings.
_FORBIDDEN_ENV_PREFIXES = ("JARVIS_AGENT", "JARVIS_AUTONOMOUS", "JARVIS_VISION")


@dataclass
class StepResult:
    ok: bool
    output: str = ""
    error: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    blocked: bool = False
    blocked_reason: str = ""
    cancelled: bool = False

    @classmethod
    def success(cls, output: str = "", **evidence: Any) -> "StepResult":
        return cls(True, output=redact(output), evidence=evidence)

    @classmethod
    def failure(cls, error: str, *, output: str = "", retryable: bool = False,
                evidence: dict[str, Any] | None = None) -> "StepResult":
        return cls(False, output=redact(output), error=redact(error),
                   retryable=retryable, evidence=evidence or {})

    @classmethod
    def blocked_result(cls, reason: str, *, output: str = "",
                       evidence: dict[str, Any] | None = None) -> "StepResult":
        return cls(False, output=redact(output), error=redact(reason), blocked=True,
                   blocked_reason=redact(reason), evidence=evidence or {})

    @classmethod
    def stopped(cls) -> "StepResult":
        return cls(False, error="Stopped.", cancelled=True)


@dataclass
class ExecutionContext:
    """Everything a handler may use. Injected, never looked up globally."""

    task: Task
    workspace: Path
    cancel: threading.Event
    pause: threading.Event
    logger: Callable[[str], None] = lambda message: None
    vision: Any | None = None
    computer: Any | None = None
    policy: policy_module.ExecutionPolicy = field(
        default_factory=policy_module.ExecutionPolicy
    )
    request_approval: Callable[[TaskStep, policy_module.Decision], bool] | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    emit: Callable[[str, dict[str, Any]], None] = lambda kind, data: None

    def stopped(self) -> bool:
        return self.cancel.is_set()

    def log(self, message: str) -> None:
        try:
            self.logger(redact(message, 500))
        except Exception:
            pass


class StepExecutor:
    """Dispatch one step to its handler, enforcing policy first."""

    def __init__(self, *, engine: policy_module.PolicyEngine | None = None,
                 command_runner: Callable[..., dict[str, Any]] | None = None):
        self.engine = engine or policy_module.PolicyEngine()
        self._command_runner = command_runner
        self._handlers = {
            StepKind.INSPECT: self._inspect,
            StepKind.RUN_COMMAND: self._run_command,
            StepKind.RUN_TESTS: self._run_tests,
            StepKind.READ_FILE: self._read_file,
            StepKind.WRITE_FILE: self._write_file,
            StepKind.OBSERVE_SCREEN: self._observe_screen,
            StepKind.SCREEN_ACTION: self._screen_action,
            StepKind.VERIFY: self._verify,
            StepKind.NOTE: self._note,
        }

    def execute(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        if ctx.cancel.is_set():
            return StepResult.stopped()
        decision = self.engine.check(step)
        if not decision.allowed and not decision.requires_approval:
            return StepResult.blocked_result(decision.reason)
        if decision.requires_approval:
            approver = ctx.request_approval
            approved = bool(approver and approver(step, decision))
            if not approved:
                return StepResult.blocked_result(
                    f"Approval was not granted for a consequential step ({decision.reason})."
                )
        handler = self._handlers.get(step.kind)
        if handler is None:
            return StepResult.blocked_result(f"Unsupported step kind: {step.kind.value}")
        try:
            result = handler(step, ctx)
        except Exception as exc:  # a handler bug must not kill the worker
            ctx.log(f"Step '{step.title}' raised {type(exc).__name__}: {exc}")
            return StepResult.failure(
                f"{type(exc).__name__}: {redact(exc, 400)}", retryable=True
            )
        if ctx.cancel.is_set() and not result.ok:
            result.cancelled = True
        return result

    # -- command execution -------------------------------------------------
    def _run_command(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        if not ctx.policy.allow_shell:
            return StepResult.blocked_result("Shell execution is disabled for autonomous tasks.")
        timeout = min(
            max(5.0, float(step.timeout_s)),
            max(5.0, float(ctx.policy.command_timeout_s)),
        )
        result = self._run_process(step.command, ctx, timeout)
        if result.get("cancelled"):
            return StepResult.stopped()
        output = str(result.get("output") or "")
        evidence = {
            "returncode": result.get("returncode"),
            "duration_s": round(float(result.get("duration_s") or 0.0), 2),
            "timed_out": bool(result.get("timed_out")),
        }
        if result.get("timed_out"):
            return StepResult.failure(
                f"The command exceeded its {timeout:.0f}s timeout.", output=output,
                retryable=True, evidence=evidence,
            )
        exit_code = result.get("returncode")
        if exit_code not in (0, None):
            # Non-zero is not automatically fatal; the plan said what it expects.
            expected = step.expect.get("exit_code")
            if expected is not None and int(expected) == int(exit_code):
                return StepResult.success(output, **evidence)
            retryable = _looks_transient(output)
            return StepResult.failure(
                f"The command exited with code {exit_code}.", output=output,
                retryable=retryable, evidence=evidence,
            )
        return StepResult.success(output, **evidence)

    def _run_tests(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        command = step.command or default_test_command(ctx.workspace)
        step.command = command
        result = self._run_command(step, ctx)
        if result.cancelled or result.blocked:
            return result
        counts = parse_test_summary(result.output)
        result.evidence.update(counts)
        if not result.ok:
            return result
        failures = counts.get("failed", 0) + counts.get("errors", 0)
        if failures:
            return StepResult.failure(
                f"{failures} test(s) failed.", output=result.output,
                retryable=False, evidence=result.evidence,
            )
        if counts.get("total") is None and not result.output.strip():
            return StepResult.failure(
                "The test command produced no output, so it could not be verified.",
                retryable=True, evidence=result.evidence,
            )
        return StepResult(True, output=result.output, evidence=result.evidence)

    def _inspect(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        if not step.command:
            return StepResult.blocked_result("The inspection step has no command.")
        result = self._run_command(step, ctx)
        if result.blocked or result.cancelled:
            return result
        # An inspection that exits non-zero (e.g. `git status` in a non-repo) is
        # still information, not necessarily a failure of the task.
        if not result.ok:
            result.retryable = False
        return result

    def _run_process(self, command: str, ctx: ExecutionContext, timeout: float) -> dict[str, Any]:
        if self._command_runner is not None:  # tests inject a fake process runner
            return self._command_runner(command, ctx, timeout)
        return run_process(
            command,
            cwd=ctx.workspace,
            timeout=timeout,
            cancel=ctx.cancel,
            logger=ctx.log,
        )

    # -- files -------------------------------------------------------------
    def _resolve(self, step: TaskStep, ctx: ExecutionContext) -> tuple[Path | None, str]:
        raw = str(step.path or "").strip()
        if not raw:
            return None, "No path was given."
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = ctx.workspace / path
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as exc:
            return None, f"Invalid path: {exc}"
        try:
            resolved.relative_to(ctx.workspace.resolve())
        except ValueError:
            return None, (
                f"Refusing to touch '{resolved}': it is outside the task workspace "
                f"({ctx.workspace})."
            )
        return resolved, ""

    def _read_file(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        path, error = self._resolve(step, ctx)
        if path is None:
            return StepResult.blocked_result(error)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return StepResult.failure(f"{path.name} does not exist.")
        except OSError as exc:
            return StepResult.failure(f"Could not read {path.name}: {exc}")
        evidence = {"path": str(path), "lines": text.count("\n") + 1}
        return StepResult.success(redact(text, _MAX_OUTPUT), **evidence)

    def _write_file(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        if not ctx.policy.allow_file_write:
            return StepResult.blocked_result("File writes are disabled for autonomous tasks.")
        path, error = self._resolve(step, ctx)
        if path is None:
            return StepResult.blocked_result(error)
        if ctx.cancel.is_set():
            return StepResult.stopped()
        content = str(step.content or "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            existed = path.exists()
            if existed and path.is_dir():
                return StepResult.failure(f"{path.name} is a directory.")
            temporary = path.with_name(path.name + ".jarvis-tmp")
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, path)
        except OSError as exc:
            return StepResult.failure(f"Could not write {path.name}: {exc}", retryable=True)
        return StepResult.success(
            f"{'Replaced' if existed else 'Created'} {path.name} "
            f"({len(content)} characters).",
            path=str(path), bytes=len(content.encode("utf-8")),
        )

    # -- screen ------------------------------------------------------------
    def _observe_screen(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        if ctx.vision is None:
            return StepResult.blocked_result(
                "Screen vision is not available. Configure a vision provider "
                "(GEMINI_API_KEY) and install mss/Pillow plus Tesseract for OCR."
            )
        try:
            observation = ctx.vision.observe(step.detail or step.title)
        except Exception as exc:
            return StepResult.failure(f"Screen observation failed: {redact(exc, 300)}",
                                      retryable=True)
        evidence = {
            "provider": observation.provider,
            "confidence": round(float(observation.confidence), 3),
            "uncertain": bool(observation.uncertain),
            "elements": [element.to_dict() for element in observation.elements[:6]],
            "error_text": observation.error_text,
        }
        return StepResult(True, output=observation.summary(), evidence=evidence)

    def _screen_action(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        if ctx.computer is None:
            return StepResult.blocked_result(
                "Desktop control is not available (pyautogui is missing or no "
                "display is attached)."
            )
        if not step.target:
            return StepResult.blocked_result("The screen action has no target control.")
        expectation = str(step.expect.get("vision") or "")
        try:
            result = ctx.computer.click_element(step.target, expectation=expectation)
        except Exception as exc:
            return StepResult.failure(f"Desktop action failed: {redact(exc, 300)}",
                                      retryable=True)
        evidence = result.to_dict()
        if result.cancelled:
            return StepResult.stopped()
        if result.blocked:
            return StepResult.blocked_result(result.detail or "Blocked by policy.",
                                             evidence=evidence)
        if not result.ok:
            return StepResult.failure(result.detail or "The action did not take effect.",
                                      output=result.observed, retryable=result.retryable,
                                      evidence=evidence)
        output = result.detail
        if result.observed:
            output += f"\nNow on screen: {result.observed}"
        return StepResult(True, output=output, evidence=evidence)

    # -- verification ------------------------------------------------------
    def _verify(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        expect = dict(step.expect or {})
        previous = None
        for candidate in reversed(ctx.task.steps[: step.index]):
            if candidate.state.value in {"completed", "failed"}:
                previous = candidate
                break
        evidence: dict[str, Any] = {}
        checks: list[tuple[str, bool, str]] = []

        if "file_exists" in expect:
            path = Path(str(expect["file_exists"])).expanduser()
            if not path.is_absolute():
                path = ctx.workspace / path
            exists = path.exists()
            checks.append(("file_exists", exists, str(path)))
            evidence["checked_file"] = str(path)

        if "contains" in expect and previous is not None:
            needle = str(expect["contains"])
            found = needle.casefold() in (previous.output or "").casefold()
            checks.append(("contains", found, needle[:80]))

        if "not_contains" in expect and previous is not None:
            needle = str(expect["not_contains"])
            absent = needle.casefold() not in (previous.output or "").casefold()
            checks.append(("not_contains", absent, needle[:80]))

        if "test_failures" in expect:
            limit = int(expect.get("test_failures") or 0)
            failures = 0
            if previous is not None:
                failures = int(previous.evidence.get("failed", 0)) + int(
                    previous.evidence.get("errors", 0)
                )
            checks.append(("test_failures", failures <= limit, f"{failures} ≤ {limit}"))

        vision_expectation = str(expect.get("vision") or "")
        if vision_expectation:
            if ctx.vision is None:
                return StepResult.blocked_result(
                    "The plan asks for visual verification, but screen vision is not "
                    "available."
                )
            try:
                outcome = ctx.vision.verify(vision_expectation)
            except Exception as exc:
                return StepResult.failure(
                    f"Visual verification failed: {redact(exc, 300)}", retryable=True
                )
            checks.append(("vision", bool(outcome.ok), f"{outcome.reason[:80]}"))
            evidence["vision_confidence"] = round(float(outcome.confidence), 3)
            evidence["vision_provider"] = outcome.provider

        if not checks:
            return StepResult.blocked_result(
                "This verification step has no criteria the engine understands "
                "(supported: file_exists, contains, not_contains, test_failures, vision)."
            )

        failures = [name for name, ok, _ in checks if not ok]
        ok = not failures
        detail = "; ".join(f"{name}: {'ok' if passed else 'failed'} ({info})"
                           for name, passed, info in checks)
        evidence["checks"] = [{"name": name, "ok": passed} for name, passed, _ in checks]
        if ok:
            return StepResult(True, output=detail, evidence=evidence)
        return StepResult(False, output=detail, error=detail, retryable=False,
                          evidence=evidence)

    def _note(self, step: TaskStep, ctx: ExecutionContext) -> StepResult:
        return StepResult.success(step.detail or step.title)


# ── process helpers ──────────────────────────────────────────────────────────

_SHELL_META = re.compile(r"[|&;<>()$`]")


def run_process(
    command: str,
    *,
    cwd: Path,
    timeout: float,
    cancel: threading.Event | None = None,
    logger: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run a command with a hard timeout and cooperative cancellation."""
    started = time.monotonic()
    env = child_environment()
    use_shell = bool(_SHELL_META.search(command)) or os.name == "nt"
    if use_shell:
        args: Any = command
    else:
        args = shlex.split(command)

    try:
        process = subprocess.Popen(
            args,
            cwd=str(cwd),
            shell=use_shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except FileNotFoundError:
        return {"returncode": 127, "output": f"Command not found: {command}",
                "duration_s": 0.0, "timed_out": False}
    except OSError as exc:
        return {"returncode": None, "output": f"Could not start the command: {exc}",
                "duration_s": 0.0, "timed_out": False}

    chunks: list[str] = []
    head_chars = 0
    tail_chars = 0
    lock = threading.Lock()

    def reader() -> None:
        # Keep the first few lines *and* the last few, because test runners and
        # build tools print their summary at the very end. Truncating the tail
        # used to drop pytest's "N passed" line, so the verification step could
        # not tell a passing suite from a failing one.
        nonlocal head_chars, tail_chars
        try:
            assert process.stdout is not None
            for line in process.stdout:
                with lock:
                    chunks.append(line)
                    if head_chars < _CLIP_HEAD:
                        head_chars += len(line)
                    else:
                        tail_chars += len(line)
                        while tail_chars > _MAX_OUTPUT * 4 and len(chunks) > 2:
                            tail_chars -= len(chunks.pop(1))
        except Exception:
            return

    thread = threading.Thread(target=reader, name="jarvis-agent-output", daemon=True)
    thread.start()

    timed_out = False
    cancelled = False
    while True:
        returncode = process.poll()
        if returncode is not None:
            break
        if cancel is not None and cancel.is_set():
            cancelled = True
            _terminate(process)
            break
        if time.monotonic() - started > timeout:
            timed_out = True
            _terminate(process)
            break
        time.sleep(0.05)

    try:
        returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - process ignoring SIGKILL
        returncode = None
    thread.join(timeout=2)
    try:
        if process.stdout is not None:
            process.stdout.close()
    except Exception:
        pass
    with lock:
        output = _clip_output("".join(chunks))
    if logger:
        logger(f"command finished rc={returncode} in "
               f"{time.monotonic() - started:.1f}s: {command[:120]}")
    return {
        "returncode": returncode,
        "output": output,
        "duration_s": time.monotonic() - started,
        "timed_out": timed_out,
        "cancelled": cancelled,
    }


def child_environment() -> dict[str, str]:
    """The environment a spawned command runs with.

    Mark children as agent-spawned, but do NOT inherit ``JARVIS_AUTONOMOUS`` or
    the ``JARVIS_AGENT_*`` / ``JARVIS_VISION_*`` switches: those *configure* the
    app, so exporting them into a test run would make the suite observe a
    different configuration than the user's (e.g. a 10-minute runtime budget
    instead of the default 4 hours).
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _FORBIDDEN_ENV
        and not key.upper().startswith(_FORBIDDEN_ENV_PREFIXES)
    }
    env.update({"PYTHONUNBUFFERED": "1", "JARVIS_AGENT_CHILD": "1", "NO_COLOR": "1"})
    return env


def _clip_output(text: str) -> str:
    """Redact secrets, keeping both ends of an over-long output.

    ``core.self_repair.redact_secrets`` hard-truncates at 6 000 characters from
    the *head*, so the output is clipped first. An over-long log has to keep its
    tail: pytest, npm and cargo all print the pass/fail summary on the last
    lines, and those counts are what the verification step relies on.
    """
    raw = str(text or "")
    budget = _MAX_OUTPUT - 100
    if len(raw) > budget:
        tail_chars = budget - _CLIP_HEAD - 60
        head = raw[:_CLIP_HEAD]
        tail = raw[-tail_chars:] if tail_chars > 0 else ""
        clipped = len(raw) - len(head) - len(tail)
        raw = head + _CLIP_MARKER.format(clipped) + tail
    return redact(raw, _MAX_OUTPUT)


def _terminate(process: subprocess.Popen) -> None:
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=3)
        return
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass


_TEST_COUNT_RE = re.compile(
    r"(\d+)\s+(passed|failed|skipped|error|errors|xfailed|xpassed|deselected)\b",
    re.IGNORECASE,
)


def parse_test_summary(output: str) -> dict[str, Any]:
    """Best-effort pass/fail counts from pytest/unittest/npm style output."""
    counts: dict[str, Any] = {}
    for match in _TEST_COUNT_RE.finditer(str(output or "")):
        number = int(match.group(1))
        label = match.group(2).lower()
        if label == "errors":
            label = "error"
        if label == "error":
            counts["errors"] = counts.get("errors", 0) + number
        elif label in {"passed", "failed", "skipped", "xfailed", "xpassed", "deselected"}:
            counts[label] = counts.get(label, 0) + number
    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0)
    errors = counts.get("errors", 0)
    if passed or failed or errors:
        counts["total"] = passed + failed + errors + counts.get("skipped", 0)
        counts["ok"] = failed == 0 and errors == 0
        # Explicit zeroes matter: "0 failed" is evidence, "missing" is not.
        for key in ("passed", "failed", "errors", "skipped"):
            counts.setdefault(key, 0)
    return counts


def default_test_command(workspace: Path) -> str:
    """A deterministic test command for this repository."""
    import sys

    root = Path(workspace)
    if (root / "JarvisAI").is_dir():
        return f'"{sys.executable}" -m pytest JarvisAI/tests -q'
    if (root / "tests").is_dir():
        return f'"{sys.executable}" -m pytest tests -q'
    return f'"{sys.executable}" -m pytest -q'


def _looks_transient(output: str) -> bool:
    lowered = str(output or "").casefold()
    return any(
        marker in lowered
        for marker in (
            "timed out", "timeout", "connection reset", "temporary failure",
            "resource temporarily unavailable", "address already in use",
            "rate limit", "please try again",
        )
    )
