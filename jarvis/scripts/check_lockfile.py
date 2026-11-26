"""Check that the hashed lockfiles still satisfy requirements*.txt.

    python -m jarvis.scripts.check_lockfile

CI installs ``requirements-dev.lock`` with ``pip install --require-hashes``, so every byte it installs is
pinned and hash-checked. This script (also run as a test) catches the lockfiles drifting from the
human-edited ``requirements*.txt``: a requirement missing from a lock, a pin outside its range, or a
pin without hashes. It does not resolve anything and needs no network.

When it fails, regenerate both locks from the repository root (needs uv):

    uv pip compile --universal --python-version 3.11 --generate-hashes --no-header \\
        --annotation-style line requirements.txt requirements-dev.txt -o requirements-dev.lock
    uv pip compile --universal --python-version 3.11 --generate-hashes --no-header \\
        --annotation-style line requirements.txt -c requirements-dev.lock -o requirements.lock

``requirements.lock`` is constrained by the dev lock, so the runtime pins are exactly the versions CI tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[2]

#: lockfile -> the requirement files it must satisfy
LOCKS: dict[str, tuple[str, ...]] = {
    "requirements.lock": ("requirements.txt",),
    "requirements-dev.lock": ("requirements.txt", "requirements-dev.txt"),
}

REGENERATE = (
    "uv pip compile --universal --python-version 3.11 --generate-hashes --no-header --annotation-style line "
    "requirements.txt requirements-dev.txt -o requirements-dev.lock && "
    "uv pip compile --universal --python-version 3.11 --generate-hashes --no-header --annotation-style line "
    "requirements.txt -c requirements-dev.lock -o requirements.lock"
)


def parse_requirements(path: Path) -> list[Requirement]:
    """Top-level requirements of a requirements file (comments, blank lines and options skipped)."""
    out: list[Requirement] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith(("#", "-")):
            continue
        out.append(Requirement(line))
    return out


def parse_lock(path: Path) -> tuple[dict[str, list[Version]], list[str]]:
    """Pinned versions per canonical name, plus problems (unparsable lines, pins without hashes)."""
    pins: dict[str, list[Version]] = {}
    problems: list[str] = []
    entry = ""
    for raw in path.read_text(encoding="utf-8").splitlines() + [""]:
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if entry and not raw.startswith((" ", "\t")):
            _add_entry(entry, pins, problems, path.name)
            entry = ""
        if line.strip():
            entry += " " + line.strip().rstrip("\\").strip()
    return pins, problems


def _add_entry(entry: str, pins: dict[str, list[Version]], problems: list[str], lock: str) -> None:
    head, *hashes = entry.strip().split(" --hash=")
    if not hashes or not all(h.startswith("sha256:") and len(h) == 71 for h in hashes):
        problems.append(f"{lock}: no sha256 hashes for {head.split(';')[0].strip()!r}")
    try:
        req = Requirement(head.strip())
    except InvalidRequirement:
        problems.append(f"{lock}: cannot parse {head.strip()!r}")
        return
    spec = list(req.specifier)
    if len(spec) != 1 or spec[0].operator != "==":
        problems.append(f"{lock}: {req.name} is not pinned with ==")
        return
    try:
        pins.setdefault(canonicalize_name(req.name), []).append(Version(spec[0].version))
    except InvalidVersion:
        problems.append(f"{lock}: {req.name} has an invalid version {spec[0].version!r}")


def check(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    for lock, sources in LOCKS.items():
        lock_path = root / lock
        if not lock_path.is_file():
            problems.append(f"{lock} is missing")
            continue
        pins, lock_problems = parse_lock(lock_path)
        problems += lock_problems
        for source in sources:
            for req in parse_requirements(root / source):
                versions = pins.get(canonicalize_name(req.name))
                if not versions:
                    problems.append(f"{lock}: {req.name} (from {source}) is not in the lock")
                    continue
                for version in versions:
                    if not req.specifier.contains(version, prereleases=True):
                        problems.append(f"{lock}: {req.name}=={version} does not satisfy {req} (from {source})")
    return problems


def main() -> int:
    problems = check()
    if not problems:
        print("lockfiles satisfy requirements*.txt")
        return 0
    print("Lockfiles are out of date with requirements*.txt:", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(f"\nRegenerate them from the repository root:\n  {REGENERATE}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
