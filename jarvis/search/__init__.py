"""Global search across conversations, memory, knowledge bases, notes and the file library (Cherry parity P12).

Conversation archive
--------------------
Owner/assistant lines from the HUD log are appended to ``<data>/history/YYYY-MM-DD.jsonl``
(local only). Only lines judged safe by the web UI's redaction rules are kept: authentication
lines and credential-shaped commands are dropped, secrets and home paths are scrubbed, and
nothing is recorded while JARVIS is locked, waiting for a PIN, silent or in Guest Mode.
Turn it off with ``JARVIS_CHAT_HISTORY=0``. Old days are deleted after ``JARVIS_CHAT_HISTORY_DAYS``
(default 180).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

_lock = threading.Lock()


def history_enabled() -> bool:
    return os.environ.get("JARVIS_CHAT_HISTORY", "1").strip().lower() not in {"0", "false", "no", "off"}


def _history_dir() -> Path:
    from jarvis.core.user_data import user_data_dir
    d = user_data_dir() / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _default_available() -> bool:
    try:
        from jarvis.core import identity, security
        m = security.get_auth_manager()
        return not (m.is_privacy_lock_active() or m.needs_pin() or m.is_silent()
                    or identity.get_identity_manager().guest_mode_active())
    except Exception:
        return False


class ConversationArchive:
    def __init__(self, folder: Optional[Path] = None, *, available: Callable[[], bool] = _default_available,
                 clock: Callable[[], float] = time.time) -> None:
        self._folder = folder
        self._available = available
        self._clock = clock

    @property
    def folder(self) -> Path:
        return self._folder or _history_dir()

    def on_line(self, line: str) -> None:
        if not history_enabled():
            return
        try:
            if not self._available():
                return
            from jarvis.webui import redact
            c = redact.classify(line)
            if not c or c[0] not in ("you", "ai"):
                return
            text = redact.scrub(c[1]).strip()
            if not text:
                return
            ts = self._clock()
            entry = json.dumps({"t": int(ts), "role": "owner" if c[0] == "you" else "jarvis", "text": text[:4000]},
                               ensure_ascii=False)
            path = self.folder / (time.strftime("%Y-%m-%d", time.localtime(ts)) + ".jsonl")
            with _lock, path.open("a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            return

    def prune(self, keep_days: Optional[int] = None) -> int:
        keep_days = keep_days or int(os.environ.get("JARVIS_CHAT_HISTORY_DAYS", "180") or 180)
        cutoff = time.strftime("%Y-%m-%d", time.localtime(self._clock() - keep_days * 86400))
        removed = 0
        for p in self.folder.glob("*.jsonl"):
            if p.stem < cutoff:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    continue
        return removed

    def search(self, query: str, *, days: int = 90, limit: int = 10) -> list[dict]:
        words = [w for w in re.findall(r"\w+", str(query or "").lower()) if len(w) > 1]
        if not words:
            return []
        cutoff = time.strftime("%Y-%m-%d", time.localtime(self._clock() - days * 86400))
        hits = []
        for p in sorted(self.folder.glob("*.jsonl"), reverse=True):
            if p.stem < cutoff:
                break
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                low = e.get("text", "").lower()
                score = sum(low.count(w) for w in words)
                if score and all(w in low for w in words[:3]):
                    hits.append((score, e))
        hits.sort(key=lambda h: (-h[0], -h[1].get("t", 0)))
        return [e for _, e in hits[:limit]]

    def clear(self) -> int:
        n = 0
        for p in self.folder.glob("*.jsonl"):
            p.unlink()
            n += 1
        return n


_archive: Optional[ConversationArchive] = None


def get_archive() -> ConversationArchive:
    global _archive
    if _archive is None:
        _archive = ConversationArchive()
    return _archive


def start_archive() -> Optional[ConversationArchive]:
    """Called once from JarvisLive: subscribe the archive to the HUD log."""
    if not history_enabled():
        return None
    from jarvis.core import log_tap
    arc = get_archive()
    log_tap.subscribe(arc.on_line)
    threading.Thread(target=arc.prune, name="history-prune", daemon=True).start()
    return arc


def search_all(query: str, *, sources: Optional[set[str]] = None, limit: int = 5) -> dict[str, list[dict]]:
    """Results grouped by source; each source fails soft on its own."""
    query = str(query or "").strip()
    want = sources or {"conversations", "memory", "knowledge", "notes", "files"}
    out: dict[str, list[dict]] = {}
    if not query:
        return out
    if "conversations" in want:
        try:
            out["conversations"] = [{"title": time.strftime("%Y-%m-%d %H:%M", time.localtime(e["t"])) + f" ({e['role']})",
                                     "text": e["text"][:240]} for e in get_archive().search(query, limit=limit)]
        except Exception:
            out["conversations"] = []
    if "memory" in want:
        try:
            from jarvis.memory.retrieval_engine import retrieve
            rows = retrieve(query, top_k=limit, log_usage=False, provider_safe=True)
            out["memory"] = [{"title": str(r.get("category") or r.get("type") or "memory"),
                              "text": str(r.get("value") or r.get("text") or "")[:240]} for r in rows]
        except Exception:
            out["memory"] = []
    if "knowledge" in want:
        try:
            from jarvis.knowledge import get_store
            out["knowledge"] = [{"title": f"{h.title} ({h.base})", "text": h.text[:240], "path": h.location}
                                for h in get_store().search(query, limit=limit)]
        except Exception:
            out["knowledge"] = []
    if "notes" in want:
        try:
            from jarvis import notes
            out["notes"] = [{"title": n.title, "text": s, "path": str(n.path)} for n, s in notes.search(query, limit=limit)]
        except Exception:
            out["notes"] = []
    if "files" in want:
        try:
            from jarvis import library
            out["files"] = [{"title": f"{i['name']} [{i['kind']}]", "text": "", "path": i["path"]}
                            for i in library.items(query=query, limit=limit)]
        except Exception:
            out["files"] = []
    return out


def format_results(results: dict[str, list[dict]]) -> str:
    blocks = []
    for source, rows in results.items():
        if not rows:
            continue
        lines = [f"## {source}"] + [f"- {r['title']}: {r['text']}".rstrip(": ") for r in rows]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
