"""Voice tool for the Telegram channel: pair the owner's phone, send messages and files to it."""
from __future__ import annotations

import os
from pathlib import Path

from jarvis.channels import service

_ACTIONS = ("status", "pair", "unpair", "send", "send_file")


def telegram(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "").strip().lower()
    if action not in _ACTIONS:
        return f"Unknown telegram action '{action}'. Use one of: {', '.join(_ACTIONS)}."
    ch = service.get_channel()
    if ch is None:
        if not service.configured_token():
            return ("Telegram is not set up. Create a bot with @BotFather, put its token in config/api_keys.json "
                    "as telegram_bot_token, then restart JARVIS.")
        return "The Telegram channel is not running yet; restart JARVIS."
    if action == "status":
        paired = ch.paired()
        names = ", ".join(v.get("name") or k for k, v in paired.items()) or "none"
        err = f" Last error: {ch.last_error}." if ch.last_error else ""
        return f"Telegram channel {'running' if ch.running else 'stopped'}. Paired chats: {names}.{err}"
    if action == "pair":
        code = ch.new_pair_code()
        if player is not None and hasattr(player, "write_log"):
            player.write_log(f"SYS: Telegram pairing code: {code} (valid 10 minutes)")
        return (f"Pairing code {code}. Tell the owner to open the bot in Telegram and send: /pair {code} . "
                "It expires in 10 minutes.")
    if action == "unpair":
        n = ch.unpair()
        return f"Unpaired {n} Telegram chat(s)."
    if action == "send":
        text = str(p.get("text") or "").strip()
        if not text:
            return "What should I send?"
        n = ch.notify(text)
        return f"Sent to {n} Telegram chat(s)." if n else "No Telegram chat is paired."
    path = Path(os.path.expandvars(os.path.expanduser(str(p.get("path") or "").strip().strip('"'))))
    if not path.is_file():
        return f"File not found: {path}"
    try:
        n = ch.send_file(path, str(p.get("text") or ""))
    except Exception as e:
        return f"Could not send the file: {e}"
    return f"Sent {path.name} to {n} Telegram chat(s)." if n else "No Telegram chat is paired."


TOOL = {
    "name": "telegram",
    "description": (
        "The owner's private Telegram channel to JARVIS. 'pair' shows a one-time code to link the owner's phone; "
        "'send' messages the owner on Telegram; 'send_file' sends a local file (e.g. a document they asked for "
        "while away); 'status'; 'unpair'. Commands typed in the paired chat arrive as normal requests."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(_ACTIONS)},
            "text": {"type": "STRING", "description": "Message text (send) or caption (send_file)."},
            "path": {"type": "STRING", "description": "Full path of the file to send (send_file)."},
        },
        "required": ["action"],
    },
    "handler": telegram,
    "risk": "write",
    "timeout": 120,
}
