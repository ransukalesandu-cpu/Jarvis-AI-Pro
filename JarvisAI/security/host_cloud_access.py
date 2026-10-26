"""Local gate for host-only cloud capabilities."""
from __future__ import annotations

def host_session_verified(manager) -> bool:
    """Return true only when the existing local owner session is active."""
    try:
        return bool(manager and manager.is_owner_access_allowed())
    except Exception:
        return False
