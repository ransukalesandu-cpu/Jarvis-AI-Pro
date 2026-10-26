"""Local gate for host-only cloud capabilities."""
from __future__ import annotations


def host_session_verified(manager) -> bool:
    """Require active owner access plus both PIN and live Voice ID in this process."""
    try:
        return bool(
            manager
            and manager.is_owner_access_allowed()
            and manager.owner_factors_verified()
        )
    except Exception:
        return False
