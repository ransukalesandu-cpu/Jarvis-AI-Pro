"""Audit trail for computer control.

Every action — allowed, denied, dry-run, cancelled, failed — is written through
the existing owner-readable action log (core/action_log.py, so
``show_recent_actions`` and the dashboard see it) with redacted arguments.
Approval decisions additionally go to the HMAC-chained security ledger
(core/security.audit) so they are tamper-evident.

Tool names in the log are ``cc.<action>`` (for example ``cc.element.click``).
Nothing here raises: an audit failure must not turn into a crashed action, but
it is recorded through core/failsoft so it is visible in diagnostics.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from jarvis.computer_control.redaction import redact_params, redact_text

_recent: deque = deque(maxlen=200)


def record(action: str, params: Mapping[str, Any] | None, result: Any, *, status: str,
           level: str = "", duration_ms: int | None = None, job_id: str | None = None,
           extra: Mapping[str, Any] | None = None) -> dict:
    safe_args = redact_params(params)
    if extra:
        safe_args["_cc"] = redact_params(extra)
    risk = {"low": "read", "medium": "write", "high": "destructive"}.get(str(level), "")
    entry = {"tool": f"cc.{action}", "args": safe_args, "status": status, "risk": risk,
             "result": redact_text(result, 400)}
    _recent.append(entry)
    try:
        from jarvis.core import action_log
        return action_log.record(f"cc.{action}", safe_args, entry["result"], status=status,
                                 risk=risk, duration_ms=duration_ms, job_id=job_id)
    except Exception:
        from jarvis.core import failsoft
        failsoft.suppress("computer_control.audit:record")
        return entry


def ledger(event: str, action: str, level: str, decision: str, detail: str = "") -> None:
    try:
        from jarvis.core import security
        security.audit(event, f"cc.{action}", str(level), decision, redact_text(detail, 200))
    except Exception:
        from jarvis.core import failsoft
        failsoft.suppress("computer_control.audit:ledger")


def recent(limit: int = 20) -> list[dict]:
    """In-process copy of the newest entries (tests, status panel)."""
    return list(_recent)[-max(1, int(limit)):]


def clear_for_tests() -> None:
    _recent.clear()
