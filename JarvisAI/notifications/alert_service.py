"""
JarvisAI Notifications — Emergency Alert Service

Dispatches emergency Privacy Lock notifications across Twilio (SMS/Voice) and
WebSockets to connected mobile companion HUDs and local devices.
"""

import asyncio
import json
from typing import Callable, Optional

_websocket_broadcast_cb: Optional[Callable[[dict], None]] = None


def register_websocket_broadcast_callback(callback: Callable[[dict], None]) -> None:
    """Register callback function to broadcast WebSocket payloads."""
    global _websocket_broadcast_cb
    _websocket_broadcast_cb = callback


def send_twilio_alert(message: str) -> bool:
    """Send emergency alert via Twilio SMS or REST API if configured."""
    try:
        from plugins.phone_call import get_twilio_config, is_twilio_configured
        if not is_twilio_configured():
            print("[AlertService] Twilio not configured; skipping SMS/voice alert.")
            return False

        cfg = get_twilio_config()
        account_sid = cfg.get("account_sid")
        auth_token = cfg.get("auth_token")
        from_number = cfg.get("phone_number")
        to_number = cfg.get("alert_recipient_number") or cfg.get("phone_number")

        if not account_sid or not auth_token or not from_number:
            print("[AlertService] Missing Twilio credentials for alert.")
            return False

        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        client.messages.create(
            body=message,
            from_=from_number,
            to=to_number,
        )
        print("[AlertService] Twilio alert SMS dispatched successfully.")
        return True
    except Exception as e:
        print(f"[AlertService] Failed to send Twilio alert: {e}")
        return False


def dispatch_privacy_lock_alert(duration_seconds: int) -> dict:
    """Dispatch emergency PRIVACY_LOCK alert across Twilio and WebSockets."""
    alert_message = (
        f"SECURITY ALERT: Privacy Lock activated on master laptop. "
        f"3 failed authorization attempts. System locked and muted for {duration_seconds} seconds."
    )

    # 1. Send Twilio SMS alert
    send_twilio_alert(alert_message)

    # 2. Prepare WebSocket payload
    payload = {
        "event": "PRIVACY_LOCK",
        "duration": duration_seconds,
        "message": alert_message,
        "type": "privacy_lock",
    }

    # 3. Broadcast WebSocket payload to companion HUDs & clients
    if _websocket_broadcast_cb is not None:
        try:
            res = _websocket_broadcast_cb(payload)
            if asyncio.iscoroutine(res):
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(res)
                    else:
                        loop.run_until_complete(res)
                except Exception:
                    pass
        except Exception as e:
            print(f"[AlertService] WebSocket broadcast error: {e}")

    return payload
