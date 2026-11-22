"""Voice tool: back up and restore JARVIS's data (owner-level)."""
from __future__ import annotations

from pathlib import Path

from jarvis import backup as bk

_ACTIONS = ("create", "list", "preview", "restore", "schedule", "status", "set_folder")


def _find(name: str) -> Path:
    items = bk.list_backups()
    if not items:
        raise FileNotFoundError("no backups found")
    if not name or name in ("latest", "last"):
        return items[0]
    p = Path(name).expanduser()
    if p.is_file():
        return p
    for b in items:
        if name in b.name:
            return b
    raise FileNotFoundError(f"no backup matching '{name}'")


def backup(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "status").strip().lower()
    if action not in _ACTIONS:
        return f"Unknown backup action '{action}'. Use one of: {', '.join(_ACTIONS)}."
    try:
        if action == "create":
            if speak:
                speak("Backing up now.")
            r = bk.create_backup()
            msg = (f"Backup saved: {r.path} ({r.files} files, {r.bytes // 1024} KB, "
                   f"{'encrypted' if r.encrypted else 'not encrypted'}).")
            if r.skipped_secrets:
                msg += (f" {r.skipped_secrets} secret file(s) (API keys, PIN, Voice ID) were left out because no "
                        "backup password is set.")
            if r.uploaded:
                msg += " Uploaded to WebDAV."
            if r.errors:
                msg += " " + " ".join(r.errors)
            return msg
        if action == "list":
            items = bk.list_backups()
            if not items:
                return f"No backups yet in {bk.backup_dir()}."
            return "Backups (newest first):\n" + "\n".join(f"- {b.name} ({b.stat().st_size // 1024} KB)" for b in items[:15])
        if action == "preview":
            info = bk.preview(_find(str(p.get("name") or "")))
            roots = ", ".join(f"{k}: {v}" for k, v in info["by_root"].items())
            return f"Backup contains {info['files']} files ({roots})."
        if action == "restore":
            n = bk.restore(_find(str(p.get("name") or "")))
            return f"Restored {n} files. A safety backup of the previous state was saved first. Restart JARVIS to load them."
        if action == "schedule":
            days = float(p.get("every_days") if p.get("every_days") is not None else 1)
            cfg = bk.save_config(every_days=max(0.0, days), keep=int(p.get("keep") or bk.load_config().get("keep", 10)))
            return ("Automatic backups are off." if not cfg["every_days"] else
                    f"Automatic backup every {cfg['every_days']:g} day(s), keeping the last {cfg['keep']}.")
        if action == "set_folder":
            folder = Path(str(p.get("folder") or "")).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            bk.save_config(folder=str(folder.resolve()))
            return f"Backups will be saved in {folder.resolve()}."
        cfg = bk.load_config()
        items = bk.list_backups()
        return (f"Backup folder: {bk.backup_dir()}. {len(items)} backup(s); latest: {items[0].name if items else 'none'}. "
                f"Schedule: {'every ' + format(cfg['every_days'], 'g') + ' day(s)' if cfg.get('every_days') else 'off'}. "
                f"Password: {'set' if bk._password() else 'not set (secrets are excluded)'}. "
                f"WebDAV: {'on' if (cfg.get('webdav') or {}).get('url') else 'off'}.")
    except (FileNotFoundError, ValueError) as e:
        return f"Backup: {e.args[0] if e.args else e}"
    except OSError as e:
        return f"Backup failed: {e}"


TOOL = {
    "name": "backup",
    "description": (
        "Back up / restore JARVIS's own data (memory, knowledge bases, notes, settings; secrets only when a backup "
        "password is set, encrypted with AES-256). create, list, preview, restore (owner confirmation), "
        "schedule (every_days, keep; 0 = off), status, set_folder."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(_ACTIONS)},
            "name": {"type": "STRING", "description": "Backup file name or 'latest' (preview/restore)."},
            "every_days": {"type": "NUMBER", "description": "Schedule interval in days; 0 turns it off."},
            "keep": {"type": "INTEGER", "description": "How many backups to keep."},
            "folder": {"type": "STRING", "description": "Folder for set_folder."},
        },
        "required": ["action"],
    },
    "handler": backup,
    "risk": "write",
    "timeout": 600,
}
