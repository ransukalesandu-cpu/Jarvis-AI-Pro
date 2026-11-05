"""Guest Mode coordinator (Security V2, Phase 3).

Ties the identity state machine, the owner registry and the Guest audit log together.
Guest Mode is only started when at least one owner exists, so installs that still use
the single legacy PIN behave exactly as before.

Nothing here reads or stores what a guest says. A task or website password is never
accepted here: only an owner PIN/voice proof from the registry can end Guest Mode.
"""
from __future__ import annotations

import threading
from typing import Optional

from jarvis.core import failsoft, identity
from jarvis.core.guest_audit import NOTICE, NOTICE_OFF, get_guest_audit


class GuestService:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def _registry(self):
        from jarvis.core.owner_registry import get_owner_registry
        return get_owner_registry()

    def enabled(self) -> bool:
        try:
            return self._registry().has_owners()
        except Exception:
            failsoft.suppress("guest:enabled")
            return False

    def start(self) -> Optional[str]:
        """Begin a visible Guest session. Returns the notice text to show, or None if not applicable."""
        with self._lock:
            mgr = identity.get_identity_manager()
            cur = mgr.current()
            if not self.enabled() or cur.role == identity.ROLE_OWNER or mgr.guest_mode_active():
                return None
            sess = mgr.start_guest()
            audit = get_guest_audit()
            audit.purge_expired()
            audit.record(sess.session_id, "guest_session_started")
            audit.record(sess.session_id, "guest_notice_shown")
            return NOTICE if audit.monitoring_enabled() else NOTICE_OFF

    def record_denial(self, tool: str, tier: str, reason: str = "guest_default_deny") -> None:
        try:
            sid = identity.get_identity_manager().current().session_id
            get_guest_audit().record(sid, "restricted_action_denied", identity.category_for(tool),
                                     "denied", tool=tool, tier=tier, reason=reason)
        except Exception:
            failsoft.suppress("guest:record_denial")

    def owner_login_pin(self, pin: str) -> tuple[bool, str]:
        """Only an owner PIN from the registry ends Guest Mode. Returns (ok, message)."""
        with self._lock:
            reg, mgr, audit = self._registry(), identity.get_identity_manager(), get_guest_audit()
            guest_sid = mgr.current().session_id if mgr.guest_mode_active() else ""
            proof = reg.authenticate_pin(pin)
            if proof is None:
                if guest_sid:
                    audit.record(guest_sid, "authentication_failed", "security_management", "denied",
                                 reason="wrong_credential")
                return False, "That did not match an owner credential."
            reg.login(mgr, proof)
            if guest_sid:
                audit.record(guest_sid, "guest_session_ended")
            return True, self.login_summary()

    def handle_typed_text(self, text: str, legacy_needs_pin: bool) -> Optional[tuple[bool, str]]:
        """Intercept an owner credential typed during Guest Mode, before it reaches any model or log.

        Returns None when the text is not a credential attempt (normal handling continues).
        Otherwise (consumed): (ok, message). A credential attempt is text typed while the
        legacy gate is asking for a PIN, or text that starts with ``/owner ``.
        """
        if not identity.get_identity_manager().guest_mode_active():
            return None
        raw = str(text or "").strip()
        if raw.lower().startswith("/owner "):
            return self.owner_login_pin(raw[7:].strip())
        if legacy_needs_pin:
            return self.owner_login_pin(raw)
        return None

    def login_summary(self) -> str:
        """What happened in Guest sessions since an owner last reviewed. Built from recorded events only."""
        audit = get_guest_audit()
        since = audit.last_review()
        denied = audit.denied_since(since)
        if not audit.sessions(since):
            return ""
        text = "Guest activity since you last checked:\n" + audit.summary_text(since, limit=3)
        if denied:
            text += "\nAsk me for the Guest history to see the details, or to delete it."
        audit.mark_reviewed()
        return text

    def end(self) -> None:
        with self._lock:
            mgr = identity.get_identity_manager()
            if mgr.guest_mode_active():
                get_guest_audit().record(mgr.current().session_id, "guest_session_ended")
            mgr.end_session()


_svc: Optional[GuestService] = None
_svc_lock = threading.Lock()


def get_guest_service() -> GuestService:
    global _svc
    with _svc_lock:
        if _svc is None:
            _svc = GuestService()
        return _svc


def reset_for_tests() -> None:
    global _svc
    with _svc_lock:
        _svc = None
