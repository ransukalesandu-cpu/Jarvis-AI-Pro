"""Device-bound Ed25519 signing identity in the native OS credential store.

Windows uses DPAPI; macOS uses Keychain; Linux uses Secret Service. Unsupported
or insecure keyring backends fail closed. Possession of this key proves device
identity only; owner authentication and action authorization remain separate.
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
_KEYRING_SERVICE = "JARVIS.HostDeviceIdentity"
_KEYRING_ACCOUNT = "ed25519-private-key-v1"


def _new_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _keyring_private_key() -> Ed25519PrivateKey:
    """Load/create a key only through the platform's native protected vault."""
    import keyring

    backend = keyring.get_keyring()
    backend_module = type(backend).__module__
    if sys.platform == "darwin":
        allowed = backend_module.startswith("keyring.backends.macOS")
    elif sys.platform.startswith("linux"):
        allowed = backend_module.startswith("keyring.backends.SecretService")
    else:
        allowed = False
    if not allowed:
        raise RuntimeError("No supported native OS credential store is available for the host signing key.")

    encoded = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
    if encoded:
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise RuntimeError("Stored host device key is invalid.") from None
        if len(raw) != 32:
            raise RuntimeError("Stored host device key is invalid.")
        return Ed25519PrivateKey.from_private_bytes(raw)

    raw = _new_private_key().private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    encoded = base64.b64encode(raw).decode("ascii")
    keyring.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, encoded)
    # Verify persistence before returning; never proceed with an ephemeral key.
    stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
    if not stored or not __import__("hmac").compare_digest(stored, encoded):
        raise RuntimeError("The native credential store did not persist the host signing key.")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _private_key() -> Ed25519PrivateKey:
    if sys.platform == "win32":
        from security.auth_manager import _dpapi_protect, _dpapi_unprotect
        if KEY_FILE.is_file():
            raw = _dpapi_unprotect(KEY_FILE.read_bytes())
            if len(raw) != 32:
                raise RuntimeError("Stored host device key is invalid.")
            return Ed25519PrivateKey.from_private_bytes(raw)

        raw = _new_private_key().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
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

    if sys.platform == "darwin" or sys.platform.startswith("linux"):
        return _keyring_private_key()
    raise RuntimeError("Host device signing is unavailable on this operating system.")


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
