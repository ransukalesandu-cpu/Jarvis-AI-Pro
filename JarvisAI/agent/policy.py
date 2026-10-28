"""Least-privilege execution policy for autonomous steps.

The engine can run for minutes without a human in the loop, so "the model asked
for it" is not authorization. Every step is classified *before* it runs, and the
classification is independent of the plan text:

* ``READ``          — inspection only: listing, reading, ``git status``, tests.
* ``WRITE``         — reversible local changes: writing a file inside the repo,
                      creating a folder, running a formatter.
* ``CONSEQUENTIAL`` — anything that could destroy data, spend money, contact a
                      third party, change credentials/security, or leave the
                      machine: deletes, force-pushes, installs, publishes,
                      shutdown, purchases, outbound messages.

A consequential step is refused unless the caller supplies an approval callback
*and* the existing owner authentication allows it. Deny is the default in every
ambiguous case, which is why the pattern list below is intentionally blunt.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from agent.models import StepKind, TaskStep


class Risk(str, Enum):
    READ = "read"
    WRITE = "write"
    CONSEQUENTIAL = "consequential"

    @property
    def order(self) -> int:
        return {Risk.READ: 0, Risk.WRITE: 1, Risk.CONSEQUENTIAL: 2}[self]


#: Commands that may appear in an autonomous plan without asking the owner.
#: Anything not listed is still allowed, but only at the tier its risk implies —
#: this list exists so the *common* inspection commands stay fast.
_READ_ONLY_HEADS = {
    "ls", "dir", "pwd", "cat", "type", "head", "tail", "wc", "find", "grep",
    "rg", "git", "python", "python3", "py", "pip", "ruff", "pytest", "node",
    "npm", "echo", "which", "where", "whoami", "stat", "file", "du", "df",
    "systeminfo", "ver", "uname", "env", "printenv", "tree", "sort", "uniq",
}

#: (pattern, explanation). Matched case-insensitively against the whole command.
_CONSEQUENTIAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+", "recursive or forced delete"),
    (r"\brm\s+-[a-z]*[rf]", "recursive or forced delete"),
    (r"\brmdir\b|\bdel\s+/[sq]\b|\bformat\s+[a-z]:", "destructive filesystem command"),
    (r"\bgit\s+push\b.*(--force|-f)\b", "force-push rewrites shared history"),
    (r"\bgit\s+reset\s+--hard\b", "discards uncommitted work"),
    (r"\bgit\s+clean\s+-[a-z]*[fd]", "deletes untracked files"),
    (r"\bgit\s+(checkout|restore)\s+--\s", "discards uncommitted work"),
    (r"\bgit\s+branch\s+-D\b", "deletes a branch"),
    (r"\bpip3?\s+(install|uninstall)\b", "changes the Python environment"),
    (r"\bnpm\s+(publish|install\s+-g)\b", "publishes or installs globally"),
    (r"\b(curl|wget)\b[^|;&]*(\||&&|;)\s*(sh|bash|python|powershell)", "pipes remote code to an interpreter"),
    (r"\bsudo\b|\brunas\b|\bdoas\b", "privilege escalation"),
    (r"\bshutdown\b|\breboot\b|\bpoweroff\b|\bhalt\b", "power state change"),
    (r"\bdiskpart\b|\bmkfs\b|\bdd\s+if=", "disk-level operation"),
    (r"\breg\s+(add|delete)\b|\bsetx\b|\bnet\s+user\b", "security/account configuration"),
    (r"\bchmod\s+(-R\s+)?777\b|\bicacls\b|\btakeown\b", "permission change"),
    (r"\bgit\s+config\b.*(credential|user\.)", "credential/identity configuration"),
    (r"\b(scp|rsync|ssh|ftp|sftp|telnet)\b", "remote transfer or shell"),
    (r"\b(sendmail|mailx|twilio|slack\s+hook|webhook)\b", "external communication"),
    (r"\b(purchase|checkout|place\s+order|buy\s+now|payment)\b", "purchase or payment"),
    (r"\bapi[_-]?keys?\.json\b|\.env\b|id_rsa|\.pem\b|credential", "credential material"),
    (r"\b(drop|truncate)\s+(table|database)\b", "destructive database operation"),
    (r"\bkill(all)?\s+-9\b|\btaskkill\b.*\/f\b", "forced process termination"),
    (r"\b(wipe|erase|shred)\b", "data destruction"),
)

#: A command containing these writes to disk, even when its head is read-only.
_WRITE_PATTERNS: tuple[str, ...] = (
    r"\bgit\s+(add|commit|tag|stash|merge|rebase|cherry-pick)\b",
    r"\bgit\s+push\b",
    r"\bmkdir\b|\btouch\b|\bcp\b|\bmv\b|\bln\b",
    r"\b(python|python3|py)\s+-m\s+(pip|compileall)\b",
    r"\b(ruff|black|isort|prettier)\b[^\n]*--(fix|write)\b",
    r">\s*[^|&]+",          # output redirection
    r"\btee\b",
    r"\b(pytest|python|python3|py)\b.*(--cov|--junitxml|--html)\b",
)


def _strip_quoted(command: str) -> str:
    """Remove quoted literal text so a filename like "rm -rf" is not a match."""
    return re.sub(r"(\"[^\"]*\"|'[^']*')", "''", command)


def classify_command(command: str) -> tuple[Risk, str]:
    """Return the risk of a shell command and the reason for that verdict."""
    raw = str(command or "").strip()
    if not raw:
        return Risk.READ, "empty command"
    lowered = _strip_quoted(raw).casefold()
    for pattern, reason in _CONSEQUENTIAL_PATTERNS:
        if re.search(pattern, lowered):
            return Risk.CONSEQUENTIAL, reason
    for pattern in _WRITE_PATTERNS:
        if re.search(pattern, lowered):
            return Risk.WRITE, "modifies local files or the environment"
    head = _command_head(raw)
    if head and head not in _READ_ONLY_HEADS:
        # Unknown binaries are treated as writes at most: they need the WRITE
        # scope, but not a human, unless a pattern above flagged them.
        return Risk.WRITE, f"unrecognised command '{head}'"
    return Risk.READ, "read-only inspection"


def _command_head(command: str) -> str:
    try:
        parts = shlex.split(command, posix=(__import__("os").name != "nt"))
    except ValueError:
        parts = str(command).split()
    while parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", parts[0]):
        parts.pop(0)
    if not parts:
        return ""
    head = parts[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if head.endswith(".exe"):
        head = head[:-4]
    return head


def classify_step(step: TaskStep) -> tuple[Risk, str]:
    """Classify a planned step. Explicit ``consequential`` wins over analysis."""
    if step.consequential:
        return Risk.CONSEQUENTIAL, "plan marked this step consequential"
    if step.kind in (StepKind.INSPECT, StepKind.READ_FILE, StepKind.NOTE,
                     StepKind.OBSERVE_SCREEN, StepKind.VERIFY):
        if step.command:
            return classify_command(step.command)
        return Risk.READ, "observation only"
    if step.kind is StepKind.RUN_TESTS:
        return classify_command(step.command or "python -m pytest -q")
    if step.kind is StepKind.RUN_COMMAND:
        return classify_command(step.command)
    if step.kind is StepKind.WRITE_FILE:
        return Risk.WRITE, "writes a file inside the workspace"
    if step.kind is StepKind.SCREEN_ACTION:
        return Risk.CONSEQUENTIAL, "controls the desktop"
    return Risk.CONSEQUENTIAL, "unclassified step kind"


#: Tool names the existing dispatcher already tiers, reused so the two systems
#: cannot drift apart. Imported lazily: ``core.security`` touches the owner
#: auth manager at import time and should not load in a bare unit test.
def existing_tier(name: str, params: dict[str, Any] | None = None) -> str | None:
    try:
        from core.security import tier_for
    except Exception:
        return None
    try:
        return tier_for(name, params or {})
    except Exception:
        return None


@dataclass
class ExecutionPolicy:
    """Bounded, explicit limits for one autonomous run."""

    allowed_risk: Risk = Risk.WRITE
    allow_shell: bool = True
    allow_file_write: bool = True
    allow_input_control: bool = True
    allow_network: bool = True
    workspace_root: str = ""
    max_steps: int = 24
    max_attempts_per_step: int = 3
    max_runtime_s: float = 1800.0
    command_timeout_s: float = 300.0
    retry_backoff_s: float = 2.0
    max_retry_backoff_s: float = 30.0
    retry_budget: int = 12
    approval_timeout_s: float = 120.0
    deny_patterns: tuple[str, ...] = field(default_factory=tuple)

    def allows(self, risk: Risk) -> bool:
        return risk.order <= self.allowed_risk.order


@dataclass
class Decision:
    """Outcome of a policy check for one step."""

    allowed: bool
    risk: Risk
    reason: str
    requires_approval: bool = False
    blocked: bool = False

    def __bool__(self) -> bool:  # pragma: no cover - sugar for `if decision`
        return self.allowed


class PolicyEngine:
    """Classify and gate steps against a policy and the existing security layer."""

    def __init__(
        self,
        policy: ExecutionPolicy | None = None,
        *,
        owner_check: Callable[[], bool] | None = None,
    ):
        self.policy = policy or ExecutionPolicy()
        self._owner_check = owner_check

    # -- authorization -----------------------------------------------------
    def owner_authorized(self) -> bool:
        """True when the existing owner-authentication layer permits work."""
        if self._owner_check is not None:
            try:
                return bool(self._owner_check())
            except Exception:
                return False
        try:
            from core.security import is_owner_access_allowed

            return bool(is_owner_access_allowed())
        except Exception:
            # No security layer available (headless test, import error): the
            # caller may still run READ-only work, but nothing consequential.
            return False

    def check(self, step: TaskStep) -> Decision:
        risk, reason = classify_step(step)
        policy = self.policy

        if not policy.allows(risk):
            return Decision(
                allowed=False,
                risk=risk,
                reason=f"{risk.value} step refused: {reason}",
                requires_approval=risk is Risk.CONSEQUENTIAL,
                blocked=risk is Risk.CONSEQUENTIAL,
            )

        if step.kind is StepKind.RUN_COMMAND and not policy.allow_shell:
            return Decision(False, risk, "shell execution is disabled for autonomous tasks", blocked=True)
        if step.kind is StepKind.RUN_TESTS and not policy.allow_shell:
            return Decision(False, risk, "shell execution is disabled for autonomous tasks", blocked=True)
        if step.kind is StepKind.WRITE_FILE and not policy.allow_file_write:
            return Decision(False, risk, "file writes are disabled for autonomous tasks", blocked=True)
        if step.kind is StepKind.SCREEN_ACTION and not policy.allow_input_control:
            return Decision(False, risk, "desktop control is disabled for autonomous tasks", blocked=True)

        command = str(step.command or "")
        for pattern in policy.deny_patterns:
            try:
                if re.search(pattern, command, re.IGNORECASE):
                    return Decision(
                        False, risk,
                        f"command matches a configured deny rule ({pattern})",
                        blocked=True,
                    )
            except re.error:
                continue

        if risk is Risk.CONSEQUENTIAL:
            if not self.owner_authorized():
                return Decision(
                    False, risk,
                    "owner verification is required before consequential actions",
                    requires_approval=True,
                    blocked=True,
                )
            return Decision(
                True, risk,
                f"consequential action needs explicit approval: {reason}",
                requires_approval=True,
            )

        if step.kind is StepKind.WRITE_FILE and policy.workspace_root:
            if not _within(step.path, policy.workspace_root):
                return Decision(
                    False, risk,
                    f"path outside the task workspace is not writable: {step.path}",
                    blocked=True,
                )

        return Decision(True, risk, reason)

    def authorize_for_risk(self, risk: Risk) -> tuple[bool, str]:
        """Is this *run* allowed to reach this risk level at all?"""
        if not self.policy.allows(risk):
            return False, f"task scope allows up to {self.policy.allowed_risk.value} only"
        if risk is Risk.CONSEQUENTIAL and not self.owner_authorized():
            return False, "owner verification is required for consequential actions"
        return True, "within task scope"


def _within(path: str, root: str) -> bool:
    if not path:
        return True
    from pathlib import Path

    try:
        candidate = Path(path).expanduser().resolve()
        base = Path(root).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    try:
        candidate.relative_to(base)
        return True
    except ValueError:
        return False


def summarize_risks(steps: Iterable[TaskStep]) -> dict[str, int]:
    """Count how many steps each risk level contains (used in the UI preview)."""
    counts = {risk.value: 0 for risk in Risk}
    for step in steps:
        risk, _ = classify_step(step)
        counts[risk.value] += 1
    return counts
