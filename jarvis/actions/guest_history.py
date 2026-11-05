"""Owner-only view of the Guest security log (what was blocked, never what was said)."""
from __future__ import annotations

from jarvis.core import identity
from jarvis.core.guest_audit import GuestAuditError, get_guest_audit

_DENY = "Guest history is only available to a signed-in owner."


def _owner_signed_in() -> bool:
    s = identity.get_identity_manager().current()
    return s.role == identity.ROLE_OWNER and s.state == identity.OWNER_AUTHENTICATED


def guest_history(parameters: dict, **_ctx) -> str:
    if not _owner_signed_in():
        return _DENY
    audit = get_guest_audit()
    action = str((parameters or {}).get("action", "summary")).lower()
    if action == "summary":
        audit.mark_reviewed()
        return audit.summary_text(limit=10)
    if action == "latest":
        sid = audit.latest_session_id()
        return audit.detail_text(sid) if sid else "No Guest activity is recorded."
    if action == "delete_latest":
        if not (parameters or {}).get("confirm"):
            return "This permanently deletes the latest Guest session log. Ask again with confirmation to proceed."
        sid = audit.latest_session_id()
        if not sid:
            return "No Guest activity is recorded."
        try:
            n = audit.delete_session(sid)
        except GuestAuditError as exc:
            return f"Not confirmed: {exc}."
        return f"Deleted the latest Guest session log ({n} entries) and confirmed it is gone."
    return "Unknown action. Use summary, latest or delete_latest."


TOOL = {
    "name": "guest_history",
    "description": ("Owner only. Show what Guest sessions attempted or were blocked from doing (a short security "
                    "log, never conversation content), or delete the latest Guest session log. "
                    "action: summary | latest | delete_latest (delete needs confirm=true)."),
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "description": "summary, latest or delete_latest"},
        "confirm": {"type": "BOOLEAN", "description": "must be true for delete_latest"}}},
    "handler": guest_history,
}
