"""Security V2 Phase 2: more than one owner, each with their own identity.

Every owner has a UUID, a display name, an Argon2 PIN/password hash, an optional
Voice ID profile of their own (role ``owner-<id8>`` in core/voice_id.py, never a
shared profile), an enrolment status and a revocation status. Sessions are minted
per owner through ``identity.OwnerProof``.

Administration model (also in docs/SECURITY_V2_ARCHITECTURE.md):

* The first owner created through the local setup script is the **primary
  administrator**. Only administrators can add, revoke or promote owners.
* Every owner has normal owner capabilities; "admin" only adds owner management.
* Management actions need a live owner session *and* a fresh step-up (PIN re-entry).
* The last active administrator cannot be revoked or demoted.
* A one-time **recovery code** (shown once at first setup, stored only as a hash)
  restores an administrator's access if every PIN is lost or the admin is locked
  out. Using it rotates the code.

PINs and recovery codes are collected by local console code only (a getpass
prompt or the HUD PIN field), never through a voice tool, so they are not sent to
cloud AI. Nothing here logs a PIN, hash, recovery code or voice vector.
"""
from __future__ import annotations

import secrets
import threading
import time
import uuid
from typing import Any, Callable, Optional

from jarvis.core import identity
from jarvis.core.identity import IdentityManager, OwnerProof, Session

MIN_SECRET, MAX_SECRET = 4, 64
MAX_NAME = 40
MAX_OWNERS = 8
FAILS_BEFORE_LOCK = 3
BASE_LOCK_SECONDS = 60
MAX_LOCK_SECONDS = 900
MAX_RECOVERY_ATTEMPTS = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS security_owners (
    owner_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    voice_role TEXT NOT NULL,
    voice_enrolled INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created REAL NOT NULL,
    updated REAL NOT NULL,
    revoked_at REAL
);
CREATE TABLE IF NOT EXISTS security_owner_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class OwnerError(RuntimeError):
    """A refused owner-management action (message is safe to show)."""


def _default_hasher():
    from argon2 import PasswordHasher
    return PasswordHasher()


def _audit(event: str, owner_id: str, decision: str, detail: str = "") -> None:
    """Record to the tamper-evident ledger; never include secrets. Failure must not break auth."""
    try:
        from jarvis.core import security
        security.audit(event, f"owner:{owner_id[:8]}" if owner_id else "owner", "SENSITIVE", decision, detail)
    except Exception:
        from jarvis.core import failsoft
        failsoft.suppress("owner_registry:audit")


class OwnerRegistry:
    def __init__(self, store=None, *, hasher=None, clock: Callable[[], float] = time.time,
                 voice_verify: Optional[Callable[[Any, str], tuple[bool, float]]] = None,
                 voice_enroll: Optional[Callable[[Any, str], None]] = None,
                 voice_remove: Optional[Callable[[str], None]] = None):
        if store is None:
            from jarvis.core.owner_store import get_owner_store
            store = get_owner_store()
        store.ensure_schema(_SCHEMA)
        self._store = store
        self._hasher = hasher or _default_hasher()
        self._clock = clock
        self._lock = threading.RLock()
        self._fails: dict[str, tuple[int, float]] = {}      # owner_id -> (failures, locked_until)
        self._recovery_fails = 0
        self._voice_verify = voice_verify
        self._voice_enroll = voice_enroll
        self._voice_remove = voice_remove

    # ── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _secret(value: str, what: str) -> str:
        value = str(value or "").strip()
        if not MIN_SECRET <= len(value) <= MAX_SECRET:
            raise OwnerError(f"{what} must be {MIN_SECRET}-{MAX_SECRET} characters")
        return value

    @staticmethod
    def _name(value: str) -> str:
        value = " ".join(str(value or "").split())
        if not value or len(value) > MAX_NAME:
            raise OwnerError(f"name must be 1-{MAX_NAME} characters")
        return value

    def _rows(self, where: str = "", args: tuple = ()) -> list[dict]:
        with self._store.connect() as db:
            rows = db.execute(f"SELECT * FROM security_owners {where} ORDER BY created", args).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _public(row: dict) -> dict:
        return {"owner_id": row["owner_id"], "display_name": row["display_name"],
                "is_admin": bool(row["is_admin"]), "voice_enrolled": bool(row["voice_enrolled"]),
                "status": row["status"]}

    def _get(self, owner_id: str) -> Optional[dict]:
        rows = self._rows("WHERE owner_id=?", (str(owner_id),))
        return rows[0] if rows else None

    def _active_admins(self) -> list[dict]:
        return self._rows("WHERE status='active' AND is_admin=1")

    # ── reading ──────────────────────────────────────────────────────────────
    def has_owners(self) -> bool:
        return bool(self._rows("WHERE status='active'"))

    def list_owners(self) -> list[dict]:
        return [self._public(r) for r in self._rows()]

    # ── bootstrap and recovery ───────────────────────────────────────────────
    def bootstrap_first_owner(self, name: str, pin: str) -> tuple[dict, str]:
        """Create the primary administrator. Refused once any owner exists."""
        with self._lock:
            if self._rows():
                raise OwnerError("an owner already exists; use the signed-in owner flow to add another")
            owner = self._insert(self._name(name), self._secret(pin, "PIN/password"), admin=True)
            code = self._new_recovery_code()
            _audit("owner_bootstrap", owner["owner_id"], "ran", "first owner created")
            return owner, code

    def _insert(self, name: str, pin: str, *, admin: bool) -> dict:
        if len(self._rows()) >= MAX_OWNERS:
            raise OwnerError(f"at most {MAX_OWNERS} owners are supported")
        owner_id = str(uuid.uuid4())
        now = self._clock()
        with self._store.connect() as db:
            db.execute("INSERT INTO security_owners(owner_id, display_name, pin_hash, is_admin, voice_role,"
                       " created, updated) VALUES (?,?,?,?,?,?,?)",
                       (owner_id, name, self._hasher.hash(pin), int(admin), f"owner-{owner_id[:8]}", now, now))
        return self._public(self._get(owner_id))  # type: ignore[arg-type]

    def _new_recovery_code(self) -> str:
        code = secrets.token_urlsafe(18)
        with self._store.connect() as db:
            db.execute("INSERT INTO security_owner_meta(key, value) VALUES ('recovery_hash', ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (self._hasher.hash(code),))
        return code

    def recover_admin(self, recovery_code: str, new_pin: str, *, owner_id: str = "") -> tuple[dict, str]:
        """Restore access with the one-time recovery code. Rotates the code; rate-limited."""
        with self._lock:
            if self._recovery_fails >= MAX_RECOVERY_ATTEMPTS:
                raise OwnerError("too many wrong recovery codes in this run; restart JARVIS and try again")
            with self._store.connect() as db:
                row = db.execute("SELECT value FROM security_owner_meta WHERE key='recovery_hash'").fetchone()
            ok = False
            if row:
                try:
                    ok = bool(self._hasher.verify(row["value"], str(recovery_code or "").strip()))
                except Exception:
                    ok = False
            if not ok:
                self._recovery_fails += 1
                _audit("owner_recovery", owner_id, "denied", "wrong recovery code")
                raise OwnerError("recovery code not accepted")
            pin = self._secret(new_pin, "PIN/password")
            admins = self._rows("WHERE is_admin=1")
            target = self._get(owner_id) if owner_id else (admins[0] if admins else None)
            if not target or not target["is_admin"]:
                raise OwnerError("recovery restores an administrator account; none matched")
            now = self._clock()
            with self._store.connect() as db:
                db.execute("UPDATE security_owners SET pin_hash=?, status='active', revoked_at=NULL, updated=? "
                           "WHERE owner_id=?", (self._hasher.hash(pin), now, target["owner_id"]))
            self._fails.pop(target["owner_id"], None)
            self._recovery_fails = 0
            _audit("owner_recovery", target["owner_id"], "ran", "administrator restored")
            return self._public(self._get(target["owner_id"])), self._new_recovery_code()  # type: ignore[arg-type]

    # ── authentication (returns proofs; sessions are created by login()) ─────
    def _locked_for(self, owner_id: str) -> int:
        fails, until = self._fails.get(owner_id, (0, 0.0))
        return max(0, int(until - self._clock()))

    def _note_failure(self, owner_id: str) -> None:
        fails, _ = self._fails.get(owner_id, (0, 0.0))
        fails += 1
        until = 0.0
        if fails >= FAILS_BEFORE_LOCK:
            span = min(MAX_LOCK_SECONDS, BASE_LOCK_SECONDS * 2 ** (fails - FAILS_BEFORE_LOCK))
            until = self._clock() + span
        self._fails[owner_id] = (fails, until)
        _audit("owner_auth_failed", owner_id, "denied", "wrong credential")

    def authenticate_pin(self, pin: str, owner_id: str = "") -> Optional[OwnerProof]:
        """Check a PIN against one owner, or against every active owner when no id is given."""
        with self._lock:
            candidates = ([self._get(owner_id)] if owner_id else self._rows("WHERE status='active'"))
            for row in candidates:
                if not row or row["status"] != "active":
                    continue
                if self._locked_for(row["owner_id"]):
                    continue
                try:
                    good = bool(self._hasher.verify(row["pin_hash"], str(pin or "").strip()))
                except Exception:
                    good = False
                if good:
                    self._fails.pop(row["owner_id"], None)
                    _audit("owner_auth", row["owner_id"], "ran", "pin accepted")
                    return identity.mint_owner_proof(row["owner_id"], "pin", strength=1)
                if owner_id:
                    self._note_failure(row["owner_id"])
            if not owner_id:
                for row in candidates:                       # a wrong guess counts against everyone it could have been
                    if row and not self._locked_for(row["owner_id"]):
                        self._note_failure(row["owner_id"])
            return None

    def authenticate_voice(self, audio: Any, owner_id: str = "") -> Optional[OwnerProof]:
        """Voice proof for one owner (or the best matching active owner). Fails closed."""
        verify = self._voice_verify
        if verify is None:
            from jarvis.core import voice_id
            if not (voice_id.is_enabled() and voice_id.backend_ready()):
                return None                                  # never fall back to "everyone is the owner"
            verify = voice_id.verify
        with self._lock:
            rows = [self._get(owner_id)] if owner_id else self._rows("WHERE status='active' AND voice_enrolled=1")
            best: tuple[float, Optional[dict]] = (0.0, None)
            for row in rows:
                if not row or row["status"] != "active" or not row["voice_enrolled"] or self._locked_for(row["owner_id"]):
                    continue
                matched, score = verify(audio, row["voice_role"])
                if matched and score > best[0]:
                    best = (score, row)
            if best[1] is None:
                return None
            _audit("owner_auth", best[1]["owner_id"], "ran", "voice accepted")
            return identity.mint_owner_proof(best[1]["owner_id"], "voice", strength=1)

    def login(self, manager: IdentityManager, proof: Optional[OwnerProof]) -> Session:
        if proof is None:
            raise OwnerError("authentication failed")
        row = self._get(proof.owner_id)
        if not row or row["status"] != "active":
            raise OwnerError("this owner is not active")
        manager.begin_owner_auth()
        return manager.complete_owner_auth(proof)

    def lock_seconds_remaining(self, owner_id: str) -> int:
        return self._locked_for(owner_id)

    # ── administration ───────────────────────────────────────────────────────
    def _require_admin(self, manager: IdentityManager) -> dict:
        s = manager.current()
        if s.role != identity.ROLE_OWNER or s.state != identity.OWNER_AUTHENTICATED:
            raise OwnerError("sign in as an owner first")
        row = self._get(s.owner_id)
        if not row or row["status"] != "active" or not row["is_admin"]:
            raise OwnerError("only an owner administrator can manage owners")
        if self._clock() >= s.step_up_until:
            raise OwnerError("re-enter your PIN to confirm this change")
        return row

    def confirm_step_up(self, manager: IdentityManager, pin: str) -> Session:
        s = manager.current()
        if s.role != identity.ROLE_OWNER:
            raise OwnerError("sign in as an owner first")
        proof = self.authenticate_pin(pin, owner_id=s.owner_id)
        if proof is None:
            raise OwnerError("PIN not accepted")
        manager.require_step_up()
        return manager.complete_step_up(proof)

    def add_owner(self, manager: IdentityManager, name: str, pin: str, *, admin: bool = False) -> dict:
        with self._lock:
            actor = self._require_admin(manager)
            owner = self._insert(self._name(name), self._secret(pin, "PIN/password"), admin=bool(admin))
            _audit("owner_added", actor["owner_id"], "ran", f"added {owner['owner_id'][:8]} admin={bool(admin)}")
            return owner

    def set_admin(self, manager: IdentityManager, owner_id: str, admin: bool) -> dict:
        with self._lock:
            actor = self._require_admin(manager)
            target = self._get(owner_id)
            if not target or target["status"] != "active":
                raise OwnerError("no such active owner")
            if not admin and target["is_admin"] and len(self._active_admins()) <= 1:
                raise OwnerError("the last administrator cannot be demoted")
            with self._store.connect() as db:
                db.execute("UPDATE security_owners SET is_admin=?, updated=? WHERE owner_id=?",
                           (int(bool(admin)), self._clock(), target["owner_id"]))
            _audit("owner_admin_changed", actor["owner_id"], "ran", f"{target['owner_id'][:8]} admin={bool(admin)}")
            return self._public(self._get(owner_id))  # type: ignore[arg-type]

    def revoke_owner(self, manager: IdentityManager, owner_id: str) -> dict:
        with self._lock:
            actor = self._require_admin(manager)
            target = self._get(owner_id)
            if not target or target["status"] != "active":
                raise OwnerError("no such active owner")
            if target["is_admin"] and len(self._active_admins()) <= 1:
                raise OwnerError("the last administrator cannot be revoked; add another administrator first")
            now = self._clock()
            with self._store.connect() as db:
                db.execute("UPDATE security_owners SET status='revoked', revoked_at=?, updated=?, voice_enrolled=0 "
                           "WHERE owner_id=?", (now, now, target["owner_id"]))
            manager.revoke_owner(target["owner_id"])
            self._remove_voice(target["voice_role"])
            _audit("owner_revoked", actor["owner_id"], "ran", f"revoked {target['owner_id'][:8]}")
            return self._public(self._get(owner_id))  # type: ignore[arg-type]

    def change_pin(self, owner_id: str, old_pin: str, new_pin: str) -> None:
        with self._lock:
            if self.authenticate_pin(old_pin, owner_id=owner_id) is None:
                raise OwnerError("current PIN not accepted")
            pin = self._secret(new_pin, "PIN/password")
            with self._store.connect() as db:
                db.execute("UPDATE security_owners SET pin_hash=?, updated=? WHERE owner_id=?",
                           (self._hasher.hash(pin), self._clock(), str(owner_id)))
            _audit("owner_pin_changed", owner_id, "ran", "pin changed")

    # ── voice profile (one per owner) ────────────────────────────────────────
    def _remove_voice(self, role: str) -> None:
        remover = self._voice_remove
        if remover is None:
            from jarvis.core import voice_id
            remover = voice_id.remove_profile
        try:
            remover(role)
        except Exception:
            from jarvis.core import failsoft
            failsoft.suppress("owner_registry:remove_voice")

    def enroll_voice(self, owner_id: str, audio: Any) -> dict:
        """Create or replace this owner's own Voice ID profile (audio is never stored)."""
        with self._lock:
            row = self._get(owner_id)
            if not row or row["status"] != "active":
                raise OwnerError("no such active owner")
            enroll = self._voice_enroll
            if enroll is None:
                from jarvis.core import voice_id
                if not voice_id.backend_ready():
                    raise OwnerError("Voice ID dependencies are not available on this computer")
                enroll = voice_id.enroll
            enroll(audio, row["voice_role"])
            with self._store.connect() as db:
                db.execute("UPDATE security_owners SET voice_enrolled=1, updated=? WHERE owner_id=?",
                           (self._clock(), row["owner_id"]))
            _audit("owner_voice_enrolled", row["owner_id"], "ran", "voice profile replaced or created")
            return self._public(self._get(owner_id))  # type: ignore[arg-type]


_registry: Optional[OwnerRegistry] = None
_registry_lock = threading.Lock()


def get_owner_registry() -> OwnerRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = OwnerRegistry()
        return _registry


def reset_for_tests(registry: Optional[OwnerRegistry] = None) -> None:
    global _registry
    with _registry_lock:
        _registry = registry

