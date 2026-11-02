"""Which network addresses the hub listens on.

Never 0.0.0.0 and never a public address: the hub can run any command on the
laptop, so it is reachable only from

* localhost (the laptop itself, and the tablet over USB via `adb reverse`),
* private LAN ranges (10/8, 172.16/12, 192.168/16), and
* Tailscale's CGNAT range 100.64.0.0/10 (and its IPv6 fd7a:115c:a1e0::/48).

``JARVIS_HUB_BIND`` can name addresses explicitly (still checked against the
same rules). Public internet exposure is refused, not configurable.
"""
from __future__ import annotations

import ipaddress

_TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


def classify(address: str) -> str:
    """'loopback', 'tailscale', 'lan' or 'public' (refused)."""
    ip = ipaddress.ip_address(address.split("%")[0])
    if ip.is_loopback:
        return "loopback"
    if ip in (_TAILSCALE_V4 if ip.version == 4 else _TAILSCALE_V6):
        return "tailscale"
    if ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return "public"
    if ip.is_private:
        return "lan"
    return "public"


def local_addresses() -> list[str]:
    try:
        import psutil
    except ImportError:
        return ["127.0.0.1"]
    import socket
    out = []
    for addrs in psutil.net_if_addrs().values():
        for a in addrs:
            if a.family in (socket.AF_INET, socket.AF_INET6):
                out.append(a.address.split("%")[0])
    return out


def bind_addresses(explicit: list[str] | None = None, *, lan: bool = True) -> dict[str, list[str]]:
    """{'plain': [...], 'tls': [...]} — plain HTTP only on loopback."""
    candidates = list(explicit) if explicit else local_addresses()
    plain, tls = ["127.0.0.1"], []
    for addr in candidates:
        try:
            kind = classify(addr)
        except ValueError:
            continue
        if kind == "public":
            continue
        if kind == "loopback":
            continue
        if kind == "lan" and not lan:
            continue
        if addr not in tls:
            tls.append(addr)
    return {"plain": plain, "tls": tls}


def is_allowed_peer(address: str | None) -> bool:
    """A connection from a public address is dropped before authentication."""
    if not address:
        return False
    try:
        return classify(address) != "public"
    except ValueError:
        return False
