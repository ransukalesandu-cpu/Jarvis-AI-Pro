"""Load a local, untracked ``.env`` file into the process environment.

Standard library only (no python-dotenv dependency). Looked up in order:

1. the path in ``JARVIS_ENV_FILE`` (if set),
2. ``<repo root>/.env``,
3. ``jarvis/.env``.

Values already present in the real environment always win, so a key set in
Windows' environment variables is never overwritten by the file. Lines look
like ``KEY=value``; ``#`` comments, blank lines, ``export KEY=...`` and quoted
values are accepted. Values are never printed or logged.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PACKAGE_DIR.parent
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def candidate_files() -> list[Path]:
    files: list[Path] = []
    override = os.environ.get("JARVIS_ENV_FILE", "").strip()
    if override:
        files.append(Path(override))
    files += [_REPO_ROOT / ".env", _PACKAGE_DIR / ".env"]
    return files


def parse(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()  # inline comment after unquoted value
        values[key] = value
    return values


def load(files: list[Path] | None = None) -> list[str]:
    """Apply every candidate file; return the names of variables that were set."""
    applied: list[str] = []
    for path in files if files is not None else candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for key, value in parse(text).items():
            if value and key not in os.environ:
                os.environ[key] = value
                applied.append(key)
    return applied
