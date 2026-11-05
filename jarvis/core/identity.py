"""Security V2 identity and session model (Phase 1).

One in-process source of truth for *who is acting*. Everything here is
backend-side: a role is never read from the UI, a request, or a task password.

States (docs/SECURITY_V2_ARCHITECTURE.md):
    UNAUTHENTICATED -> GUEST
    GUEST / UNAUTHENTICATED -> OWNER_AUTHENTICATING -> OWNER_AUTHENTICATED
    OWNER_AUTHENTICATED -> STEP_UP_REQUIRED -> OWNER_AUTHENTICATED
    any -> SESSION_EXPIRED (timeout) / REVOKED (owner removed)

Only ``complete_owner_auth`` creates an owner session and it needs an
``OwnerProof``, which only the owner-authentication code paths can mint
(``mint_owner_proof``). ``verify_task_credential`` is a different function with a
different result type and never touches the session: a guest who knows an app's
password is still a guest.

This module has no cloud dependency and no new package; ``guard()`` consults it
only when a Guest session has been started explicitly, so default behaviour is
unchanged until the later phases switch Guest Mode on.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

ROLE_OWNER, ROLE_GUEST, ROLE_SYSTEM = "owner", "guest", "system"

UNAUTHENTICATED = "UNAUTHENTICATED"
GUEST = "GUEST"
OWNER_AUTHENTICATING = "OWNER_AUTHENTICATING"
OWNER_AUTHENTICATED = "OWNER_AUTHENTICATED"
STEP_UP_REQUIRED = "STEP_UP_REQUIRED"
SESSION_EXPIRED = "SESSION_EXPIRED"
REVOKED = "REVOKED"

OWNER_SESSION_SECONDS = 12 * 3600
GUEST_SESSION_SECONDS = 4 * 3600
STEP_UP_WINDOW_SECONDS = 300

_ALLOWED = {
    UNAUTHENTICATED: {GUEST, OWNER_AUTHENTICATING},
    GUEST: {OWNER_AUTHENTICATING, SESSION_EXPIRED},
    OWNER_AUTHENTICATING: {OWNER_AUTHENTICATED, GUEST, UNAUTHENTICATED},
    OWNER_AUTHENTICATED: {STEP_UP_REQUIRED, SESSION_EXPIRED, REVOKED, GUEST},
    STEP_UP_REQUIRED: {OWNER_AUTHENTICATED, SESSION_EXPIRED, REVOKED, GUEST},
    SESSION_EXPIRED: {UNAUTHENTICATED, GUEST, OWNER_AUTHENTICATING},
    REVOKED: {UNAUTHENTICATED, GUEST},
}

# Tools a Guest may use. Everything else is denied (default-deny), whatever tier it has.
GUEST_ALLOWED_TOOLS = frozenset({"weather_report", "web_search", "quiz", "battery_status"})

# Permission categories (docs/SECURITY_V2_ARCHITECTURE.md). Unknown tools map to "unknown"
# and are owner-only.
_CATEGORY = {
    "run_command": "shell_execution", "files": "file_management", "file_controller": "file_management",
    "file_processor": "file_management", "software": "computer_control", "ui_automate": "computer_control",
    "computer_control": "computer_control", "computer_settings": "computer_control",
    "desktop": "computer_control", "desktop_control": "computer_control", "desktop_automation": "computer_control",
    "open": "computer_control", "open_app": "computer_control", "phone_control": "computer_control",
    "browser_control": "browser_automation", "mcp": "plugin_execution", "skills": "plugin_execution",
    "autonomous_task": "task_automation", "proactive_triggers": "task_automation", "routine": "task_automation",
    "reminder": "task_automation", "personal_memory": "personal_data", "recall_memory": "owner_memory",
    "save_memory": "owner_memory", "facts": "owner_memory", "rules": "owner_memory",
    "standing_orders": "owner_memory", "jarvis_settings": "settings_write", "self_heal": "security_management",
    "self_update": "security_management", "email": "personal_data", "email_gmail": "personal_data",
    "calendar": "personal_data", "send_message": "personal_data", "weather_report": "general_chat",
    "web_search": "general_chat", "quiz": "general_chat", "battery_status": "general_chat",
}


def category_for(tool: str) -> str:
    return _CATEGORY.get(str(tool), "unknown")


class IdentityError(RuntimeError):
    """An identity transition that is not allowed."""


@dataclass(frozen=True)
class OwnerProof:
    """Evidence that an owner credential check just succeeded. Minted by owner auth only."""
    owner_id: str
    method: str                     # "pin" | "voice" | "voice+pin"
    strength: int                   # 1 = single factor, 2 = two factors
    issued: float = field(default_factory=time.time)
    _nonce: str = field(default_factory=lambda: secrets.token_hex(8), repr=False)


@dataclass(frozen=True)
class Session:
    session_id: str
    role: str
    state: str
    owner_id: str = ""
    strength: int = 0
    started: float = 0.0
    expires: float = 0.0
    step_up_until: float = 0.0


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    category: str = ""


def mint_owner_proof(owner_id: str, method: str, *, strength: int = 1) -> OwnerProof:
    """Called by the owner-authentication code (PIN / Voice ID success) and nowhere else."""
    if not owner_id or method not in {"pin", "voice", "voice+pin"}:
        raise IdentityError("an owner proof needs an owner id and a real authentication method")
    return OwnerProof(owner_id, method, max(1, int(strength)))


class IdentityManager:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.RLock()
        self._revoked: set[str] = set()
        self._session = Session(secrets.token_hex(8), ROLE_GUEST, UNAUTHENTICATED)
        self._explicit_guest = False

    # ── reading ──────────────────────────────────────────────────────────────
    def current(self) -> Session:
        with self._lock:
            self._expire_locked()
            return self._session

    def guest_mode_active(self) -> bool:
        """True only after start_guest(): guard() applies Guest rules from then on."""
        with self._lock:
            self._expire_locked()
            return self._explicit_guest and self._session.role == ROLE_GUEST

    # ── transitions ──────────────────────────────────────────────────────────
    def _move(self, new_state: str, **changes) -> Session:
        old = self._session
        if new_state != old.state and new_state not in _ALLOWED.get(old.state, set()):
            raise IdentityError(f"{old.state} -> {new_state} is not an allowed transition")
        self._session = Session(**{**old.__dict__, "state": new_state, **changes})
        return self._session

    def _expire_locked(self) -> None:
        s = self._session
        if s.expires and self._clock() >= s.expires and s.state in {GUEST, OWNER_AUTHENTICATED, STEP_UP_REQUIRED}:
            self._session = Session(secrets.token_hex(8), ROLE_GUEST, SESSION_EXPIRED)
            self._explicit_guest = False
        elif s.state == OWNER_AUTHENTICATED and s.owner_id in self._revoked:
            self._session = Session(secrets.token_hex(8), ROLE_GUEST, REVOKED)
            self._explicit_guest = False

    def start_guest(self) -> Session:
        with self._lock:
            self._expire_locked()
            now = self._clock()
            self._session = Session(secrets.token_hex(8), ROLE_GUEST, UNAUTHENTICATED)
            self._move(GUEST, started=now, expires=now + GUEST_SESSION_SECONDS)
            self._explicit_guest = True
            return self._session

    def begin_owner_auth(self) -> Session:
        with self._lock:
            self._expire_locked()
            return self._move(OWNER_AUTHENTICATING)

    def fail_owner_auth(self) -> Session:
        with self._lock:
            if self._session.state == OWNER_AUTHENTICATING:
                self._session = Session(secrets.token_hex(8), ROLE_GUEST, UNAUTHENTICATED)
            return self._session

    def complete_owner_auth(self, proof: OwnerProof) -> Session:
        """The only way to an owner session. Anything but an OwnerProof is refused."""
        if not isinstance(proof, OwnerProof):
            raise IdentityError("owner sessions need an OwnerProof from owner authentication")
        with self._lock:
            if proof.owner_id in self._revoked:
                raise IdentityError("this owner has been revoked")
            if self._session.state != OWNER_AUTHENTICATING:
                raise IdentityError("owner authentication was not started")
            now = self._clock()
            self._session = Session(secrets.token_hex(8), ROLE_OWNER, OWNER_AUTHENTICATING)
            self._explicit_guest = False
            return self._move(OWNER_AUTHENTICATED, owner_id=proof.owner_id, strength=proof.strength,
                              started=now, expires=now + OWNER_SESSION_SECONDS)

    def require_step_up(self) -> Session:
        with self._lock:
            self._expire_locked()
            return self._move(STEP_UP_REQUIRED, step_up_until=0.0)

    def complete_step_up(self, proof: OwnerProof) -> Session:
        with self._lock:
            s = self.current()
            if s.state != STEP_UP_REQUIRED or not isinstance(proof, OwnerProof) or proof.owner_id != s.owner_id:
                raise IdentityError("step-up must come from the same signed-in owner")
            return self._move(OWNER_AUTHENTICATED, strength=max(s.strength, proof.strength),
                              step_up_until=self._clock() + STEP_UP_WINDOW_SECONDS)

    def revoke_owner(self, owner_id: str) -> None:
        with self._lock:
            self._revoked.add(str(owner_id))
            self._expire_locked()

    def end_session(self) -> Session:
        with self._lock:
            self._session = Session(secrets.token_hex(8), ROLE_GUEST, UNAUTHENTICATED)
            self._explicit_guest = False
            return self._session

    # ── authorization ────────────────────────────────────────────────────────
    def authorize(self, tool: str, tier: str, *, needs_strong: bool = False) -> Decision:
        """Default-deny: an owner needs a live session; a Guest only gets the allowlist."""
        category = category_for(tool)
        with self._lock:
            s = self.current()
            if s.role == ROLE_OWNER and s.state in {OWNER_AUTHENTICATED, STEP_UP_REQUIRED}:
                if s.owner_id in self._revoked:
                    return Decision(False, "owner revoked", category)
                if s.state == STEP_UP_REQUIRED or (needs_strong and s.strength < 2
                                                   and self._clock() >= s.step_up_until):
                    return Decision(False, "step-up authentication required", category)
                return Decision(True, "owner session", category)
            if s.role == ROLE_GUEST and tool in GUEST_ALLOWED_TOOLS and tier == "SAFE":
                return Decision(True, "guest allowlist", category)
            return Decision(False, f"{s.role} session may not use {category}", category)


# ── task credentials: deliberately unable to touch identity ──────────────────
@dataclass(frozen=True)
class TaskCredentialResult:
    ok: bool
    task: str                       # what the password unlocks; never an identity


def verify_task_credential(task: str, supplied: str, expected_check: Callable[[str], bool]) -> TaskCredentialResult:
    """Check a password that belongs to one application or website.

    Returns a TaskCredentialResult only. It has no access to the IdentityManager
    and cannot produce an OwnerProof, so success here never changes who the user is.
    """
    try:
        ok = bool(expected_check(supplied))
    except Exception:
        ok = False
    return TaskCredentialResult(ok, str(task))


_manager: Optional[IdentityManager] = None
_manager_lock = threading.Lock()


def get_identity_manager() -> IdentityManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = IdentityManager()
        return _manager


def reset_for_tests(manager: Optional[IdentityManager] = None) -> None:
    global _manager
    with _manager_lock:
        _manager = manager
