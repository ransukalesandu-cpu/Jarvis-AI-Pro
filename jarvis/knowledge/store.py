"""Local knowledge bases: files, folders and web pages JARVIS can search and cite.

Storage is one SQLite file under the user data folder (``knowledge/kb.sqlite``):

* ``bases``   — named knowledge bases ("work", "university", ...)
* ``sources`` — what was added: a file, a folder (expanded to files), a URL or pasted text
* ``chunks``  — overlapping text chunks, indexed with FTS5 for keyword search
* ``vectors`` — optional Gemini embeddings per chunk (``JARVIS_KB_EMBEDDINGS=1``)

Search blends BM25 keyword rank with embedding similarity when vectors exist.
With embeddings off (the default) or offline, keyword search still works.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import extract

Embedder = Callable[[list[str]], list[list[float]]]

MAX_FOLDER_FILES = 2000
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9 _\-]{0,47}$")
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea", ".vscode"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bases (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY, base_id INTEGER NOT NULL REFERENCES bases(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, location TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '', mtime REAL NOT NULL DEFAULT 0, sha TEXT NOT NULL DEFAULT '',
    chunks INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'ok', error TEXT NOT NULL DEFAULT '',
    added REAL NOT NULL, UNIQUE(base_id, location));
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    base_id INTEGER NOT NULL, ord INTEGER NOT NULL, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content='chunks', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
CREATE TABLE IF NOT EXISTS vectors (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE, vec BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def embeddings_enabled() -> bool:
    return os.environ.get("JARVIS_KB_EMBEDDINGS", "").strip().lower() in {"1", "true", "yes", "on"}


def default_db_path() -> Path:
    from jarvis.core.user_data import user_data_dir
    folder = user_data_dir() / "knowledge"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "kb.sqlite"


def clean_name(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name or "").strip().lower())
    if not NAME_RE.match(n):
        raise ValueError("knowledge base names use letters, digits, spaces, '-' or '_' (max 48)")
    return n


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _fts_query(q: str) -> str:
    words = re.findall(r"\w+", q.lower())
    words = [w for w in words if len(w) > 1][:24]
    return " OR ".join(f'"{w}"' for w in words)


@dataclass
class Hit:
    chunk_id: int
    base: str
    source_id: int
    title: str
    location: str
    text: str
    score: float


@dataclass
class AddResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.added} added", f"{self.updated} updated", f"{self.unchanged} unchanged"]
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        return ", ".join(parts)


class KnowledgeStore:
    def __init__(self, path: Optional[Path] = None, *, embedder: Optional[Embedder] = None,
                 fetcher: Callable[[str], tuple[str, str]] = extract.fetch_url) -> None:
        self.path = Path(path) if path else default_db_path()
        self._embedder = embedder
        self._fetch = fetcher
        self._lock = threading.RLock()
        with self._db() as db:
            db.executescript(_SCHEMA)

    # ── plumbing ────────────────────────────────────────────────────────────
    @contextlib.contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with self._lock:
                yield db
                db.commit()
        finally:
            db.close()

    def _embedder_or_none(self) -> Optional[Embedder]:
        if self._embedder is not None:
            return self._embedder
        if not embeddings_enabled():
            return None
        from jarvis.core import privacy
        if privacy.offline_enabled():
            return None
        from jarvis.memory import vector_index
        return lambda texts: vector_index.gemini_embedder(texts)

    def _base_id(self, db, name: str, *, create: bool = False) -> int:
        name = clean_name(name)
        row = db.execute("SELECT id FROM bases WHERE name=?", (name,)).fetchone()
        if row:
            return int(row["id"])
        if not create:
            raise KeyError(f"no knowledge base named '{name}'")
        cur = db.execute("INSERT INTO bases(name, created) VALUES (?, ?)", (name, time.time()))
        return int(cur.lastrowid)

    # ── bases ───────────────────────────────────────────────────────────────
    def create_base(self, name: str, description: str = "") -> str:
        name = clean_name(name)
        with self._db() as db:
            if db.execute("SELECT 1 FROM bases WHERE name=?", (name,)).fetchone():
                raise ValueError(f"knowledge base '{name}' already exists")
            db.execute("INSERT INTO bases(name, description, created) VALUES (?,?,?)",
                       (name, str(description or "")[:300], time.time()))
        return name

    def list_bases(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute(
                "SELECT b.name, b.description, COUNT(DISTINCT s.id) AS sources, COALESCE(SUM(s.chunks),0) AS chunks "
                "FROM bases b LEFT JOIN sources s ON s.base_id=b.id GROUP BY b.id ORDER BY b.name").fetchall()
        return [dict(r) for r in rows]

    def delete_base(self, name: str) -> None:
        with self._db() as db:
            bid = self._base_id(db, name)
            db.execute("DELETE FROM chunks WHERE base_id=?", (bid,))
            db.execute("DELETE FROM bases WHERE id=?", (bid,))

    def get_active(self) -> str:
        with self._db() as db:
            row = db.execute("SELECT value FROM meta WHERE key='active'").fetchone()
        return row["value"] if row else ""

    def set_active(self, name: str) -> str:
        with self._db() as db:
            if name:
                name = clean_name(name)
                self._base_id(db, name)
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('active', ?)", (name,))
        return name

    def list_sources(self, name: str) -> list[dict]:
        with self._db() as db:
            bid = self._base_id(db, name)
            rows = db.execute("SELECT id, kind, location, title, chunks, status, error, added FROM sources "
                              "WHERE base_id=? ORDER BY added DESC", (bid,)).fetchall()
        return [dict(r) for r in rows]

    # ── adding ──────────────────────────────────────────────────────────────
    def _write_source(self, db, bid: int, kind: str, location: str, title: str, text: str,
                      *, parent: str = "", mtime: float = 0.0) -> str:
        """Insert or refresh one source. Returns 'added' | 'updated' | 'unchanged' | 'failed'."""
        sha = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest() if text else ""
        row = db.execute("SELECT id, sha FROM sources WHERE base_id=? AND location=?", (bid, location)).fetchone()
        if row and sha and row["sha"] == sha:
            db.execute("UPDATE sources SET mtime=? WHERE id=?", (mtime, row["id"]))
            return "unchanged"
        chunks = extract.chunk_text(text)
        status, error = ("ok", "") if chunks else ("failed", "no readable text")
        if row:
            sid = int(row["id"])
            db.execute("DELETE FROM chunks WHERE source_id=?", (sid,))
            db.execute("UPDATE sources SET title=?, mtime=?, sha=?, chunks=?, status=?, error=?, parent=COALESCE(NULLIF(?, ''), parent) WHERE id=?",
                       (title[:200], mtime, sha, len(chunks), status, error, parent, sid))
            outcome = "updated"
        else:
            cur = db.execute(
                "INSERT INTO sources(base_id, kind, location, title, parent, mtime, sha, chunks, status, error, added) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (bid, kind, location, title[:200], parent, mtime, sha, len(chunks), status, error, time.time()))
            sid = int(cur.lastrowid)
            outcome = "added"
        db.executemany("INSERT INTO chunks(source_id, base_id, ord, text) VALUES (?,?,?,?)",
                       [(sid, bid, i, c) for i, c in enumerate(chunks)])
        return outcome if chunks else "failed"

    def _iter_folder(self, folder: Path) -> Iterable[Path]:
        count = 0
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            for f in sorted(files):
                p = Path(root) / f
                if extract.supported(p):
                    yield p
                    count += 1
                    if count >= MAX_FOLDER_FILES:
                        return

    def add_path(self, name: str, target: str, *, create: bool = True) -> AddResult:
        path = Path(os.path.expandvars(os.path.expanduser(str(target).strip().strip('"')))).resolve()
        result = AddResult()
        if not path.exists():
            raise FileNotFoundError(f"not found: {path}")
        files = list(self._iter_folder(path)) if path.is_dir() else [path]
        parent = str(path) if path.is_dir() else ""
        with self._db() as db:
            bid = self._base_id(db, name, create=create)
            if parent:
                db.execute("INSERT OR IGNORE INTO sources(base_id, kind, location, title, added) VALUES (?,?,?,?,?)",
                           (bid, "folder", parent, path.name, time.time()))
            for f in files:
                title, text = extract.extract_file(f)
                try:
                    mtime = f.stat().st_mtime
                except OSError:
                    mtime = 0.0
                outcome = self._write_source(db, bid, "file", str(f), title or f.name, text, parent=parent, mtime=mtime)
                self._tally(result, outcome, str(f))
            if parent:
                n = db.execute("SELECT COALESCE(SUM(chunks),0) FROM sources WHERE base_id=? AND parent=?",
                               (bid, parent)).fetchone()[0]
                db.execute("UPDATE sources SET chunks=0, status='ok', title=? WHERE base_id=? AND location=?",
                           (f"{path.name} ({len(files)} files, {n} chunks)", bid, parent))
        self._embed_pending()
        return result

    def add_url(self, name: str, url: str, *, create: bool = True) -> AddResult:
        result = AddResult()
        title, text = self._fetch(url.strip())
        with self._db() as db:
            bid = self._base_id(db, name, create=create)
            self._tally(result, self._write_source(db, bid, "url", url.strip(), title, text), url)
        self._embed_pending()
        return result

    def add_text(self, name: str, title: str, text: str, *, create: bool = True) -> AddResult:
        result = AddResult()
        title = (title or "note").strip()[:120]
        location = f"text:{hashlib.sha1((title + text).encode('utf-8', 'ignore')).hexdigest()[:16]}"
        with self._db() as db:
            bid = self._base_id(db, name, create=create)
            self._tally(result, self._write_source(db, bid, "text", location, title, text), title)
        self._embed_pending()
        return result

    @staticmethod
    def _tally(result: AddResult, outcome: str, label: str) -> None:
        if outcome == "added":
            result.added += 1
        elif outcome == "updated":
            result.updated += 1
        elif outcome == "unchanged":
            result.unchanged += 1
        else:
            result.failed.append(label)

    def remove_source(self, name: str, location_or_id: str) -> int:
        """Remove a source (and, for a folder, every file under it). Returns sources removed."""
        with self._db() as db:
            bid = self._base_id(db, name)
            key = str(location_or_id).strip()
            rows = db.execute("SELECT id, location, kind FROM sources WHERE base_id=? AND (location=? OR CAST(id AS TEXT)=?)",
                              (bid, key, key)).fetchall()
            if not rows:
                rows = db.execute("SELECT id, location, kind FROM sources WHERE base_id=? AND title LIKE ?",
                                  (bid, f"%{key}%")).fetchall()
            ids = [r["id"] for r in rows]
            for r in rows:
                if r["kind"] == "folder":
                    ids += [x["id"] for x in db.execute("SELECT id FROM sources WHERE base_id=? AND parent=?",
                                                         (bid, r["location"])).fetchall()]
            for sid in set(ids):
                db.execute("DELETE FROM chunks WHERE source_id=?", (sid,))
                db.execute("DELETE FROM sources WHERE id=?", (sid,))
        return len(set(ids))

    def refresh(self, name: str) -> AddResult:
        """Re-read every file/folder source: changed files are re-indexed, deleted ones removed."""
        result = AddResult()
        with self._db() as db:
            bid = self._base_id(db, name)
            folders = [r["location"] for r in db.execute(
                "SELECT location FROM sources WHERE base_id=? AND kind='folder'", (bid,)).fetchall()]
            files = db.execute("SELECT id, location, mtime FROM sources WHERE base_id=? AND kind='file'", (bid,)).fetchall()
            known = {r["location"] for r in files}
            for r in files:
                p = Path(r["location"])
                if not p.exists():
                    db.execute("DELETE FROM chunks WHERE source_id=?", (r["id"],))
                    db.execute("DELETE FROM sources WHERE id=?", (r["id"],))
                    continue
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                if abs(mtime - r["mtime"]) < 1e-6:
                    result.unchanged += 1
                    continue
                title, text = extract.extract_file(p)
                self._tally(result, self._write_source(db, bid, "file", str(p), title or p.name, text,
                                                       mtime=mtime), str(p))
            for folder in folders:
                fp = Path(folder)
                if not fp.is_dir():
                    continue
                for f in self._iter_folder(fp):
                    if str(f) in known:
                        continue
                    title, text = extract.extract_file(f)
                    self._tally(result, self._write_source(db, bid, "file", str(f), title or f.name, text,
                                                           parent=folder, mtime=f.stat().st_mtime), str(f))
        self._embed_pending()
        return result

    # ── embeddings ──────────────────────────────────────────────────────────
    def _embed_pending(self, batch: int = 64, limit: int = 2000) -> int:
        embed = self._embedder_or_none()
        if embed is None:
            return 0
        done = 0
        while done < limit:
            with self._db() as db:
                rows = db.execute("SELECT c.id, c.text FROM chunks c LEFT JOIN vectors v ON v.chunk_id=c.id "
                                  "WHERE v.chunk_id IS NULL LIMIT ?", (batch,)).fetchall()
            if not rows:
                break
            try:
                vecs = embed([r["text"][:6000] for r in rows])
            except Exception:
                break                                   # fail soft: keyword search still works
            with self._db() as db:
                db.executemany("INSERT OR REPLACE INTO vectors(chunk_id, vec) VALUES (?,?)",
                               [(r["id"], _pack(v)) for r, v in zip(rows, vecs)])
            done += len(rows)
        return done

    # ── search ──────────────────────────────────────────────────────────────
    def search(self, query: str, *, base: str = "", limit: int = 6) -> list[Hit]:
        query = str(query or "").strip()
        if not query:
            return []
        limit = max(1, min(int(limit or 6), 20))
        fts = _fts_query(query)
        with self._db() as db:
            where, args = "", []
            if base:
                where = "AND c.base_id=?"
                args = [self._base_id(db, base)]
            scored: dict[int, float] = {}
            if fts:
                rows = db.execute(
                    f"SELECT c.id, bm25(chunks_fts) AS r FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid "
                    f"WHERE chunks_fts MATCH ? {where} ORDER BY r LIMIT ?", [fts, *args, limit * 5]).fetchall()
                if rows:
                    worst = max(-r["r"] for r in rows) or 1.0
                    for r in rows:
                        scored[r["id"]] = 0.6 * max(0.0, -r["r"]) / worst
            embed = self._embedder_or_none()
            if embed is not None:
                try:
                    qv = embed([query])[0]
                except Exception:
                    qv = None
                if qv:
                    vrows = db.execute(f"SELECT v.chunk_id, v.vec FROM vectors v JOIN chunks c ON c.id=v.chunk_id "
                                       f"WHERE 1=1 {where}", args).fetchall()
                    sims = sorted(((_cosine(qv, _unpack(r["vec"])), r["chunk_id"]) for r in vrows), reverse=True)
                    for sim, cid in sims[: limit * 5]:
                        scored[cid] = scored.get(cid, 0.0) + 0.4 * max(0.0, sim) + (0.2 if sim > 0.75 else 0.0)
            if not scored:
                return []
            top = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)[:limit]
            ids = [cid for cid, _ in top]
            qmarks = ",".join("?" * len(ids))
            rows = {r["id"]: r for r in db.execute(
                f"SELECT c.id, c.text, c.source_id, s.title, s.location, b.name AS base FROM chunks c "
                f"JOIN sources s ON s.id=c.source_id JOIN bases b ON b.id=c.base_id WHERE c.id IN ({qmarks})",
                ids).fetchall()}
        return [Hit(cid, rows[cid]["base"], rows[cid]["source_id"], rows[cid]["title"], rows[cid]["location"],
                    rows[cid]["text"], round(score, 4)) for cid, score in top if cid in rows]

    def stats(self) -> dict:
        with self._db() as db:
            return {
                "bases": db.execute("SELECT COUNT(*) FROM bases").fetchone()[0],
                "sources": db.execute("SELECT COUNT(*) FROM sources WHERE kind!='folder'").fetchone()[0],
                "chunks": db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "vectors": db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0],
            }


_store: Optional[KnowledgeStore] = None
_store_lock = threading.Lock()


def get_store() -> KnowledgeStore:
    global _store
    with _store_lock:
        if _store is None or _store.path != default_db_path():
            _store = KnowledgeStore()
        return _store


def format_hits(hits: list[Hit], *, max_chars: int = 7000) -> str:
    """Numbered, citable context block for the model."""
    out, used = [], 0
    for i, h in enumerate(hits, 1):
        block = f"[{i}] {h.title} ({h.base}: {h.location})\n{h.text.strip()}"
        if used + len(block) > max_chars:
            block = block[: max(0, max_chars - used)]
        if not block:
            break
        out.append(block)
        used += len(block)
    return "\n\n".join(out)
