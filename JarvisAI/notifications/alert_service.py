"""Optional emergency alerts for the existing Jarvis Privacy Lock state machine.

This module does not own authentication or lock state. The existing AuthManager
remains authoritative; callers invoke these helpers after it activates lockout.
"""

from __future__ import annotations

from typing import Any


def build_privacy_lock_alert(duration_seconds: int, message: str | None = None) -> dict[str, Any]:
    """Build a safe, non-sensitive dashboard event for the current lockout."""
    try:
        duration = max(0, min(int(duration_seconds), 300))
    except (TypeError, ValueError):
        duration = 0
    alert_message = (str(message or "").strip() or
        "JARVIS Privacy Lock activated. Private access is blocked.")
    return {
        "event": "PRIVACY_LOCK",
        "duration": duration,
        "message": alert_message,
        # Keep existing dashboard event conventions compatible.
        "type": "privacy_lock",
        "text": alert_message,
        "cooldown_remaining": duration,
    }


def send_twilio_alert(message: str) -> bool:
    """Send an optional SMS only when Twilio and an explicit recipient are configured.

    This function is synchronous by design; the application calls it via
    asyncio.to_thread so network I/O never blocks the real-time audio loop.
    """
    try:
        from plugins.phone_call import get_twilio_config, is_twilio_configured

        if not is_twilio_configured():
            return False

        config = get_twilio_config() or {}
        account_sid = str(config.get("account_sid") or "").strip()
        auth_token = str(config.get("auth_token") or "").strip()
        from_number = str(config.get("phone_number") or "").strip()
        # Do not silently send an alert to the Twilio sender number.
        to_number = str(config.get("alert_recipient_number") or "").strip()
        if not all((account_sid, auth_token, from_number, to_number)):
            print("[Privacy Lock] Twilio alert skipped: credentials or explicit recipient are missing.")
            return False
        if to_number == from_number:
            print("[Privacy Lock] Twilio alert skipped: sender and recipient must differ.")
            return False

        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        client.messages.create(body=str(message), from_=from_number, to=to_number)
        return True
    except Exception as exc:
        # Avoid putting provider exception details or credential-related values in logs.
        print(f"[Privacy Lock] Twilio SMS alert failed: {type(exc).__name__}")
        return False
