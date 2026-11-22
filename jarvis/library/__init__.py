"""File library + Mini Apps (Cherry Studio parity P10). See docs/FILE_LIBRARY_AND_MINI_APPS.md.

File library: an index of files JARVIS made or received (translations, backups, generated
images, Telegram downloads, exports). Features call ``register(path, kind)``; known output
folders (``Pictures/JARVIS``) are also scanned. Stored in ``<data>/library.json``.

Mini Apps: owner-defined web tools (name + https URL) opened as their own app window
(Edge/Chrome ``--app`` mode) with a separate browser profile per app under
``<data>/miniapps/<name>``, so logins stay separate from the main browser.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

MAX_ITEMS = 2000
_lock = threading.RLock()
KINDS = ("translation", "backup", "media", "download", "export", "document", "other")


def _data() -> Path:
    from jarvis.core.user_data import user_data_dir
    return user_data_dir()


def _lib_path() -> Path:
    return _data() / "library.json"


def _load() -> list[dict]:
    try:
        items = json.loads(_lib_path().read_text(encoding="utf-8"))
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    _lib_path().write_text(json.dumps(items[-MAX_ITEMS:], indent=1, ensure_ascii=False), encoding="utf-8")


def register(path: str | Path, kind: str = "other", *, source: str = "", note: str = "") -> None:
    """Record a file JARVIS produced or received. Fail-soft: never raises."""
    try:
        p = Path(path).resolve()
        kind = kind if kind in KINDS else "other"
        with _lock:
            items = [i for i in _load() if i.get("path") != str(p)]
            items.append({"path": str(p), "name": p.name, "kind": kind, "source": source[:40], "note": note[:200],
                          "added": int(time.time())})
            _save(items)
    except Exception:
        return


def scan_known_folders() -> int:
    """Pick up generated media in Pictures/JARVIS that were not registered yet."""
    added = 0
    folder = Path.home() / "Pictures" / "JARVIS"
    if not folder.is_dir():
        return 0
    with _lock:
        items = _load()
        known = {i.get("path") for i in items}
        for p in sorted(folder.iterdir()):
            if p.is_file() and str(p.resolve()) not in known:
                items.append({"path": str(p.resolve()), "name": p.name, "kind": "media", "source": "scan", "note": "",
                              "added": int(p.stat().st_mtime)})
                added += 1
        if added:
            _save(items)
    return added


def items(*, kind: str = "", query: str = "", limit: int = 30, include_missing: bool = False) -> list[dict]:
    scan_known_folders()
    out = []
    q = str(query or "").lower().split()
    for i in reversed(_load()):
        if kind and i.get("kind") != kind:
            continue
        hay = f"{i.get('name', '')} {i.get('note', '')} {i.get('kind', '')}".lower()
        if q and not all(w in hay for w in q):
            continue
        exists = Path(i["path"]).exists()
        if not exists and not include_missing:
            continue
        out.append(dict(i, exists=exists))
        if len(out) >= limit:
            break
    return out


def forget_missing() -> int:
    with _lock:
        all_items = _load()
        keep = [i for i in all_items if Path(i.get("path", "")).exists()]
        _save(keep)
        return len(all_items) - len(keep)


def find_one(query: str) -> Optional[dict]:
    hits = items(query=query, limit=1)
    return hits[0] if hits else None


# ── Mini Apps ───────────────────────────────────────────────────────────────
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9 _\-]{0,31}$")
DEFAULT_APPS = {
    "figma": "https://www.figma.com/files",
    "canva": "https://www.canva.com/",
    "fiverr": "https://www.fiverr.com/",
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/",
    "gemini": "https://gemini.google.com/",
    "github": "https://github.com/",
}


def _apps_path() -> Path:
    return _data() / "miniapps.json"


def mini_apps() -> dict[str, str]:
    try:
        custom = json.loads(_apps_path().read_text(encoding="utf-8"))
        custom = custom if isinstance(custom, dict) else {}
    except (OSError, ValueError):
        custom = {}
    merged = dict(DEFAULT_APPS)
    merged.update({k: v for k, v in custom.items() if v})
    for k, v in custom.items():
        if not v:
            merged.pop(k, None)                       # a removed default
    return merged


def _clean_app_name(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name or "").strip().lower())
    n = re.sub(r"\s*(mini ?app|app)$", "", n).strip()
    if not NAME_RE.match(n):
        raise ValueError("mini app names use letters, digits, spaces, '-' or '_' (max 32)")
    return n


def safe_url(url: str) -> str:
    u = urlsplit(str(url or "").strip())
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise ValueError("mini apps need an https:// URL without embedded credentials")
    return u.geturl()


def add_app(name: str, url: str) -> str:
    name, url = _clean_app_name(name), safe_url(url)
    with _lock:
        try:
            custom = json.loads(_apps_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            custom = {}
        custom[name] = url
        _apps_path().write_text(json.dumps(custom, indent=2), encoding="utf-8")
    return name


def remove_app(name: str) -> None:
    name = _clean_app_name(name)
    if name not in mini_apps():
        raise KeyError(f"no mini app named '{name}'")
    with _lock:
        try:
            custom = json.loads(_apps_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            custom = {}
        custom[name] = ""
        _apps_path().write_text(json.dumps(custom, indent=2), encoding="utf-8")


def _browser() -> Optional[str]:
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    for name in ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def open_app(name: str, *, launcher: Optional[Callable[[list[str]], object]] = None,
             browser: Optional[str] = None) -> str:
    key = _clean_app_name(name)
    apps = mini_apps()
    if key not in apps:
        close = [k for k in apps if key in k or k in key]
        if len(close) == 1:
            key = close[0]
        else:
            raise KeyError(f"no mini app named '{key}'. Known: {', '.join(sorted(apps))}")
    url = safe_url(apps[key])
    exe = browser or _browser()
    profile = _data() / "miniapps" / re.sub(r"[^a-z0-9_-]", "_", key)
    profile.mkdir(parents=True, exist_ok=True)
    if exe:
        cmd = [exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"]
        (launcher or (lambda c: subprocess.Popen(c, close_fds=True)))(cmd)  # noqa: S603 - fixed argv, https-only URL
        return key
    import webbrowser
    webbrowser.open(url)
    return key
