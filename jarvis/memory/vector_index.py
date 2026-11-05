"""Optional real-embedding layer for memory retrieval.

Retrieval already blends FTS5 with a deterministic local similarity. This adds a
second, semantic signal from a real embedding model (Gemini ``text-embedding``),
so "what did I decide about the invoice tool" can match a memory worded
differently. Design rules:

* Off by default. Enable with ``JARVIS_MEMORY_EMBEDDINGS=1``.
* Never blocks retrieval: only vectors already in the local cache are used
  synchronously; missing ones are filled by ``backfill`` (called from a worker).
  The query vector costs one short network call with a hard timeout.
* Privacy: only memories retrieval itself may use (not secret/restricted) are
  ever embedded, and nothing is sent when the flag is off.
* Any failure falls back silently to the existing ranking (fail-soft).
"""
from __future__ import annotations

import contextlib
import hashlib
import math
import os
import sqlite3
import struct
import threading
from pathlib import Path
from typing import Callable, Optional

MODEL = "gemini-embedding-001"
DIMENSIONS = 256
QUERY_TIMEOUT_MS = 2500
VECTOR_ONLY_THRESHOLD = 0.72      # cosine needed to surface a memory with no word overlap
MAX_BACKFILL_PER_RUN = 40

_lock = threading.Lock()
Embedder = Callable[[list[str]], list[list[float]]]


def enabled() -> bool:
    return os.environ.get("JARVIS_MEMORY_EMBEDDINGS", "").strip().lower() in {"1", "true", "yes", "on"}


def _db_path() -> Path:
    from jarvis.memory.memory_manager import BASE_DIR
    return Path(BASE_DIR) / "memory" / "vectors.sqlite3"


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = path or _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=5)
    db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, model TEXT NOT NULL, dim INTEGER NOT NULL, vec BLOB NOT NULL)")
    return db


def _key(text: str) -> str:
    return hashlib.sha256(f"{MODEL}:{DIMENSIONS}:{text}".encode("utf-8")).hexdigest()


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def gemini_embedder(texts: list[str], *, timeout_ms: int = 8000) -> list[list[float]]:
    """Embed with Gemini; raises on any problem (callers fail soft)."""
    from google.genai import types as gtypes
    from jarvis.core import gemini
    result = gemini.client(timeout_ms=timeout_ms).models.embed_content(
        model=MODEL, contents=texts,
        config=gtypes.EmbedContentConfig(output_dimensionality=DIMENSIONS))
    return [list(item.values) for item in result.embeddings]


def cached_vectors(texts: list[str], *, path: Optional[Path] = None) -> dict[str, list[float]]:
    """Vectors already stored, keyed by the text itself."""
    if not texts:
        return {}
    with _lock, contextlib.closing(_connect(path)) as db:
        found: dict[str, list[float]] = {}
        keys = {_key(t): t for t in texts}
        marks = ",".join("?" * len(keys))
        for k, blob in db.execute(f"SELECT key, vec FROM vectors WHERE key IN ({marks})", list(keys)):
            found[keys[k]] = _unpack(blob)
        return found


def store_vectors(pairs: dict[str, list[float]], *, path: Optional[Path] = None) -> None:
    with _lock, contextlib.closing(_connect(path)) as db:
        db.executemany("INSERT OR REPLACE INTO vectors(key, model, dim, vec) VALUES (?,?,?,?)",
                       [(_key(t), MODEL, len(v), _pack(v)) for t, v in pairs.items()])
        db.commit()


def backfill(texts: list[str], *, embedder: Optional[Embedder] = None,
             path: Optional[Path] = None) -> int:
    """Embed and cache texts that have no vector yet. Returns how many were added."""
    from jarvis.core import failsoft
    missing = [t for t in dict.fromkeys(texts) if t.strip()]
    have = cached_vectors(missing, path=path)
    missing = [t for t in missing if t not in have][:MAX_BACKFILL_PER_RUN]
    if not missing:
        return 0
    try:
        vectors = (embedder or gemini_embedder)(missing)
        store_vectors(dict(zip(missing, vectors)), path=path)
        return len(vectors)
    except Exception:
        failsoft.suppress("vector_index:backfill")
        return 0


def score_candidates(query: str, texts: dict[str, str], *, embedder: Optional[Embedder] = None,
                     path: Optional[Path] = None) -> dict[str, float]:
    """Cosine of the query against each cached memory vector, keyed like ``texts``.

    Returns {} when disabled, when the query cannot be embedded, or nothing is cached.
    """
    if not (enabled() or embedder) or not query.strip() or not texts:
        return {}
    from jarvis.core import failsoft
    try:
        embed = embedder or (lambda items: gemini_embedder(items, timeout_ms=QUERY_TIMEOUT_MS))
        qvec = cached_vectors([query], path=path).get(query)
        if qvec is None:
            qvec = embed([query])[0]
            store_vectors({query: qvec}, path=path)
        cache = cached_vectors(list(texts.values()), path=path)
        return {rid: max(0.0, cosine(qvec, cache[text])) for rid, text in texts.items() if text in cache}
    except Exception:
        failsoft.suppress("vector_index:score")
        return {}


_backfill_running = threading.Event()


def backfill_async(texts: list[str]) -> None:
    """Fill missing vectors in a daemon thread; no-op when disabled or already running."""
    if not enabled() or _backfill_running.is_set():
        return
    _backfill_running.set()

    def work():
        try:
            backfill(texts)
        finally:
            _backfill_running.clear()

    threading.Thread(target=work, name="memory-embeddings", daemon=True).start()
