"""Markdown notes (Cherry Studio parity P6). See docs/NOTES.md.

Notes are plain ``.md`` files in one folder, so any editor (or an Obsidian vault)
can open them. Optional front matter holds tags and timestamps:

    ---
    tags: [client, logo]
    created: 2026-11-22T20:10
    ---
    # Logo feedback
    The client wants blue.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MAX_NOTE_BYTES = 2 * 1024 * 1024
_FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
_lock = threading.RLock()


@dataclass
class Note:
    path: Path
    title: str
    tags: list[str] = field(default_factory=list)
    body: str = ""
    updated: float = 0.0


def _config_path() -> Path:
    from jarvis.core.user_data import user_data_dir
    return user_data_dir() / "notes_config.json"


def notes_dir() -> Path:
    env = os.environ.get("JARVIS_NOTES_DIR", "").strip()
    if env:
        folder = Path(env).expanduser()
    else:
        try:
            folder = Path(json.loads(_config_path().read_text(encoding="utf-8"))["folder"]).expanduser()
        except (OSError, ValueError, KeyError, TypeError):
            from jarvis.core.user_data import user_data_dir
            folder = user_data_dir() / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def set_notes_dir(folder: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(folder.strip().strip('"')))).resolve()
    path.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps({"folder": str(path)}), encoding="utf-8")
    return path


def slug(title: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(title or "").strip())
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:80] or "Untitled"


def _parse(path: Path) -> Note:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")[:MAX_NOTE_BYTES]
    except OSError:
        raw = ""
    tags: list[str] = []
    m = _FRONT.match(raw)
    if m:
        for line in m.group(1).splitlines():
            if line.lower().startswith("tags:"):
                tags = [t.strip(" '\"#") for t in line.split(":", 1)[1].strip(" []").split(",") if t.strip(" '\"#")]
        raw = raw[m.end():]
    try:
        updated = path.stat().st_mtime
    except OSError:
        updated = 0.0
    return Note(path, path.stem, tags, raw, updated)


def _render(title: str, body: str, tags: list[str], created: str) -> str:
    front = ""
    if tags or created:
        lines = []
        if tags:
            lines.append("tags: [" + ", ".join(tags) + "]")
        if created:
            lines.append(f"created: {created}")
        front = "---\n" + "\n".join(lines) + "\n---\n"
    body = body.strip()
    heading = f"# {title}\n\n" if not body.startswith("#") else ""
    return f"{front}{heading}{body}\n"


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = tags.split(",")
    out = []
    for t in tags or []:
        t = re.sub(r"[^\w\- ]", "", str(t)).strip().lower().replace(" ", "-")
        if t and t not in out:
            out.append(t[:30])
    return out[:12]


def find(title: str, folder: Optional[Path] = None) -> Optional[Path]:
    folder = folder or notes_dir()
    exact = folder / f"{slug(title)}.md"
    if exact.is_file():
        return exact
    want = slug(title).lower()
    best = None
    for p in folder.rglob("*.md"):
        if ".trash" in p.parts:
            continue
        stem = p.stem.lower()
        if stem == want:
            return p
        if want and want in stem and (best is None or len(p.stem) < len(best.stem)):
            best = p
    return best


def create(title: str, body: str = "", tags=None, *, folder: Optional[Path] = None) -> Path:
    folder = folder or notes_dir()
    title = slug(title)
    with _lock:
        path = folder / f"{title}.md"
        n = 2
        while path.exists():
            path = folder / f"{title} {n}.md"
            n += 1
        path.write_text(_render(path.stem, body, _clean_tags(tags), time.strftime("%Y-%m-%dT%H:%M")), encoding="utf-8")
    return path


def append(title: str, text: str, *, folder: Optional[Path] = None, create_missing: bool = True) -> Path:
    folder = folder or notes_dir()
    with _lock:
        path = find(title, folder)
        if path is None:
            if not create_missing:
                raise FileNotFoundError(f"no note called '{title}'")
            return create(title, text, folder=folder)
        stamp = time.strftime("%Y-%m-%d %H:%M")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n- {stamp}: {text.strip()}\n")
    return path


def read(title: str, *, folder: Optional[Path] = None) -> Note:
    path = find(title, folder)
    if path is None:
        raise FileNotFoundError(f"no note called '{title}'")
    return _parse(path)


def all_notes(folder: Optional[Path] = None) -> list[Note]:
    folder = folder or notes_dir()
    notes = [_parse(p) for p in folder.rglob("*.md") if ".trash" not in p.parts]
    return sorted(notes, key=lambda n: n.updated, reverse=True)


def search(query: str, *, tag: str = "", limit: int = 10, folder: Optional[Path] = None) -> list[tuple[Note, str]]:
    words = [w for w in re.findall(r"\w+", str(query or "").lower()) if len(w) > 1]
    tag = _clean_tags([tag])[0] if tag and _clean_tags([tag]) else ""
    out = []
    for n in all_notes(folder):
        if tag and tag not in n.tags:
            continue
        hay = f"{n.title}\n{n.body}".lower()
        score = sum(hay.count(w) for w in words) + sum(5 for w in words if w in n.title.lower())
        if words and score == 0:
            continue
        snippet = ""
        if words:
            i = min((hay.find(w) for w in words if w in hay), default=0)
            snippet = (n.title + "\n" + n.body)[max(0, i - 60): i + 140].replace("\n", " ").strip()
        out.append((score, n, snippet))
    out.sort(key=lambda t: (-t[0], -t[1].updated))
    return [(n, s) for _, n, s in out[: max(1, limit)]]


def delete(title: str, *, folder: Optional[Path] = None) -> Path:
    """Move a note into the notes folder's .trash (recoverable)."""
    folder = folder or notes_dir()
    path = find(title, folder)
    if path is None:
        raise FileNotFoundError(f"no note called '{title}'")
    trash = folder / ".trash"
    trash.mkdir(exist_ok=True)
    dest = trash / f"{path.stem}-{int(time.time())}.md"
    shutil.move(str(path), dest)
    return dest
