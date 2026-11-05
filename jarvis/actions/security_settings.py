"""Owner-only Security ON/OFF switch for Guest monitoring."""
from __future__ import annotations

from jarvis.core import identity
from jarvis.core.security_settings import SettingsError, get_security_settings


def security_settings(parameters: dict, **_ctx) -> str:
    s = identity.get_identity_manager().current()
    if not (s.role == identity.ROLE_OWNER and s.state == identity.OWNER_AUTHENTICATED):
        return "Security settings are only available to a signed-in owner."
    cfg = get_security_settings()
    action = str((parameters or {}).get("action", "status")).lower()
    if action == "status":
        return cfg.status_text()
    if action in {"on", "off"}:
        try:
            cfg.set_monitoring(identity.get_identity_manager(), action == "on")
        except SettingsError as exc:
            return f"Not changed: {exc}."
        return cfg.status_text()
    return "Unknown action. Use status, on or off."


TOOL = {
    "name": "security_settings",
    "description": ("Owner only. Show or change Security monitoring for Guest sessions. action: status | on | off. "
                    "Turning it off needs a recent second-factor confirmation; baseline protections always stay on."),
    "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING", "description": "status, on or off"}}},
    "handler": security_settings,
}
