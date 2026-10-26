"""Device-bound Ed25519 signing identity stored with Windows DPAPI.

This proves possession of the enrolled device key; the caller must separately
ensure that the local owner PIN/voice authentication session is active.
"""
from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_FILE = Path(__file__).resolve().parent.parent / "config" / "host_device_key.dat"


def _private_key() -> Ed25519PrivateKey:
    from security.auth_manager import _dpapi_protect, _dpapi_unprotect
    if sys.platform != "win32":
        raise RuntimeError("Host device signing requires the Windows DPAPI store.")
    if KEY_FILE.is_file():
        raw = _dpapi_unprotect(KEY_FILE.read_bytes())
        if len(raw) != 32:
            raise RuntimeError("Stored host device key is invalid.")
        return Ed25519PrivateKey.from_private_bytes(raw)
    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = KEY_FILE.with_suffix(".tmp")
    try:
        temp.write_bytes(_dpapi_protect(raw))
        os.replace(temp, KEY_FILE)
    finally:
        temp.unlink(missing_ok=True)
    return Ed25519PrivateKey.from_private_bytes(raw)


def public_key_b64() -> str:
    raw = _private_key().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def sign_request(body: bytes) -> dict[str, str]:
    import hashlib
    import secrets
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    digest = hashlib.sha256(body).hexdigest()
    message = f"JARVIS-HOST-V1\n{timestamp}\n{nonce}\n{digest}".encode("utf-8")
    signature = _private_key().sign(message)
    return {
        "X-Jarvis-Host-Timestamp": timestamp,
        "X-Jarvis-Host-Nonce": nonce,
        "X-Jarvis-Host-Signature": base64.b64encode(signature).decode("ascii"),
    }
