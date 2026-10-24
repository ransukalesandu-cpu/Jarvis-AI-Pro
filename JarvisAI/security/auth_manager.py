"""
JarvisAI/security/auth_manager.py — Secure PIN Vault & Authentication State Machine.

Maintains 4 explicit authentication states:
  - RESTRICTED_MODE
  - FULL_ACCESS_MODE
  - CHALLENGE_MODE
  - PRIVACY_LOCK

Stores master PIN securely using argon2-cffi and Windows DPAPI / restricted local vault.
Enforces 3-strike Privacy Lock policy with persistent cooldown and Windows workstation lock.
"""

from __future__ import annotations

import os
import sys
import json
import time
import ctypes
from pathlib import Path
from typing import Optional

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError
    _ARGON2_AVAILABLE = True
except ImportError:
    _ARGON2_AVAILABLE = False

from security.voice_auth import SpeakerAuthenticator, COSINE_THRESHOLD

RESTRICTED_MODE = "RESTRICTED_MODE"
FULL_ACCESS_MODE = "FULL_ACCESS_MODE"
CHALLENGE_MODE = "CHALLENGE_MODE"
PRIVACY_LOCK = "PRIVACY_LOCK"

DEFAULT_VAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "pin_vault.dat"
DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "config" / "auth_state.json"
MAX_FAILED_PIN_ATTEMPTS = 3
DEFAULT_COOLDOWN_SECONDS = 300  # 5 minutes


def _dpapi_protect(data: bytes) -> bytes:
    """Protect data using Windows DPAPI. Fail closed if DPAPI fails."""
    if sys.platform != "win32":
        return data
    try:
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        in_blob = DATA_BLOB()
        in_blob.cbData = len(data)
        in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_byte))
        out_blob = DATA_BLOB()

        if ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob), "JARVIS_PIN_VAULT", None, None, None, 0, ctypes.byref(out_blob)
        ):
            buf = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return buf
        else:
            raise RuntimeError("Windows DPAPI CryptProtectData returned False.")
    except Exception as e:
        raise RuntimeError(f"Windows DPAPI encryption failed: {e}") from e


def _dpapi_unprotect(data: bytes) -> bytes:
    """Unprotect data using Windows DPAPI. Fail closed if DPAPI fails."""
    if sys.platform != "win32":
        return data
    try:
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        in_blob = DATA_BLOB()
        in_blob.cbData = len(data)
        in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_byte))
        out_blob = DATA_BLOB()

        if ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        ):
            buf = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return buf
        else:
            raise RuntimeError("Windows DPAPI CryptUnprotectData returned False.")
    except Exception as e:
        raise RuntimeError(f"Windows DPAPI decryption failed: {e}") from e


def lock_workstation() -> bool:
    """Lock the workstation (Windows user32.LockWorkStation)."""
    if sys.platform == "win32":
        try:
            return bool(ctypes.windll.user32.LockWorkStation())
        except Exception:
            return False
    return False


class AuthManager:
    """Authentication State Machine & Secure PIN Vault Manager."""

    def __init__(
        self,
        vault_path: str | Path | None = None,
        state_path: str | Path | None = None,
        voice_authenticator: SpeakerAuthenticator | None = None,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ):
        self.vault_path = Path(vault_path) if vault_path else DEFAULT_VAULT_PATH
        self.state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self.voice_authenticator = voice_authenticator or SpeakerAuthenticator()
        self.cooldown_seconds = max(60, min(300, cooldown_seconds))
        self.failed_pin_attempts = 0

        if not _ARGON2_AVAILABLE:
            raise RuntimeError("argon2-cffi package is required for secure PIN vault storage.")
        self._hasher = PasswordHasher()

        self.state = RESTRICTED_MODE
        self.lock_until = 0.0
        self._load_persistent_state()

    def _load_persistent_state(self) -> None:
        """Load state and Privacy Lock cooldown timestamp from disk."""
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                saved_state = data.get("state", RESTRICTED_MODE)
                self.lock_until = float(data.get("lock_until", 0.0))
                self.failed_pin_attempts = int(data.get("failed_pin_attempts", 0))

                now = time.time()
                if saved_state == PRIVACY_LOCK and now < self.lock_until:
                    self.state = PRIVACY_LOCK
                elif saved_state == PRIVACY_LOCK and now >= self.lock_until:
                    self.state = CHALLENGE_MODE
                    self.lock_until = 0.0
                    self.failed_pin_attempts = 0
                    self._save_persistent_state()
                else:
                    self.state = saved_state
            except Exception:
                self.state = RESTRICTED_MODE
                self.lock_until = 0.0

    def _save_persistent_state(self) -> None:
        """Save auth state to persistent json file."""
        payload = {
            "state": self.state,
            "lock_until": self.lock_until,
            "failed_pin_attempts": self.failed_pin_attempts,
            "updated_at": time.time(),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if os.name != "nt":
            try:
                os.chmod(self.state_path, 0o600)
            except OSError:
                pass

    def get_state(self) -> str:
        # Evaluate active Privacy Lock cooldown
        if self.state == PRIVACY_LOCK:
            if time.time() >= self.lock_until:
                self.state = CHALLENGE_MODE
                self.lock_until = 0.0
                self.failed_pin_attempts = 0
                self._save_persistent_state()
        return self.state

    def set_state(self, new_state: str) -> None:
        valid_states = {RESTRICTED_MODE, FULL_ACCESS_MODE, CHALLENGE_MODE, PRIVACY_LOCK}
        if new_state not in valid_states:
            raise ValueError(f"Invalid auth state: {new_state}")
        self.state = new_state
        self._save_persistent_state()

    def is_pin_enrolled(self) -> bool:
        """Whether a master PIN is enrolled."""
        return self._read_hashed_pin() is not None

    def set_master_pin(self, pin: str) -> None:
        """Hash and save new master PIN to DPAPI protected vault using Argon2id."""
        pin_str = str(pin).strip()
        if not pin_str or len(pin_str) < 4:
            raise ValueError("PIN must be at least 4 digits/characters.")

        hashed_pin = self._hasher.hash(pin_str)
        payload = json.dumps({"hashed_pin": hashed_pin}).encode("utf-8")
        protected = _dpapi_protect(payload)

        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_path.write_bytes(protected)
        if os.name != "nt":
            try:
                os.chmod(self.vault_path, 0o600)
            except OSError:
                pass

    def _read_hashed_pin(self) -> Optional[str]:
        if not self.vault_path.exists():
            return None
        try:
            raw = self.vault_path.read_bytes()
            unprotected = _dpapi_unprotect(raw)
            data = json.loads(unprotected.decode("utf-8"))
            return data.get("hashed_pin")
        except Exception:
            return None

    def trigger_privacy_lock(self, reason: str = "3 consecutive failed PIN attempts") -> str:
        """Activate Privacy Lock, persist state, and lock Windows workstation."""
        self.lock_until = time.time() + self.cooldown_seconds
        self.set_state(PRIVACY_LOCK)
        lock_workstation()

        alert_msg = f"SEC ALERT: Privacy Lock activated due to {reason}. Workstation locked for {int(self.cooldown_seconds // 60)} minutes."
        print(f"[AuthManager] {alert_msg}")
        return alert_msg

    def verify_pin(self, pin: str) -> bool:
        """
        Verify PIN against vault using Argon2id.
        Fail closed if unenrolled or locked. 3 failed attempts trigger PRIVACY_LOCK.
        """
        current_state = self.get_state()
        if current_state == PRIVACY_LOCK:
            return False

        if not self.is_pin_enrolled():
            return False

        pin_str = str(pin).strip()
        hashed_pin = self._read_hashed_pin()
        if not hashed_pin:
            return False

        is_valid = False
        try:
            self._hasher.verify(hashed_pin, pin_str)
            is_valid = True
        except (VerifyMismatchError, VerificationError, Exception):
            is_valid = False

        if is_valid:
            self.failed_pin_attempts = 0
            self.set_state(FULL_ACCESS_MODE)
            return True
        else:
            self.failed_pin_attempts += 1
            if self.failed_pin_attempts >= MAX_FAILED_PIN_ATTEMPTS:
                self.trigger_privacy_lock()
            else:
                self._save_persistent_state()
            return False

    def process_voice_result(self, is_master: bool, similarity: float, is_live: bool, is_stranger: bool = False) -> tuple[str, str]:
        """
        Evaluate voice verification result and update state:
          - Master match (similarity >= 0.80 & live) -> FULL_ACCESS_MODE
          - Stranger match -> RESTRICTED_MODE
          - Unconfirmed / low-confidence -> CHALLENGE_MODE + prompt for PIN
        """
        current_state = self.get_state()
        if current_state == PRIVACY_LOCK:
            remaining = int(max(0, self.lock_until - time.time()))
            return PRIVACY_LOCK, f"System in PRIVACY_LOCK mode ({remaining}s remaining). Access denied."

        if is_master and similarity >= COSINE_THRESHOLD and is_live:
            self.set_state(FULL_ACCESS_MODE)
            return FULL_ACCESS_MODE, "Voice identity verified as Master. Full access granted."

        if is_stranger:
            self.set_state(RESTRICTED_MODE)
            return RESTRICTED_MODE, "Voice identity recognized as stranger. Restricted mode active."

        # Low-confidence or unverified voice -> Switch to CHALLENGE_MODE
        self.set_state(CHALLENGE_MODE)
        prompt = "Voice identity unconfirmed. Please enter or speak your PIN."
        return CHALLENGE_MODE, prompt

    def process_voice_authentication(self, audio: np.ndarray | list | bytes, sample_rate: int = 16000, is_stranger: bool = False) -> tuple[str, str]:
        """Runs live voice verification and transitions state."""
        is_master, similarity, is_live = self.voice_authenticator.verify(audio, sample_rate=sample_rate, master_emb_path=self.vault_path.parent / "master_voice.emb")
        return self.process_voice_result(is_master, similarity, is_live, is_stranger=is_stranger)
