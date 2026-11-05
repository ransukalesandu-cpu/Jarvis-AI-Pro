"""Pairing and device tokens: only paired devices may reach the hub.

1. The hub creates a one-time pairing code for a device name (printed as a URL
   and a QR code). It expires after a few minutes and works once.
2. The device exchanges the code for a long-lived token (a client stores it in
   a cookie + localStorage, the laptop agent in its config file).
3. Every later connection presents the token. The hub keeps only a SHA-256
   hash of each token, so a copy of the hub's state does not leak tokens.
4. ``revoke(device)`` deletes the device's tokens; live connections are closed
   by the caller at the same moment.

Tokens live in ``<state>/tokens.json`` (owner-only permissions where the OS
supports it). It is never inside the repository.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROLES = ("client", "agent")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class PairingCode:
    code: str
    device: str
    role: str
    expires: float


@dataclass
class TokenInfo:
    device: str
    role: str
    created: float


class TokenStore:
    def __init__(self, path: Path, *, pairing_minutes: float = 15.0):
        self.path = Path(path)
        self.pairing_seconds = pairing_minutes * 60
        self._lock = threading.Lock()
        self._codes: dict[str, PairingCode] = {}
        self._tokens: dict[str, TokenInfo] = {}
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows = {}
        for digest, row in (rows.get("tokens") or {}).items():
            self._tokens[digest] = TokenInfo(row["device"], row["role"], row.get("created", 0.0))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        data = {"tokens": {d: vars(t) for d, t in self._tokens.items()}}
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, self.path)

    # ── pairing ───────────────────────────────────────────────────────────────
    def create_code(self, device: str, role: str = "client") -> PairingCode:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        code = "-".join(secrets.token_hex(2).upper() for _ in range(3))   # e.g. 3FA1-09BC-77DE
        pc = PairingCode(code, device, role, time.time() + self.pairing_seconds)
        with self._lock:
            self._codes[code] = pc
        return pc

    def redeem(self, code: str, device: str | None = None) -> tuple[str, TokenInfo] | None:
        """Exchange a valid unused code for a new token. Returns None if refused."""
        code = str(code or "").strip().upper()
        with self._lock:
            pc = self._codes.pop(code, None)
            if pc is None or pc.expires < time.time():
                return None
            if device and device != pc.device:
                return None
            token = secrets.token_urlsafe(32)
            info = TokenInfo(pc.device, pc.role, time.time())
            self._tokens[_hash(token)] = info
            self._save()
            return token, info

    # ── checks ────────────────────────────────────────────────────────────────
    def verify(self, token: str | None, role: str | None = None) -> TokenInfo | None:
        if not token:
            return None
        digest = _hash(str(token))
        with self._lock:
            for known, info in self._tokens.items():
                if hmac.compare_digest(known, digest):
                    if role and info.role != role:
                        return None
                    return info
        return None

    def revoke(self, device: str) -> int:
        with self._lock:
            doomed = [d for d, info in self._tokens.items() if info.device == device]
            for d in doomed:
                del self._tokens[d]
            self._save()
        return len(doomed)

    def paired_devices(self) -> dict[str, list[str]]:
        with self._lock:
            out: dict[str, list[str]] = {}
            for info in self._tokens.values():
                out.setdefault(info.device, []).append(info.role)
            return out
