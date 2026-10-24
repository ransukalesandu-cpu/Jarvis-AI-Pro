"""
JarvisAI/security/auth_manager.py — Secure PIN Vault & Authentication State Machine.

Maintains 4 explicit authentication states:
  - RESTRICTED_MODE
  - FULL_ACCESS_MODE
  - CHALLENGE_MODE
  - PRIVACY_LOCK

Stores master PIN securely using argon2-cffi and Windows DPAPI / local encrypted vault.
"""

from __future__ import annotations

import os
import sys
import json
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
MAX_FAILED_PIN_ATTEMPTS = 5


def _dpapi_protect(data: bytes) -> bytes:
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
    except Exception:
        pass
    return data


def _dpapi_unprotect(data: bytes) -> bytes:
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
    except Exception:
        pass
    return data


class AuthManager:
    """Authentication State Machine & Secure PIN Vault Manager."""

    def __init__(self, vault_path: str | Path | None = None, voice_authenticator: SpeakerAuthenticator | None = None):
        self.vault_path = Path(vault_path) if vault_path else DEFAULT_VAULT_PATH
        self.voice_authenticator = voice_authenticator or SpeakerAuthenticator()
        self.state = RESTRICTED_MODE
        self.failed_pin_attempts = 0

        if _ARGON2_AVAILABLE:
            self._hasher = PasswordHasher()
        else:
            self._hasher = None

        # Ensure default PIN ("1234") if vault empty
        if not self.vault_path.exists():
            self.set_master_pin("1234")

    def get_state(self) -> str:
        return self.state

    def set_state(self, new_state: str) -> None:
        valid_states = {RESTRICTED_MODE, FULL_ACCESS_MODE, CHALLENGE_MODE, PRIVACY_LOCK}
        if new_state not in valid_states:
            raise ValueError(f"Invalid auth state: {new_state}")
        self.state = new_state

    def set_master_pin(self, pin: str) -> None:
        """Hash and save new master PIN to DPAPI protected vault."""
        pin_str = str(pin).strip()
        if not pin_str:
            raise ValueError("PIN cannot be empty.")

        if self._hasher:
            hashed_pin = self._hasher.hash(pin_str)
        else:
            # Fallback hashing if argon2 cffi binding unavailable
            import hashlib
            salt = os.urandom(16).hex()
            hashed_pin = f"sha256${salt}$" + hashlib.sha256((salt + pin_str).encode("utf-8")).hexdigest()

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

    def verify_pin(self, pin: str) -> bool:
        """Verify PIN against vault. Correct PIN grants FULL_ACCESS_MODE and resets failure counters."""
        if self.state == PRIVACY_LOCK:
            return False

        pin_str = str(pin).strip()
        hashed_pin = self._read_hashed_pin()

        if not hashed_pin:
            return False

        is_valid = False
        if self._hasher and hashed_pin.startswith("$argon2"):
            try:
                self._hasher.verify(hashed_pin, pin_str)
                is_valid = True
            except (VerifyMismatchError, VerificationError, Exception):
                is_valid = False
        else:
            import hashlib
            parts = hashed_pin.split("$")
            if len(parts) == 3 and parts[0] == "sha256":
                salt = parts[1]
                expected = parts[2]
                computed = hashlib.sha256((salt + pin_str).encode("utf-8")).hexdigest()
                is_valid = (computed == expected)

        if is_valid:
            self.failed_pin_attempts = 0
            self.set_state(FULL_ACCESS_MODE)
            return True
        else:
            self.failed_pin_attempts += 1
            if self.failed_pin_attempts >= MAX_FAILED_PIN_ATTEMPTS:
                self.set_state(PRIVACY_LOCK)
            return False

    def process_voice_result(self, is_master: bool, similarity: float, is_live: bool, is_stranger: bool = False) -> tuple[str, str]:
        """
        Evaluate voice verification result and update state:
          - Master match (similarity >= 0.80 & live) -> FULL_ACCESS_MODE
          - Stranger match -> RESTRICTED_MODE
          - Unconfirmed / low-confidence -> CHALLENGE_MODE + prompt for PIN
        """
        if self.state == PRIVACY_LOCK:
            return PRIVACY_LOCK, "System in PRIVACY_LOCK mode due to multiple failed PIN attempts."

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
