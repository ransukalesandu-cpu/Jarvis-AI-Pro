"""Child-process entry point for one node job.

Started by :mod:`jarvis.node.worker` as ``python -I jobrunner.py`` in the job's own
work folder with a scrubbed environment. It reads ``{"kind": ..., "payload": ...}``
on stdin and writes JSON lines on stdout:

    {"progress": 0.25, "message": "..."}     zero or more (real progress only)
    {"result": {...}}                       exactly one on success
    {"error": "..."}                        exactly one on failure (exit code 2)

The payload is validated again here: the parent's checks are not trusted blindly.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# ``-I`` keeps PYTHONPATH and the working folder off sys.path; add only this checkout.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class JobInputError(ValueError):
    pass


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def diag_echo(payload: dict) -> dict:
    text = payload.get("text", "")
    if set(payload) - {"text"} or not isinstance(text, str) or len(text) > 2000:
        raise JobInputError("diag.echo takes {'text': up to 2000 characters}")
    import platform
    return {"echo": text, "python": platform.python_version()}


def diag_sleep(payload: dict) -> dict:
    seconds, fail = payload.get("seconds", 1), payload.get("fail", False)
    if set(payload) - {"seconds", "fail"} or isinstance(seconds, bool) \
            or not isinstance(seconds, (int, float)) or not 0 <= seconds <= 600 or not isinstance(fail, bool):
        raise JobInputError("diag.sleep takes {'seconds': 0-600, 'fail': bool}")
    steps = max(1, int(seconds / 0.25))
    for i in range(steps):
        time.sleep(seconds / steps)
        _emit({"progress": round((i + 1) / steps, 3), "message": f"waited {seconds * (i + 1) / steps:.1f}s"})
    if fail:
        raise RuntimeError("diag.sleep was asked to fail")
    return {"slept_s": seconds}


HANDLERS = {"diag.echo": diag_echo, "diag.sleep": diag_sleep}


def main() -> int:
    try:
        request = json.loads(sys.stdin.read(70_000) or "{}")
        kind, payload = request.get("kind"), request.get("payload", {})
        handler = HANDLERS.get(kind)
        if handler is None or not isinstance(payload, dict):
            raise JobInputError(f"unknown job kind {kind!r}")
        _emit({"result": handler(payload)})
        return 0
    except JobInputError as exc:
        _emit({"error": f"Invalid job input: {exc}"[:300]})
    except Exception as exc:                         # the parent records a failed job
        _emit({"error": f"{type(exc).__name__}: {exc}"[:300]})
    return 2


if __name__ == "__main__":
    sys.exit(main())
