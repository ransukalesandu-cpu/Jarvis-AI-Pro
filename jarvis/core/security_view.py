"""Data behind the security panel (Security V2, Phase 5).

``snapshot`` returns what the UI may show for the *current* identity; ``perform`` runs
the few panel actions through the same owner-gated code the voice tools use. The
panel therefore has no privileges of its own: a Guest gets a notice and nothing else.
"""
from __future__ import annotations

from typing import Any

from jarvis.core import identity, failsoft
from jarvis.core.guest_audit import NOTICE, NOTICE_OFF, GuestAuditError, get_guest_audit
from jarvis.core.security_settings import BASELINE, SettingsError, get_security_settings


def _owner_session() -> identity.Session | None:
    s = identity.get_identity_manager().current()
    return s if (s.role == identity.ROLE_OWNER and s.state == identity.OWNER_AUTHENTICATED) else None


def snapshot() -> dict[str, Any]:
    mgr = identity.get_identity_manager()
    out: dict[str, Any] = {"mode": "signed_out", "monitoring": True, "notice": "", "owner_name": "",
                           "owners": [], "guest_summary": "", "baseline": list(BASELINE), "can_manage": False}
    try:
        from jarvis.core.owner_registry import get_owner_registry
        reg = get_owner_registry()
        if not reg.has_owners():
            out["mode"] = "legacy"
            return out
        out["monitoring"] = get_security_settings().monitoring_enabled()
        if mgr.guest_mode_active():
            out["mode"] = "guest"
            out["notice"] = NOTICE if out["monitoring"] else NOTICE_OFF
            return out                                    # a Guest sees the notice only
        sess = _owner_session()
        if sess is None:
            return out
        out["mode"] = "owner"
        out["can_manage"] = True
        owners = reg.list_owners()
        out["owners"] = [{"id": o["owner_id"], "name": o["display_name"], "admin": bool(o["is_admin"]),
                          "status": o["status"], "voice": bool(o["voice_enrolled"])} for o in owners]
        me = next((o for o in owners if o["owner_id"] == sess.owner_id), None)
        out["owner_name"] = me["display_name"] if me else ""
        out["guest_summary"] = get_guest_audit().summary_text(limit=3)
    except Exception:
        failsoft.suppress("security_view:snapshot")
    return out


def perform(action: str, **kw: Any) -> str:
    """Panel actions. Every one needs an owner session and reuses the gated implementations."""
    if _owner_session() is None:
        return "Only a signed-in owner can do that."
    mgr = identity.get_identity_manager()
    try:
        if action == "monitoring":
            get_security_settings().set_monitoring(mgr, bool(kw.get("enabled")))
            return "Guest monitoring is ON." if kw.get("enabled") else "Guest monitoring is OFF."
        if action == "delete_latest_guest":
            audit = get_guest_audit()
            sid = audit.latest_session_id()
            if not sid:
                return "No Guest activity is recorded."
            return f"Deleted the latest Guest session log ({audit.delete_session(sid)} entries)."
        if action == "revoke_owner":
            from jarvis.core.owner_registry import get_owner_registry
            get_owner_registry().revoke_owner(mgr, str(kw.get("owner_id", "")))
            return "Owner revoked."
    except (SettingsError, GuestAuditError) as exc:
        return f"Not changed: {exc}."
    except Exception as exc:
        failsoft.suppress("security_view:perform")
        return f"Not changed: {exc}."
    return "Unknown action."
