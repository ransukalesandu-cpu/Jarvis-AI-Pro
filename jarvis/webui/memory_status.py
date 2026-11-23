"""What the page may know about JARVIS memory: on/off facts only, never URLs, keys or stored content.

No Qt in this module, so it is unit-tested directly.
"""
from __future__ import annotations

import os

CLOUD_STATES = ("configured", "not_configured")


def memory_status() -> dict:
    """Supabase configured (env present), opt-in personal cloud memory, local memory encryption."""
    cloud = "configured" if os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_ANON_KEY", "").strip() else "not_configured"
    try:
        from jarvis.memory.config_manager import get_memory_encryption_enabled, get_personal_cloud_memory_enabled
        personal, encrypted = bool(get_personal_cloud_memory_enabled()), bool(get_memory_encryption_enabled())
    except Exception:          # config unreadable: report "off", never guess "on"
        personal = encrypted = False
    return {"cloud": cloud, "personal": personal, "encrypted": encrypted}
