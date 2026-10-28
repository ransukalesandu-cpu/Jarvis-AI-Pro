"""Verified self-update workflow for a Git checkout of JARVIS-AI-Pro.

The updater only accepts this project's canonical GitHub origin, requires a clean
checkout on main, creates a backup branch, fast-forwards (never force-pulls), and
runs the local unittest suite. If tests fail, it resets main to the backup commit.
The update operation is separately gated by core.security as DANGEROUS.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent
_ALLOWED_ORIGINS = {
    "https://github.com/ransukalesandu-cpu/Jarvis-AI-Pro.git",
    "https://github.com/ransukalesandu-cpu/Jarvis-AI-Pro",
    "git@github.com:ransukalesandu-cpu/Jarvis-AI-Pro.git",
    "ssh://git@github.com/ransukalesandu-cpu/Jarvis-AI-Pro.git",
}
_TIMEOUT = 180


class UpdateError(RuntimeError):
    """A safe update precondition or update step failed."""


def _git(*args: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_DIR), *args],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(f"Could not run Git safely: {type(exc).__name__}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "Git command failed").strip()[-1200:]
        raise UpdateError(detail)
    return result.stdout.strip()


def _preflight() -> tuple[str, str, str]:
    if getattr(sys, "frozen", False):
        raise UpdateError(
            "This is a packaged/frozen build. Git self-update is unavailable; "
            "use the official installer/release workflow instead."
        )
    if not (REPO_DIR / ".git").exists():
        raise UpdateError(
            f"No Git checkout found at {REPO_DIR}. This updater will not overwrite "
            "a copied folder or packaged app."
        )
    origin = _git("remote", "get-url", "origin")
    if origin not in _ALLOWED_ORIGINS:
        raise UpdateError(
            "The Git origin is not the configured official JARVIS-AI-Pro repository. "
            "No update was downloaded or applied."
        )
    branch = _git("branch", "--show-current")
    if branch != "main":
        raise UpdateError(
            f"Self-update requires the main branch; current branch is {branch!r}. "
            "Switch branches manually before updating."
        )
    changes = _git("status", "--porcelain", "--untracked-files=normal")
    if changes:
        raise UpdateError(
            "The checkout has local/untracked changes. Commit or back them up first; "
            "the updater will not overwrite them."
        )
    local_sha = _git("rev-parse", "HEAD")
    return origin, branch, local_sha


def _backup_ref_for(commit_sha: str) -> str | None:
    """Find an existing backup branch that points at the requested commit."""
    output = _git(
        "for-each-ref", "--format=%(refname:short) %(objectname)",
        "refs/heads/jarvis-backup-",
    )
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == commit_sha:
            return parts[0]
    return None


def _remote_sha() -> str:
    output = _git("ls-remote", "origin", "refs/heads/main", timeout=30)
    if not output:
        raise UpdateError("Could not find the official main branch. Check internet access.")
    parts = output.split()
    if len(parts) < 2 or parts[1] != "refs/heads/main":
        raise UpdateError("GitHub returned an unexpected main-branch reference.")
    return parts[0]


def _check() -> str:
    _origin, branch, local_sha = _preflight()
    remote_sha = _remote_sha()
    if local_sha == remote_sha:
        return (
            "JARVIS self-update check complete: already up to date with official main. "
            f"Commit: {local_sha[:12]}. No files changed."
        )
    return (
        "An official JARVIS update is available. "
        f"Installed commit: {local_sha[:12]}; latest main: {remote_sha[:12]}. "
        "The checkout is clean and on main. Ask JARVIS to apply the update to create "
        "a backup, fast-forward, run tests, and roll back if tests fail."
    )


def _update() -> str:
    _origin, _branch, old_sha = _preflight()
    remote_sha = _remote_sha()
    if old_sha == remote_sha:
        return f"JARVIS is already up to date ({old_sha[:12]}). No changes made."

    # Fetch only the official main branch; never run arbitrary scripts or shell text.
    _git("fetch", "--no-tags", "origin", "main", timeout=90)
    fetched_sha = _git("rev-parse", "origin/main")
    if fetched_sha != remote_sha:
        raise UpdateError(
            "The remote main branch changed during the check. No code was updated; retry."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_branch = f"jarvis-backup-{stamp}"
    _git("branch", backup_branch, old_sha)
    try:
        _git("merge", "--ff-only", "origin/main", timeout=90)
    except UpdateError:
        raise UpdateError(
            f"Fast-forward failed. Your original commit remains backed up as "
            f"{backup_branch}; no force update was attempted."
        )

    try:
        tests = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=str(BASE_DIR), capture_output=True, text=True,
            timeout=_TIMEOUT, check=False,
        )
        test_output = (tests.stdout + "\n" + tests.stderr).strip()[-5000:]
        if tests.returncode != 0:
            raise UpdateError(
                "The new version failed its local unittest suite. The updater will "
                "roll back to the previous commit. Test details:\n" + test_output
            )
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(
            "The local tests timed out. The updater will roll back to the previous commit."
        ) from exc
    except OSError as exc:
        raise UpdateError(
            f"Could not start the local tests ({exc}). The updater will roll back."
        ) from exc

    return (
        "JARVIS updated successfully and the local unittest suite passed. "
        f"Previous version backup: {backup_branch}. Restart JARVIS to load the new code."
    )


def self_update(parameters: dict, **_kwargs) -> str:
    operation = str(parameters.get("operation", "check")).strip().lower()
    if operation == "check":
        try:
            return _check()
        except UpdateError as exc:
            return f"Self-update check could not proceed safely: {exc}"
    if operation != "update":
        return "Choose operation 'check' or 'update'."

    backup_branch = None
    try:
        # Capture the current HEAD so rollback is possible even if tests fail.
        _preflight()
        old_sha = _git("rev-parse", "HEAD")
        try:
            return _update()
        except UpdateError as exc:
            current_sha = _git("rev-parse", "HEAD")
            if current_sha != old_sha:
                # The update began, but did not validate. Checkout was proven clean
                # before touching it, so resetting to the exact prior commit is safe.
                backup_branch = _backup_ref_for(old_sha)
                if backup_branch is None:
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    backup_branch = f"jarvis-backup-{stamp}-{old_sha[:8]}"
                    try:
                        _git("branch", backup_branch, old_sha)
                    except UpdateError as backup_exc:
                        return (
                            f"Update failed: {exc}. Could not create a named backup: "
                            f"{backup_exc}. Previous commit: {old_sha}. "
                            "Do not restart until the repository state is reviewed."
                        )
                try:
                    _git("reset", "--hard", old_sha)
                except UpdateError as rollback_exc:
                    return (
                        f"UPDATE FAILED: {exc}\nCRITICAL: automatic rollback also failed: "
                        f"{rollback_exc}. Previous commit: {old_sha}. Do not restart "
                        "until the repository state is reviewed."
                    )
                return (
                    f"Update failed and was rolled back to {old_sha[:12]}. "
                    f"Backup reference: {backup_branch}. Reason: {exc}"
                )
            return f"Update was not applied. {exc}"
    except UpdateError as exc:
        return f"Self-update stopped before changing code: {exc}"


TOOL = {
    "name": "self_update",
    "description": (
        "Check for official JARVIS-AI-Pro updates from the configured GitHub main branch, "
        "or apply an update to a clean Git checkout. operation=check is read-only. "
        "operation=update is a high-impact code change and must pass the normal security "
        "confirmation gate. Update requires the canonical origin, main branch and clean "
        "working tree; it creates a backup, uses fast-forward only, runs local unit tests, "
        "and rolls back to the previous commit if tests fail. Never bypass these checks."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {
                "type": "STRING",
                "enum": ["check", "update"],
                "description": "Check the official version or apply a verified update.",
            },
        },
        "required": ["operation"],
    },
    "handler": self_update,
}
