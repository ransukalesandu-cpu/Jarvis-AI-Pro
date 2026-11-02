"""Append-only record of every tool call: what JARVIS did, when, and how it went.

One JSON object per line in ``<user data>/actions.jsonl``::

    {"ts": "2026-11-02T14:03:22", "tool": "run_command", "device": "laptop",
     "risk": "destructive", "args": {...}, "result": "first 400 chars",
     "status": "ok" | "error" | "timeout" | "job_started" | "cancelled",
     "duration_ms": 812}

Secrets in arguments and results are scrubbed before writing. The file is
trimmed to the newest MAX_LINES entries so it stays small. The
``show_recent_actions`` tool reads it back (actions/show_recent_actions.py).

Unlike core/security.py's HMAC-chained audit ledger (tamper evidence for the
security layer), this log is for the owner: readable, short, and complete.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_LINES = 2000
_RESULT_CHARS = 400
_ARG_CHARS = 300
_lock = threading.Lock()
_writes_since_trim = 0


def log_path() -> Path:
    from core.user_data import user_data_file
    return user_data_file("actions.jsonl")


def _scrub(text: str, limit: int) -> str:
    try:
        from agent.store import redact
        return redact(text, limit)
    except Exception:
        return str(text)[:limit]


def _scrub_args(args: Any) -> Any:
    if isinstance(args, dict):
        out = {}
        for key, value in args.items():
            lowered = str(key).lower()
            if any(word in lowered for word in ("password", "token", "secret", "api_key", "apikey", "pin")):
                out[key] = "[redacted]"
            else:
                out[key] = _scrub_args(value)
        return out
    if isinstance(args, (list, tuple)):
        return [_scrub_args(v) for v in list(args)[:20]]
    if isinstance(args, str):
        return _scrub(args, _ARG_CHARS)
    return args


def record(tool: str, args: dict | None, result: Any, *, status: str = "ok",
           risk: str = "", device: str = "laptop", duration_ms: int | None = None,
           job_id: str | None = None) -> dict:
    """Append one entry. Never raises: logging must not break a tool call."""
    global _writes_since_trim
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "tool": tool,
        "device": device,
        "risk": risk,
        "args": _scrub_args(dict(args or {})),
        "result": _scrub(str(result if result is not None else ""), _RESULT_CHARS),
        "status": status,
    }
    if duration_ms is not None:
        entry["duration_ms"] = int(duration_ms)
    if job_id:
        entry["job_id"] = job_id
    try:
        path = log_path()
        line = json.dumps(entry, ensure_ascii=False)
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            _writes_since_trim += 1
            if _writes_since_trim >= 200:
                _writes_since_trim = 0
                _trim(path)
    except Exception as exc:   # pragma: no cover - disk full / permissions
        print(f"[ActionLog] Could not write: {type(exc).__name__}: {exc}")
    return entry


def _trim(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= MAX_LINES:
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
    tmp.replace(path)


def recent(limit: int = 10, tool: str | None = None) -> list[dict]:
    try:
        lines = log_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if tool and row.get("tool") != tool:
            continue
        out.append(row)
        if len(out) >= max(1, int(limit)):
            break
    return out


class Timer:
    def __init__(self):
        self.started = time.perf_counter()

    @property
    def ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)
