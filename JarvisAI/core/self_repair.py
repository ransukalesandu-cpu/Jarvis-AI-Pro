"""Guarded self-diagnosis and recovery primitives for JARVIS.

This module deliberately does not let an AI rewrite files, run shell commands,
install packages, or change security settings automatically. It records errors,
classifies common failures, and permits only explicitly registered recovery
callbacks. Transient operations may be retried once when the caller opts in.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)(\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
)
_TRANSIENT = (TimeoutError, ConnectionError)
_LOCK = threading.RLock()
_REPAIRERS: dict[str, Callable[[dict[str, Any]], str]] = {}
_RECENT: dict[str, int] = {}


def redact_secrets(value: object) -> str:
    """Remove common credentials from error text before it is persisted."""
    text = str(value)
    text = _SECRET_PATTERNS[0].sub(r"\1\2[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub("Bearer [REDACTED]", text)
    text = _SECRET_PATTERNS[2].sub("[REDACTED_API_KEY]", text)
    return text[:6000]


def classify_error(exc: BaseException) -> dict[str, str]:
    """Return a conservative diagnosis and safe next step for a known error."""
    name = type(exc).__name__
    message = redact_secrets(exc)
    lowered = message.casefold()

    if isinstance(exc, (TimeoutError, ConnectionError)) or "timed out" in lowered or "connection reset" in lowered:
        category = "transient_network_or_timeout"
        suggestion = "Check network/provider status and retry once; do not change credentials automatically."
    elif isinstance(exc, ModuleNotFoundError) or "no module named" in lowered:
        category = "missing_dependency"
        suggestion = "Check the active Python environment, then install only the named project dependency."
    elif isinstance(exc, PermissionError) or "permission denied" in lowered or "access is denied" in lowered:
        category = "permission_error"
        suggestion = "Check the file/app permissions manually; do not elevate privileges automatically."
    elif "api key" in lowered or "unauthorized" in lowered or "authentication" in lowered or "401" in lowered:
        category = "authentication_or_quota"
        suggestion = "Check API-key configuration and provider quota without printing or exposing credentials."
    elif "rate limit" in lowered or "429" in lowered or "quota" in lowered:
        category = "provider_rate_limit"
        suggestion = "Back off and retry later; do not rotate keys or repeatedly call the provider."
    else:
        category = "unclassified"
        suggestion = "Save the redacted traceback, reproduce in tests, and propose a minimal patch."

    return {"exception": name, "category": category, "message": message, "suggestion": suggestion}


def register_repair(category: str, callback: Callable[[dict[str, Any]], str]) -> None:
    """Register a trusted in-process recovery action for one exact category."""
    key = str(category).strip()
    if not key or not callable(callback):
        raise ValueError("A non-empty category and callable repair callback are required.")
    with _LOCK:
        _REPAIRERS[key] = callback


def unregister_repair(category: str) -> None:
    with _LOCK:
        _REPAIRERS.pop(str(category).strip(), None)


def repair_registered(category: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run only a recovery callback explicitly registered by application code."""
    key = str(category).strip()
    with _LOCK:
        callback = _REPAIRERS.get(key)
    if callback is None:
        return {"attempted": False, "success": False, "message": "No approved repair is registered."}
    try:
        result = callback(dict(context or {}))
        return {"attempted": True, "success": True, "message": redact_secrets(result)}
    except Exception as exc:
        return {"attempted": True, "success": False, "message": redact_secrets(exc)}


def record_error(
    exc: BaseException,
    *,
    operation: str = "unknown",
    log_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Classify and append a redacted incident record to a JSONL log."""
    diagnosis = classify_error(exc)
    safe_operation = redact_secrets(operation)[:200]
    trace = redact_secrets("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    fingerprint = hashlib.sha256(
        f"{safe_operation}|{diagnosis['exception']}|{diagnosis['category']}|{diagnosis['message']}".encode("utf-8")
    ).hexdigest()[:16]
    with _LOCK:
        count = _RECENT.get(fingerprint, 0) + 1
        _RECENT[fingerprint] = count

    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": safe_operation,
        "fingerprint": fingerprint,
        "repeat_count": count,
        "diagnosis": diagnosis,
        "traceback": trace,
    }
    target = Path(log_path) if log_path else Path(os.environ.get("JARVIS_SELF_REPAIR_LOG", "logs/self_repair.jsonl"))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        record["logged"] = True
    except OSError as log_exc:
        # Logging failure must never replace the original application error.
        record["logged"] = False
        record["log_error"] = redact_secrets(log_exc)
    return record


def run_with_recovery(
    operation: Callable[[], T],
    *,
    operation_name: str = "unknown",
    retries: int = 1,
    retry_delay: float = 0.2,
    log_path: str | os.PathLike[str] | None = None,
    retry_exceptions: tuple[type[BaseException], ...] = _TRANSIENT,
) -> T:
    """Run an operation and retry only explicitly designated transient errors.

    Retries are opt-in through this wrapper. The default is one retry, and only
    TimeoutError/ConnectionError are retryable. Non-idempotent actions (send,
    purchase, delete, publish, etc.) should never be wrapped with retries.
    """
    attempts = max(0, min(int(retries), 2)) + 1
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            record_error(exc, operation=operation_name, log_path=log_path)
            retryable = isinstance(exc, retry_exceptions)
            if not retryable or attempt >= attempts - 1:
                raise
            time.sleep(max(0.0, min(float(retry_delay), 2.0)))
    raise RuntimeError("Unreachable recovery state")


def health_snapshot() -> dict[str, Any]:
    """Expose a minimal local status summary for a diagnostics screen."""
    with _LOCK:
        snapshot = {
            "registered_repair_categories": sorted(_REPAIRERS),
            "known_error_fingerprints": len(_RECENT),
            "total_observed_occurrences": sum(_RECENT.values()),
            "automatic_code_editing": False,
            "arbitrary_shell_execution": False,
        }
    # Import locally to avoid coupling module initialisation and keep health
    # diagnostics available even if the optional audio helper is unavailable.
    try:
        from core.audio_callback_guard import audio_queue_snapshot
        snapshot["audio_queue"] = audio_queue_snapshot()
    except Exception:
        snapshot["audio_queue"] = {"available": False}
    return snapshot


def install_global_exception_hooks() -> Callable[[], None]:
    """Log uncaught main/thread exceptions, then delegate to Python's handlers.

    Returns an uninstall callback for tests or controlled shutdown. The hook
    never attempts to restart threads or silently swallow an exception.
    """
    import sys

    previous_sys_hook = sys.excepthook
    previous_thread_hook = getattr(threading, "excepthook", None)

    def main_hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        try:
            record_error(exc, operation="runtime:uncaught_main_thread")
        except Exception:
            pass
        previous_sys_hook(exc_type, exc, tb)

    def thread_hook(args: Any) -> None:
        try:
            record_error(args.exc_value, operation=f"runtime:uncaught_thread:{args.thread.name if args.thread else 'unknown'}")
        except Exception:
            pass
        if previous_thread_hook is not None:
            previous_thread_hook(args)

    sys.excepthook = main_hook
    if previous_thread_hook is not None:
        threading.excepthook = thread_hook

    def uninstall() -> None:
        # Restore only if our hooks are still installed; don't overwrite a
        # handler another library may have installed afterward.
        if sys.excepthook is main_hook:
            sys.excepthook = previous_sys_hook
        if previous_thread_hook is not None and threading.excepthook is thread_hook:
            threading.excepthook = previous_thread_hook

    return uninstall
