"""Voice tools: the file library (files JARVIS made/received) and Mini Apps (web tools in their own window)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from jarvis import library as lib

_FILE_ACTIONS = ("list", "search", "open", "send_to_phone", "forget_missing")
_APP_ACTIONS = ("list", "open", "add", "remove")


def file_library(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    if action not in _FILE_ACTIONS:
        return f"Unknown action '{action}'. Use one of: {', '.join(_FILE_ACTIONS)}."
    kind = str(p.get("kind") or "").strip().lower()
    query = str(p.get("query") or "").strip()
    if action in ("list", "search"):
        rows = lib.items(kind=kind, query=query, limit=int(p.get("limit") or 20))
        if not rows:
            return "The file library is empty." if not (kind or query) else "No matching files."
        return "Files (newest first):\n" + "\n".join(f"- [{r['kind']}] {r['name']} — {r['path']}" for r in rows)
    if action == "forget_missing":
        return f"Removed {lib.forget_missing()} entries whose files no longer exist."
    item = lib.find_one(query)
    if not item:
        return "No matching file in the library."
    path = Path(item["path"])
    if action == "open":
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # noqa: S606 - a file JARVIS itself recorded
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])  # noqa: S603
        return f"Opened {path.name}."
    from jarvis.channels import service
    ch = service.get_channel()
    if ch is None:
        return "Telegram is not set up, so I can't send it to your phone."
    n = ch.send_file(path, item["name"])
    return f"Sent {path.name} to your phone." if n else "No Telegram chat is paired."


def mini_app(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    if action not in _APP_ACTIONS:
        return f"Unknown action '{action}'. Use one of: {', '.join(_APP_ACTIONS)}."
    try:
        if action == "list":
            return "Mini apps:\n" + "\n".join(f"- {k}: {v}" for k, v in sorted(lib.mini_apps().items()))
        if action == "open":
            name = lib.open_app(str(p.get("name") or ""))
            return f"Opened the {name} mini app."
        if action == "add":
            name = lib.add_app(str(p.get("name") or ""), str(p.get("url") or ""))
            return f"Mini app '{name}' added. Say 'open {name}' to use it."
        lib.remove_app(str(p.get("name") or ""))
        return "Mini app removed."
    except (ValueError, KeyError) as e:
        return f"Mini apps: {e.args[0] if e.args else e}"
    except OSError as e:
        return f"Mini apps: could not start the browser ({e})."


TOOLS = [
    {
        "name": "file_library",
        "description": (
            "Library of files JARVIS created or received (translations, backups, generated images, downloads, "
            "exports). list/search (kind: translation, backup, media, download, export, document), open, "
            "send_to_phone (via Telegram), forget_missing."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "enum": list(_FILE_ACTIONS)},
                "kind": {"type": "STRING"},
                "query": {"type": "STRING", "description": "Words from the file name."},
                "limit": {"type": "INTEGER"},
            },
            "required": ["action"],
        },
        "handler": file_library,
        "risk": "read",
        "timeout": 120,
    },
    {
        "name": "mini_app",
        "description": (
            "Mini Apps: web tools opened in their own app window with a separate login profile (built-in: figma, "
            "canva, fiverr, chatgpt, claude, gemini, github). open (name), list, add (name + https url), remove."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "enum": list(_APP_ACTIONS)},
                "name": {"type": "STRING"},
                "url": {"type": "STRING", "description": "https URL (add)."},
            },
            "required": ["action"],
        },
        "handler": mini_app,
        "risk": "write",
        "timeout": 30,
    },
]
