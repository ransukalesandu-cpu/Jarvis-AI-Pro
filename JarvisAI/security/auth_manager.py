"""
Owner access state machine for JARVIS.

No default PIN is created. FULL_ACCESS is always session-only and is never restored
after a process restart. Privacy Lock state and its cooldown are persisted.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerificationError
    _ARGON2_AVAILABLE = True
except ImportError:
    PasswordHasher = None
    VerificationError = Exception
    _ARGON2_AVAILABLE = False

try:
    from security.voice_auth import SpeakerAuthenticator, COSINE_THRESHOLD
except Exception:
    SpeakerAuthenticator = None
    COSINE_THRESHOLD = 0.80

RESTRICTED_MODE = "RESTRICTED_MODE"
FULL_ACCESS_MODE = "FULL_ACCESS_MODE"
CHALLENGE_MODE = "CHALLENGE_MODE"
PRIVACY_LOCK = "PRIVACY_LOCK"

DEFAULT_VAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "pin_vault.dat"
DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "config" / "auth_state.json"
MAX_FAILED_PIN_ATTEMPTS = 3
DEFAULT_COOLDOWN_SECONDS = 60


def ensure_restricted_dir(path: Path | str) -> Path:
    """Ensure directory exists with restricted permissions (0700 on POSIX)."""
    target = Path(path)
    os.makedirs(target, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(target, 0o700)
        except OSError:
            pass
    return target


def configured_cooldown_seconds(value: str | None = None) -> int:
    """Read the 1–5 minute lock duration. Invalid values fail back to 1 minute."""
    raw = os.environ.get("JARVIS_PRIVACY_LOCK_MINUTES", "1") if value is None else value
    try:
        minutes = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_COOLDOWN_SECONDS
    if not 1 <= minutes <= 5:
        return DEFAULT_COOLDOWN_SECONDS
    return minutes * 60


def _dpapi_protect(data: bytes) -> bytes:
    """Protect PIN-hash metadata with Windows DPAPI. Never fall back to plaintext."""
    if sys.platform != "win32":
        return data
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_byte))]
    source_buffer = ctypes.create_string_buffer(data, len(data))
    source = DATA_BLOB(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    dest = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "JARVIS_PIN_VAULT", None, None, None, 0, ctypes.byref(dest)
    )
    if not ok:
        raise RuntimeError("Windows DPAPI could not encrypt the JARVIS PIN vault.")
    try:
        return ctypes.string_at(dest.pbData, dest.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dest.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    """Unprotect Windows DPAPI data; fail closed if the Windows call fails."""
    if sys.platform != "win32":
        return data
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_byte))]
    source_buffer = ctypes.create_string_buffer(data, len(data))
    source = DATA_BLOB(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    dest = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(dest)
    )
    if not ok:
        raise RuntimeError("Windows DPAPI could not decrypt the JARVIS PIN vault.")
    try:
        return ctypes.string_at(dest.pbData, dest.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dest.pbData)


def lock_workstation() -> bool:
    """Lock the current Windows workstation without attempting to unlock it later."""
    try:
        from security.lockdown import lock_workstation as _lock_ws
        success, err = _lock_ws()
        if not success and sys.platform == "win32":
            print(f"[AuthManager] LockWorkStation failed with error code: {err}")
        return success
    except Exception:
        if sys.platform != "win32":
            return False
        try:
            res = ctypes.windll.user32.LockWorkStation()
            if res == 0:
                err = ctypes.GetLastError()
                print(f"[AuthManager] LockWorkStation returned 0; GetLastError={err}")
                return False
            return True
        except Exception as exc:
            print(f"[AuthManager] LockWorkStation failed: {exc}")
            return False


class AuthManager:
    """PIN and voice-derived owner access state machine; no network API can set FULL_ACCESS."""

    def __init__(
        self,
        vault_path: str | Path | None = None,
        state_path: str | Path | None = None,
        voice_authenticator=None,
        cooldown_seconds: int | None = None,
    ):
        self.vault_path = Path(vault_path) if vault_path else DEFAULT_VAULT_PATH
        self.state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self.voice_authenticator = voice_authenticator
        configured = configured_cooldown_seconds() if cooldown_seconds is None else int(cooldown_seconds)
        self.cooldown_seconds = configured if 60 <= configured <= 300 else DEFAULT_COOLDOWN_SECONDS
        self._lock = threading.RLock()
        self._privacy_lock_notifier: Optional[Callable[[str], None]] = None
        self.failed_pin_attempts = 0
        self.state = RESTRICTED_MODE
        self.lock_until = 0.0
        self._requires_owner_reauth = False
        self._auth_method: str | None = None
        # Separate in-memory factors gate privileged host cloud access. Never persisted.
        self._pin_verified = False
        self._voice_verified = False
        self._hasher = PasswordHasher() if _ARGON2_AVAILABLE else None
        self._load_persistent_state()

    def _load_persistent_state(self) -> None:
        """Restore lockout only; a previous FULL_ACCESS session never survives restart."""
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            saved_state = str(data.get("state", RESTRICTED_MODE))
            self.lock_until = float(data.get("lock_until", 0.0))
            self.failed_pin_attempts = max(0, int(data.get("failed_pin_attempts", 0)))
            saved_reauth = bool(data.get("requires_owner_reauth", False))
            now = time.time()
            if saved_state == PRIVACY_LOCK and now < self.lock_until:
                self.state = PRIVACY_LOCK
                self._requires_owner_reauth = True
            elif saved_state == PRIVACY_LOCK or saved_reauth:
                self.state = CHALLENGE_MODE
                self.lock_until = 0.0
                self.failed_pin_attempts = 0
                self._requires_owner_reauth = True
                self._save_persistent_state()
            else:
                # All non-lock sessions, particularly FULL_ACCESS, restart restricted.
                self.state = RESTRICTED_MODE
                self.lock_until = 0.0
                self.failed_pin_attempts = 0
                self._requires_owner_reauth = False
                self._auth_method = None
                self._save_persistent_state()
        except Exception:
            # Corrupt state must never restore access.
            self.state = RESTRICTED_MODE
            self.lock_until = 0.0
            self.failed_pin_attempts = 0
            self._requires_owner_reauth = True

    def _save_persistent_state(self) -> None:
        payload = {
            "state": self.state,
            "lock_until": self.lock_until,
            "failed_pin_attempts": self.failed_pin_attempts,
            "requires_owner_reauth": self._requires_owner_reauth,
            "updated_at": time.time(),
        }
        ensure_restricted_dir(self.state_path.parent)
        temp = self.state_path.with_name(self.state_path.name + ".tmp")
        try:
            temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            if os.name != "nt":
                os.chmod(temp, 0o600)
            os.replace(temp, self.state_path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def get_state(self) -> str:
        with self._lock:
            if self.state == PRIVACY_LOCK and time.time() >= self.lock_until:
                # Cooldown expiry is not authentication. Remain silent until PIN re-auth.
                self.state = CHALLENGE_MODE
                self.lock_until = 0.0
                self.failed_pin_attempts = 0
                self._requires_owner_reauth = True
                self._auth_method = None
                self._save_persistent_state()
            return self.state

    def get_auth_method(self) -> str | None:
        with self._lock:
            return self._auth_method

    def set_state(self, new_state: str) -> None:
        """Set a non-owner state. FULL_ACCESS must use grant_owner_access()."""
        if new_state not in {RESTRICTED_MODE, CHALLENGE_MODE, PRIVACY_LOCK}:
            raise ValueError("Use grant_owner_access() after successful owner verification.")
        with self._lock:
            if self.state == PRIVACY_LOCK and time.time() < self.lock_until:
                return
            self.state = new_state
            self._auth_method = None
            self._voice_verified = False
            if new_state == RESTRICTED_MODE and not self._requires_owner_reauth:
                self.failed_pin_attempts = 0
            self._save_persistent_state()

    def set_privacy_lock_notifier(self, callback: Callable[[str], None] | None) -> None:
        with self._lock:
            self._privacy_lock_notifier = callback

    def is_pin_enrolled(self) -> bool:
        return self._read_hashed_pin() is not None

    def set_master_pin(self, pin: str) -> None:
        """Explicit local enrollment only. The raw PIN is never written to disk."""
        value = str(pin or "").strip()
        if not 4 <= len(value) <= 64:
            raise ValueError("PIN/password must be between 4 and 64 characters.")
        if not _ARGON2_AVAILABLE or self._hasher is None:
            raise RuntimeError("Install argon2-cffi before configuring an owner PIN.")
        hashed = self._hasher.hash(value)
        protected = _dpapi_protect(json.dumps({"hashed_pin": hashed}).encode("utf-8"))
        ensure_restricted_dir(self.vault_path.parent)
        vault_dir = ensure_restricted_dir(self.vault_path.parent.parent / "security" / "vault")
        temp = self.vault_path.with_name(self.vault_path.name + ".tmp")
        try:
            temp.write_bytes(protected)
            if os.name != "nt":
                os.chmod(temp, 0o600)
            os.replace(temp, self.vault_path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _read_hashed_pin(self) -> Optional[str]:
        try:
            if not self.vault_path.is_file():
                return None
            payload = json.loads(_dpapi_unprotect(self.vault_path.read_bytes()).decode("utf-8"))
            value = payload.get("hashed_pin")
            return value if isinstance(value, str) and value.startswith("$argon2") else None
        except Exception:
            return None

    def grant_owner_access(self, method: str, *, verified_live: bool = False) -> None:
        """Grant after local PIN verification or explicitly verified live owner speech."""
        if method not in {"pin", "voice"}:
            raise ValueError("Owner access must be verified by PIN or Voice ID.")
        if method == "voice" and verified_live is not True:
            raise PermissionError("Voice authorization requires verified live speech.")
        with self._lock:
            if self.state == PRIVACY_LOCK and time.time() < self.lock_until:
                raise PermissionError("Privacy Lock cooldown has not expired.")
            if self._requires_owner_reauth and method != "pin":
                raise PermissionError("Privacy Lock requires PIN re-authentication.")
            if method == "pin":
                self._pin_verified = True
                self._voice_verified = False
            elif method == "voice":
                self._voice_verified = True
            self.state = FULL_ACCESS_MODE
            self._auth_method = method
            self._requires_owner_reauth = False
            self.lock_until = 0.0
            self.failed_pin_attempts = 0
            self._save_persistent_state()

    def verify_pin(self, pin: str) -> bool:
        """Verify a typed PIN/password. Callers must intercept it before cloud submission/logging."""
        state = self.get_state()
        if state == PRIVACY_LOCK or not self.is_pin_enrolled() or self._hasher is None:
            return False
        hashed = self._read_hashed_pin()
        if not hashed:
            return False
        try:
            valid = bool(self._hasher.verify(hashed, str(pin or "").strip()))
        except Exception:
            valid = False
        if valid:
            self.grant_owner_access("pin")
            return True
        with self._lock:
            self._pin_verified = False
            self._voice_verified = False
            self.failed_pin_attempts += 1
            attempts = self.failed_pin_attempts
            self._save_persistent_state()
        if attempts >= MAX_FAILED_PIN_ATTEMPTS:
            self.trigger_privacy_lock()
        return False

    def process_voice_result(self, is_master: bool, similarity: float, is_live: bool = False, is_stranger: bool = False) -> tuple[str, str]:
        """Handle an already-computed enrolled Voice ID result; never voice-unlock after Privacy Lock."""
        state = self.get_state()
        if state == PRIVACY_LOCK or self.requires_owner_reauthentication():
            return state, "Privacy Lock requires owner PIN re-authentication."
        method = self.get_auth_method()
        # A PIN-authenticated session still needs a successful live Voice ID result
        # before host-only cloud privileges are enabled.
        if is_master is True and is_live is True and math.isfinite(similarity) and similarity >= COSINE_THRESHOLD:
            self.grant_owner_access("voice", verified_live=True)
            return FULL_ACCESS_MODE, "Owner voice verified."
        if is_stranger:
            self.set_state(RESTRICTED_MODE)
            return RESTRICTED_MODE, "Unrecognized speaker; basic access only."
        self.set_state(CHALLENGE_MODE)
        return CHALLENGE_MODE, "Live voice not verified. Enter the owner PIN/password using the local input."

    def verify_owner_voice(self, audio, sample_rate: int = 16000) -> tuple[bool, float, bool]:
        """Require both an encrypted owner match and validated anti-spoof result."""
        try:
            if self.voice_authenticator is None:
                if SpeakerAuthenticator is None:
                    return False, 0.0, False
                self.voice_authenticator = SpeakerAuthenticator()
            matched, score, live = self.voice_authenticator.verify(audio, sample_rate=sample_rate)
            score = float(score)
            authorized = matched is True and live is True and math.isfinite(score) and score >= COSINE_THRESHOLD
            return authorized, score if math.isfinite(score) else 0.0, live is True
        except Exception:
            return False, 0.0, False

    def process_voice_authentication(self, audio, sample_rate: int = 16000) -> tuple[str, str]:
        matched, score, live = self.verify_owner_voice(audio, sample_rate=sample_rate)
        return self.process_voice_result(matched, score, live, is_stranger=not matched)

    def is_privacy_lock_active(self) -> bool:
        return self.get_state() == PRIVACY_LOCK

    def requires_owner_reauthentication(self) -> bool:
        self.get_state()
        with self._lock:
            return self._requires_owner_reauth

    def owner_factors_verified(self) -> bool:
        """True only after both a valid PIN and a live enrolled-speaker check this process."""
        with self._lock:
            return self._pin_verified and self._voice_verified

    def is_owner_access_allowed(self) -> bool:
        return self.get_state() == FULL_ACCESS_MODE and not self.requires_owner_reauthentication()

    def is_silent(self) -> bool:
        return self.is_privacy_lock_active() or self.requires_owner_reauthentication()

    def needs_pin(self) -> bool:
        state = self.get_state()
        return (
            state != PRIVACY_LOCK
            and self.is_pin_enrolled()
            and (state == CHALLENGE_MODE or self.requires_owner_reauthentication())
        )

    def cooldown_remaining(self) -> int:
        self.get_state()
        with self._lock:
            return max(0, int(self.lock_until - time.time())) if self.state == PRIVACY_LOCK else 0

    def trigger_privacy_lock(self, reason: str = "three incorrect owner PIN/password attempts") -> str:
        """Persist a three-strike lock, lock Windows, then notify connected paired clients."""
        message = "JARVIS Privacy Lock activated on your laptop. Owner verification failed three times. Private access is blocked."
        with self._lock:
            now = time.time()
            if self.state == PRIVACY_LOCK and now < self.lock_until:
                return message
            self.state = PRIVACY_LOCK
            self._auth_method = None
            self._pin_verified = False
            self._voice_verified = False
            self._requires_owner_reauth = True
            self.lock_until = now + self.cooldown_seconds
            self.failed_pin_attempts = max(MAX_FAILED_PIN_ATTEMPTS, self.failed_pin_attempts)
            self._save_persistent_state()
            notifier = self._privacy_lock_notifier
        lock_workstation()
        print("[AuthManager] Privacy Lock activated.")
        if notifier:
            try:
                notifier(message)
            except Exception as exc:
                print(f"[AuthManager] Privacy Lock notification could not be scheduled: {type(exc).__name__}")
        return message
