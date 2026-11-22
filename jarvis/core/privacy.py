"""Process-wide privacy defaults and the OFFLINE kill switch.

``apply()`` runs once when the ``jarvis`` package is imported, before any
third-party SDK is loaded:

* It sets opt-out flags for libraries that report usage on their own
  (Hugging Face Hub / SpeechBrain / Transformers, Gradio, Chroma, etc.).
  ``os.environ.setdefault`` is used, so an explicit value set by the owner
  always wins.

* When ``OFFLINE=1`` (or ``JARVIS_OFFLINE=1``) is set it also installs a
  socket-level guard: DNS lookups and connections to anything that is not
  loopback are refused with :class:`OfflineBlocked` (an ``OSError``, so the
  existing network-error handling in each feature degrades gracefully).
  LAN addresses (RFC 1918, link-local, ``*.local``) stay reachable so the
  tablet/phone/smart-home links keep working; set ``JARVIS_OFFLINE_LAN=0`` to
  block those too.

Every network call that remains when OFFLINE is not set is listed in
NETWORK.md at the repository root.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import threading

# Opt-out flags understood by libraries JARVIS (or its optional extras) loads.
TELEMETRY_OPT_OUT: dict[str, str] = {
    "DO_NOT_TRACK": "1",                    # https://consoledonottrack.com convention
    "HF_HUB_DISABLE_TELEMETRY": "1",        # huggingface_hub (speechbrain, kokoro, transformers)
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",   # never attach a cached HF token to unrelated requests
    "DISABLE_TELEMETRY": "1",               # transformers / diffusers legacy flag
    "GRADIO_ANALYTICS_ENABLED": "False",
    "ANONYMIZED_TELEMETRY": "False",        # chromadb
    "POSTHOG_DISABLED": "1",
    "SCARF_NO_ANALYTICS": "true",
    "NEXT_TELEMETRY_DISABLED": "1",         # web/ build when launched from JARVIS
}

# Extra flags that only make sense when the machine is meant to be offline.
OFFLINE_FLAGS: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
}

_TRUE = {"1", "true", "yes", "on"}
_lock = threading.Lock()
_guard_installed = False
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo


class OfflineBlocked(ConnectionRefusedError):
    """Raised when OFFLINE mode refuses an outbound connection or lookup."""


def _flag(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def offline_enabled() -> bool:
    """True when the owner asked JARVIS to run with no internet traffic."""
    return _flag("OFFLINE") or _flag("JARVIS_OFFLINE")


def _lan_allowed() -> bool:
    return str(os.environ.get("JARVIS_OFFLINE_LAN", "1")).strip().lower() in _TRUE


def is_allowed_host(host: object) -> bool:
    """Whether ``host`` may be contacted while OFFLINE mode is on."""
    if host is None:
        return True  # passive / unspecified address (bind-style lookups)
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    name = str(host).strip().strip("[]").lower()
    if name in ("", "localhost", "localhost.localdomain") or name.endswith(".localhost"):
        return True
    if "%" in name:  # IPv6 scope id, e.g. fe80::1%eth0
        name = name.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return _lan_allowed() and name.endswith(".local")
    if ip.is_loopback or ip.is_unspecified:
        return True
    if getattr(ip, "ipv4_mapped", None) is not None:
        return is_allowed_host(str(ip.ipv4_mapped))
    return _lan_allowed() and (ip.is_private or ip.is_link_local) and not ip.is_global


def _address_host(address: object) -> object:
    if isinstance(address, tuple) and address:
        return address[0]
    return None  # AF_UNIX path or unknown family: local by definition


def _guarded_connect(self: socket.socket, address):  # type: ignore[no-untyped-def]
    if self.family in (socket.AF_INET, socket.AF_INET6) and not is_allowed_host(_address_host(address)):
        raise OfflineBlocked(f"OFFLINE mode: outbound connection to {address!r} blocked")
    return _orig_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address):  # type: ignore[no-untyped-def]
    if self.family in (socket.AF_INET, socket.AF_INET6) and not is_allowed_host(_address_host(address)):
        raise OfflineBlocked(f"OFFLINE mode: outbound connection to {address!r} blocked")
    return _orig_connect_ex(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    if not is_allowed_host(host):
        raise OfflineBlocked(f"OFFLINE mode: DNS lookup for {host!r} blocked")
    return _orig_getaddrinfo(host, *args, **kwargs)


def install_offline_guard() -> None:
    """Refuse non-local DNS lookups and connections for the whole process."""
    global _guard_installed
    with _lock:
        if _guard_installed:
            return
        socket.socket.connect = _guarded_connect          # type: ignore[method-assign]
        socket.socket.connect_ex = _guarded_connect_ex    # type: ignore[method-assign]
        socket.getaddrinfo = _guarded_getaddrinfo         # type: ignore[assignment]
        _guard_installed = True


def uninstall_offline_guard() -> None:
    """Restore the original socket functions (used by tests)."""
    global _guard_installed
    with _lock:
        socket.socket.connect = _orig_connect             # type: ignore[method-assign]
        socket.socket.connect_ex = _orig_connect_ex       # type: ignore[method-assign]
        socket.getaddrinfo = _orig_getaddrinfo            # type: ignore[assignment]
        _guard_installed = False


def guard_installed() -> bool:
    return _guard_installed


def apply() -> None:
    """Set telemetry opt-outs and, when requested, enable OFFLINE mode."""
    for key, value in TELEMETRY_OPT_OUT.items():
        os.environ.setdefault(key, value)
    if offline_enabled():
        for key, value in OFFLINE_FLAGS.items():
            os.environ.setdefault(key, value)
        install_offline_guard()
