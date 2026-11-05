"""Security ON/OFF (Security V2, Phase 4).

"OFF" only switches off Guest monitoring: the Guest audit log stops recording new
events and the Guest notice says so. It never weakens the baseline in ``BASELINE``,
which stays enforced in every state. Only a signed-in owner can change it, and
turning it off needs a recent step-up (second factor), like other security changes.
Existing log entries are untouched and still expire after 7 days.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from jarvis.core import identity

BASELINE = (
    "Guests are denied every tool not on the small Guest allowlist.",
    "Dangerous tools (shell, files, settings, computer control) need a signed-in owner.",
    "PINs are stored only as hashes and never go through voice or cloud AI.",
    "A task or website password never makes anyone an owner.",
    "Changing security settings, owners or Guest history needs an owner session.",
    "Privacy Lock and the tamper-evident action ledger keep working.",
)

SCHEMA = "CREATE TABLE IF NOT EXISTS security_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL);"


class SettingsError(RuntimeError):
    pass


class SecuritySettings:
    def __init__(self, store=None, clock=time.time):
        if store is None:
            from jarvis.core.owner_store import get_owner_store
            store = get_owner_store()
        store.ensure_schema(SCHEMA)
        self._store, self._clock = store, clock
        self._lock = threading.RLock()

    def monitoring_enabled(self) -> bool:
        with self._store.connect() as db:
            row = db.execute("SELECT value FROM security_settings WHERE key='guest_monitoring'").fetchone()
        return True if row is None else row[0] == "on"

    def set_monitoring(self, manager: identity.IdentityManager, enabled: bool) -> bool:
        """Owner-only. Turning monitoring OFF also needs a recent step-up."""
        decision = manager.authorize("security_settings", "DANGEROUS", needs_strong=not enabled)
        if not decision.allowed:
            raise SettingsError(f"not allowed: {decision.reason}")
        with self._lock, self._store.connect() as db:
            db.execute("INSERT OR REPLACE INTO security_settings VALUES ('guest_monitoring', ?, ?)",
                       ("on" if enabled else "off", self._clock()))
        try:
            from jarvis.core.security import audit
            audit("security_settings", "guest_monitoring", "DANGEROUS", "ran", "on" if enabled else "off")
        except Exception:
            from jarvis.core import failsoft
            failsoft.suppress("security_settings:audit")
        return enabled

    def status_text(self) -> str:
        on = self.monitoring_enabled()
        head = ("Security is ON: Guest sessions are monitored with the minimal 7-day log." if on else
                "Security monitoring is OFF: Guest sessions are not being logged. The baseline below still applies.")
        return head + "\nAlways enforced:\n- " + "\n- ".join(BASELINE)


_s: Optional[SecuritySettings] = None
_lock = threading.Lock()


def get_security_settings() -> SecuritySettings:
    global _s
    with _lock:
        if _s is None:
            _s = SecuritySettings()
        return _s


def reset_for_tests(s: Optional[SecuritySettings] = None) -> None:
    global _s
    with _lock:
        _s = s
