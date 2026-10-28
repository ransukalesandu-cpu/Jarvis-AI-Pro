"""Run pytest and make its failures visible where people actually look.

A red CI job is useless if the failure cannot be read. The raw job log is served
from a signed blob URL that is not always reachable (and is unwieldy in a
terminal), so this wrapper does three things with the *same* run:

1. prints pytest's output as usual, so nothing is hidden from the console;
2. appends a short summary to ``$GITHUB_STEP_SUMMARY``, which renders on the job
   page;
3. emits one ``::error file=...,title=...::`` workflow command per failing test,
   which GitHub turns into check-run **annotations** — visible inline on the PR
   files tab and readable from ``GET /repos/{owner}/{repo}/check-runs/{id}/annotations``.

Usage (any pytest arguments are forwarded)::

    python scripts/ci_pytest_annotate.py tests/test_ui_hologram.py -q

Exits with pytest's own exit code, so CI still fails when the suite fails.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

_MAX_ANNOTATIONS = 10          # GitHub silently drops annotations past ~10 per step
_MAX_MESSAGE = 900             # keeps each annotation well under the API limit

_FAILED_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+)(?:\s+-\s+(.*))?$")
_ERROR_LINE_RE = re.compile(r"^E\s+(.*)$")
_SECTION_RE = re.compile(r"^_{3,}\s+(.+?)\s+_{3,}$")


def _summary_tail(output: str, limit: int = 6000) -> str:
    """The part of the output a human needs: the summary plus first failures."""
    if len(output) <= limit:
        return output
    head, tail = output[: limit // 2], output[-limit // 2:]
    return f"{head}\n… output clipped …\n{tail}"


def _section_errors(lines: list[str]) -> dict[str, str]:
    """First ``E ...`` line of each failure section, keyed by the test name."""
    errors: dict[str, str] = {}
    current: str | None = None
    for line in lines:
        section = _SECTION_RE.match(line.strip())
        if section:
            current = section.group(1)
            continue
        if current is None or current in errors:
            continue
        detail = _ERROR_LINE_RE.match(line.strip())
        if detail:
            errors[current] = detail.group(1)
    return errors


def _annotations(output: str) -> list[tuple[str, str, str]]:
    """(file, title, message) for each failing test, in output order."""
    lines = output.splitlines()
    errors = _section_errors(lines)
    found: list[tuple[str, str, str]] = []
    for line in lines:
        match = _FAILED_RE.match(line.strip())
        if not match:
            continue
        kind, nodeid, reason = match.groups()
        path = nodeid.split("::", 1)[0]
        message = reason or ""
        if not message or message.endswith("..."):
            # pytest truncates a long reason on the summary line; the real
            # assertion lives in the failure section printed above it.
            leaf = nodeid.split("::")[-1]
            for name, detail in errors.items():
                if name.endswith(leaf):
                    message = detail
                    break
        found.append((path, f"{kind}: {nodeid}", (message or kind)[:_MAX_MESSAGE]))
        if len(found) >= _MAX_ANNOTATIONS:
            break
    return found


def main(argv: list[str]) -> int:
    command = [sys.executable, "-m", "pytest", *argv]
    process = subprocess.run(command, capture_output=True, text=True, errors="replace")
    output = process.stdout + process.stderr
    print(output, end="" if output.endswith("\n") else "\n")

    failures = process.returncode != 0
    if failures:
        for path, title, message in _annotations(output):
            flat = message.replace("\r", " ").replace("\n", " ")
            print(f"::error file={path},line=1,title={title}::{flat}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write("## pytest\n\n```\n")
            stream.write(_summary_tail(output))
            stream.write("\n```\n")
    return process.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
