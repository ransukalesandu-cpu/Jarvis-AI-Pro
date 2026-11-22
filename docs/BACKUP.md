# Backup and restore

P7 of `docs/CHERRY_STUDIO_PARITY_PLAN.md`. Tool: `backup`.

## What is saved
| Archive folder | Source |
|---|---|
| `data/` | per-user data folder: knowledge bases, notes, skills, channels, settings, usage, history |
| `config/` | runtime `.json`/`.dat` files in the install's `config` folder (code files are skipped) |
| `memory/` | memory databases/JSON in the install's `memory` folder |

Screenshots, browser profiles, caches, logs and model weights are skipped; files over 200 MB are skipped.

## Secrets and encryption
Set a backup password (`JARVIS_BACKUP_PASSWORD` or `"backup_password"` in `config/api_keys.json`).
- **With a password**: everything, including API keys, PIN vault and Voice ID, is saved in a `.jvbk` file
  encrypted with AES-256-GCM (key from scrypt).
- **Without a password**: a plain `.zip` that **leaves secrets out** (JARVIS tells you how many).

## Voice
"Back up JARVIS now" · "list my backups" · "what's in the latest backup" (`preview`) ·
"restore the latest backup" (DANGEROUS: confirmation; a safety backup of the current state is made first; zip-slip
safe) · "back up every day and keep 7" (`schedule`, checked hourly; `every_days=0` turns it off) ·
"save backups in D:\Backups" (`set_folder`, DANGEROUS).

## Targets
Default folder: `Documents\JARVIS Backups` (or `JARVIS_BACKUP_DIR`). Optional WebDAV upload (https only):
add to `<data>/backup_config.json`: `"webdav": {"url": "https://dav.example.com/jarvis", "user": "...", "password": "..."}`.
Scheduled results are reported in the HUD log and to your paired Telegram chat.
