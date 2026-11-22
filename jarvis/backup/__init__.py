"""Backup and restore of JARVIS's own data (Cherry Studio parity P7). See docs/BACKUP.md.

What is backed up
-----------------
* ``data/``    — the per-user data folder (knowledge bases, notes, skills, channels, settings, …)
* ``config/``  — runtime JSON/DAT files in the install's ``config`` folder (API keys, PIN vault, Voice ID)
* ``memory/``  — memory databases and JSON in the install's ``memory`` folder

Secrets (API keys, PIN vault, Voice ID, tokens, owner/auth files) are **only** included
when the archive is encrypted with a backup password (``JARVIS_BACKUP_PASSWORD`` or
``backup_password`` in api_keys.json). Without a password they are left out, so a plain
backup never leaks them. Encryption: scrypt key derivation + AES-256-GCM.

Targets: a local folder (always), plus optional WebDAV upload.
"""
from __future__ import annotations

import base64
import fnmatch
import io
import json
import os
import re
import secrets
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

MAGIC = b"JVBK1"
MAX_FILE_BYTES = 200 * 1024 * 1024
SKIP_DIRS = {"backups", "cc-screenshots", "cc-browser-profile", "cache", "caches", "__pycache__", "logs", "tmp",
             "models", "hf-cache"}
SECRET_PATTERNS = ("*api_key*", "*secret*", "*token*", "*vault*", "*voice_id*", "*auth_state*", "*credential*",
                   "*password*", "*owner*", "*face*", "*.key", "*.pem", "telegram.json", "pin*")
DATA_EXTS = {".json", ".dat", ".db", ".sqlite", ".jsonl", ".txt", ".md", ".yaml", ".yml", ".csv", ".enc"}
_STAMP_RE = re.compile(r"^jarvis-backup-(\d{8}-\d{6})\.(zip|jvbk)$")


@dataclass
class BackupResult:
    path: Path
    files: int
    bytes: int
    encrypted: bool
    skipped_secrets: int = 0
    uploaded: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _install_dir() -> Path:
    from jarvis.memory.config_manager import get_base_dir
    return get_base_dir()


def roots() -> dict[str, tuple[Path, bool]]:
    """name -> (folder, data_files_only)."""
    from jarvis.core.user_data import user_data_dir
    base = _install_dir()
    return {"data": (user_data_dir(), False), "config": (base / "config", True), "memory": (base / "memory", True)}


def _config_path() -> Path:
    from jarvis.core.user_data import user_data_dir
    return user_data_dir() / "backup_config.json"


def load_config() -> dict:
    try:
        cfg = json.loads(_config_path().read_text(encoding="utf-8"))
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(**changes) -> dict:
    cfg = load_config()
    cfg.update({k: v for k, v in changes.items() if v is not None})
    _config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def backup_dir() -> Path:
    raw = os.environ.get("JARVIS_BACKUP_DIR", "").strip() or str(load_config().get("folder") or "")
    folder = Path(raw).expanduser() if raw else Path.home() / "Documents" / "JARVIS Backups"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _password() -> str:
    env = os.environ.get("JARVIS_BACKUP_PASSWORD", "")
    if env:
        return env
    try:
        from jarvis.memory.config_manager import load_api_keys
        return str(load_api_keys().get("backup_password") or "")
    except Exception:
        return ""


def is_secret(name: str) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, pat) for pat in SECRET_PATTERNS)


def collect(sources: Optional[dict[str, tuple[Path, bool]]] = None, *, include_secrets: bool) -> tuple[list[tuple[str, Path]], int]:
    """(archive name, file) pairs to back up, and how many secret files were left out."""
    items: list[tuple[str, Path]] = []
    skipped = 0
    for root_name, (folder, data_only) in (sources or roots()).items():
        if not folder.is_dir():
            continue
        for dirpath, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                p = Path(dirpath) / f
                if data_only and p.suffix.lower() not in DATA_EXTS:
                    continue
                try:
                    if p.is_symlink() or p.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                if is_secret(f) or any(is_secret(part) for part in p.relative_to(folder).parts[:-1]):
                    if not include_secrets:
                        skipped += 1
                        continue
                items.append((f"{root_name}/{p.relative_to(folder).as_posix()}", p))
    return items, skipped


# ── encryption ──────────────────────────────────────────────────────────────
def _key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode("utf-8"))


def encrypt(data: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    return MAGIC + salt + nonce + AESGCM(_key(password, salt)).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, password: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(MAGIC):
        raise ValueError("not a JARVIS encrypted backup")
    salt, nonce, body = blob[5:21], blob[21:33], blob[33:]
    try:
        return AESGCM(_key(password, salt)).decrypt(nonce, body, MAGIC)
    except InvalidTag:
        raise ValueError("wrong backup password (or the file is damaged)") from None


# ── create ──────────────────────────────────────────────────────────────────
def create_backup(*, password: Optional[str] = None, folder: Optional[Path] = None,
                  sources: Optional[dict[str, tuple[Path, bool]]] = None, keep: Optional[int] = None,
                  upload: bool = True, clock: Callable[[], float] = time.time) -> BackupResult:
    pw = _password() if password is None else password
    items, skipped = collect(sources, include_secrets=bool(pw))
    buf = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = {"created": int(clock()), "encrypted": bool(pw), "files": len(items), "app": "JARVIS"}
        z.writestr("manifest.json", json.dumps(manifest))
        for arc, p in items:
            try:
                z.write(p, arc)
                total += p.stat().st_size
            except OSError:
                continue
    data = buf.getvalue()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    out_dir = folder or backup_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    if pw:
        path = out_dir / f"jarvis-backup-{stamp}.jvbk"
        path.write_bytes(encrypt(data, pw))
    else:
        path = out_dir / f"jarvis-backup-{stamp}.zip"
        path.write_bytes(data)
    result = BackupResult(path, len(items), total, bool(pw), skipped)
    from jarvis import library
    library.register(path, "backup", source="backup")
    prune(out_dir, int(keep if keep is not None else load_config().get("keep", 10)))
    if upload:
        cfg = load_config().get("webdav") or {}
        if cfg.get("url"):
            try:
                result.uploaded.append(webdav_upload(path, cfg))
            except Exception as e:
                result.errors.append(f"WebDAV: {type(e).__name__}: {e}"[:200])
    save_config(last_backup=int(clock()))
    return result


def list_backups(folder: Optional[Path] = None) -> list[Path]:
    folder = folder or backup_dir()
    return sorted((p for p in folder.iterdir() if _STAMP_RE.match(p.name)), key=lambda p: p.name, reverse=True)


def prune(folder: Path, keep: int) -> int:
    keep = max(1, keep)
    old = list_backups(folder)[keep:]
    for p in old:
        try:
            p.unlink()
        except OSError:
            continue
    return len(old)


# ── WebDAV ──────────────────────────────────────────────────────────────────
def webdav_upload(path: Path, cfg: dict, *, opener: Optional[Callable] = None) -> str:
    url = str(cfg.get("url") or "").rstrip("/")
    if not url.startswith("https://"):
        raise ValueError("WebDAV URL must be https://")
    dest = f"{url}/{path.name}"
    req = urllib.request.Request(dest, data=path.read_bytes(), method="PUT")
    user, pw = str(cfg.get("user") or ""), str(cfg.get("password") or "")
    if user:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode())
    req.add_header("Content-Type", "application/octet-stream")
    with (opener or urllib.request.urlopen)(req, timeout=120) as resp:  # noqa: S310 - https enforced above
        if getattr(resp, "status", 200) >= 300:
            raise RuntimeError(f"HTTP {resp.status}")
    return dest


# ── restore ─────────────────────────────────────────────────────────────────
def _open(path: Path, password: Optional[str]) -> zipfile.ZipFile:
    blob = Path(path).read_bytes()
    if blob.startswith(MAGIC):
        pw = _password() if password is None else password
        if not pw:
            raise ValueError("this backup is encrypted; set the backup password first")
        blob = decrypt(blob, pw)
    return zipfile.ZipFile(io.BytesIO(blob))


def preview(path: Path, *, password: Optional[str] = None) -> dict:
    with _open(path, password) as z:
        names = [n for n in z.namelist() if n != "manifest.json"]
        manifest = json.loads(z.read("manifest.json")) if "manifest.json" in z.namelist() else {}
    by_root: dict[str, int] = {}
    for n in names:
        by_root[n.split("/", 1)[0]] = by_root.get(n.split("/", 1)[0], 0) + 1
    return {"manifest": manifest, "files": len(names), "by_root": by_root}


def restore(path: Path, *, password: Optional[str] = None, targets: Optional[dict[str, tuple[Path, bool]]] = None,
            safety_backup: bool = True) -> int:
    """Restore files over the current ones (a safety backup of the current state is made first)."""
    targets = targets or roots()
    if safety_backup:
        create_backup(password=password, sources=targets, upload=False, keep=1000)
    restored = 0
    with _open(path, password) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename == "manifest.json":
                continue
            root_name, _, rel = info.filename.partition("/")
            if root_name not in targets or not rel:
                continue
            base = targets[root_name][0].resolve()
            dest = (base / rel).resolve()
            if base not in dest.parents:                 # zip-slip guard
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(info))
            restored += 1
    return restored


# ── scheduler ───────────────────────────────────────────────────────────────
_sched: Optional[threading.Thread] = None


def due(now: Optional[float] = None) -> bool:
    cfg = load_config()
    days = float(cfg.get("every_days") or 0)
    if days <= 0:
        return False
    return (now or time.time()) - float(cfg.get("last_backup") or 0) >= days * 86400


def start_scheduler(notify: Optional[Callable[[str], None]] = None) -> Optional[threading.Thread]:
    """Hourly check; runs a backup when ``every_days`` has passed. Off until the owner schedules one."""
    global _sched
    if _sched is not None:
        return _sched
    stop = threading.Event()

    def loop():
        while not stop.wait(3600):
            try:
                if due():
                    r = create_backup()
                    if notify:
                        notify(f"Backup done: {r.path.name} ({r.files} files"
                               f"{', encrypted' if r.encrypted else ''}).")
            except Exception as e:
                if notify:
                    notify(f"Scheduled backup failed: {type(e).__name__}")

    _sched = threading.Thread(target=loop, name="jarvis-backup", daemon=True)
    _sched.start()
    return _sched
