"""Translation of text, clipboard and documents (Cherry Studio parity P4). See docs/TRANSLATION.md."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from jarvis.core import text_brain

MAX_CHUNK = 3500
MAX_DOC_CHARS = 400_000
HISTORY_KEEP = 200
_MARK = "⟦{}⟧"
_MARK_RE = re.compile(r"⟦(\d+)⟧")

Asker = Callable[[str, str], str]

_SYSTEM = ("You are a professional translator. Translate faithfully and naturally, keep meaning, tone, numbers, "
           "names, Markdown, code and URLs unchanged. Output ONLY the translation, no notes.")


def _default_ask(prompt: str, system: str) -> str:
    return text_brain.ask_text(prompt, system, task="translate")


def _prompt(text: str, target: str, source: str = "", tone: str = "") -> str:
    src = f" from {source}" if source and source.lower() != "auto" else ""
    extra = f" Use a {tone} tone." if tone else ""
    if target.lower() in ("sinhala", "සිංහල", "si"):
        extra += " Write in Sinhala script (not transliteration); keep common English technical terms in English."
    return f"Translate the following text{src} into {target}.{extra}\n\n{text}"


def split_chunks(text: str, limit: int = MAX_CHUNK) -> list[str]:
    paras = re.split(r"(\n\s*\n)", text)
    chunks, cur = [], ""
    for piece in paras:
        if len(cur) + len(piece) > limit and cur.strip():
            chunks.append(cur)
            cur = ""
        while len(piece) > limit:
            chunks.append(piece[:limit])
            piece = piece[limit:]
        cur += piece
    if cur.strip():
        chunks.append(cur)
    return chunks


def translate_text(text: str, target: str, *, source: str = "", tone: str = "", ask: Optional[Asker] = None) -> str:
    text = str(text or "")
    target = str(target or "").strip()
    if not text.strip():
        raise ValueError("there is no text to translate")
    if not target:
        raise ValueError("which language should I translate into?")
    ask = ask or _default_ask
    out = [ask(_prompt(chunk, target, source, tone), _SYSTEM).strip() for chunk in split_chunks(text)]
    result = "\n\n".join(o for o in out if o)
    _remember(text, result, target)
    return result


def translate_segments(segments: list[str], target: str, *, source: str = "", ask: Optional[Asker] = None) -> list[str]:
    """Translate many short segments with few calls; segment count and order are preserved."""
    ask = ask or _default_ask
    result = list(segments)
    todo = [(i, s) for i, s in enumerate(segments) if s.strip()]
    batch: list[tuple[int, str]] = []

    def run(items: list[tuple[int, str]]) -> None:
        if not items:
            return
        body = "\n".join(f"{_MARK.format(n)} {s}" for n, (_, s) in enumerate(items))
        prompt = _prompt(body, target, source) + (
            "\n\nEach segment starts with a marker like ⟦0⟧. Keep every marker exactly, in order, "
            "one translated segment after each marker.")
        reply = ask(prompt, _SYSTEM)
        parts = _MARK_RE.split(reply)
        found = {int(parts[k]): parts[k + 1].strip() for k in range(1, len(parts) - 1, 2)}
        if len(found) != len(items):                       # model broke the markers: one call per segment
            for idx, s in items:
                result[idx] = ask(_prompt(s, target, source), _SYSTEM).strip()
            return
        for n, (idx, _) in enumerate(items):
            result[idx] = found.get(n, segments[idx])

    size = 0
    for item in todo:
        if batch and (size + len(item[1]) > MAX_CHUNK or len(batch) >= 60):
            run(batch)
            batch, size = [], 0
        batch.append(item)
        size += len(item[1])
    run(batch)
    return result


def _out_path(src: Path, target: str, ext: str) -> Path:
    tag = re.sub(r"[^\w\- ]", "", target).strip()[:24] or "translated"
    out = src.with_name(f"{src.stem} ({tag}){ext}")
    n = 2
    while out.exists():
        out = src.with_name(f"{src.stem} ({tag} {n}){ext}")
        n += 1
    return out


def translate_file(path: str | Path, target: str, *, source: str = "", ask: Optional[Asker] = None) -> Path:
    """Translate a document; the result is saved next to it (and listed in the file library)."""
    out = _translate_file(path, target, source=source, ask=ask)
    from jarvis import library
    library.register(out, "translation", source="translate", note=f"{Path(path).name} -> {target}")
    return out


def _translate_file(path: str | Path, target: str, *, source: str = "", ask: Optional[Asker] = None) -> Path:
    src = Path(path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"file not found: {src}")
    ext = src.suffix.lower()
    if ext == ".docx":
        from docx import Document
        doc = Document(str(src))
        paras = list(doc.paragraphs)
        cells = [p for t in doc.tables for row in t.rows for c in row.cells for p in c.paragraphs]
        allp = paras + cells
        translated = translate_segments([p.text for p in allp], target, source=source, ask=ask)
        for p, new in zip(allp, translated):
            if p.text.strip() and new != p.text:
                runs = p.runs
                if runs:
                    runs[0].text = new                        # keep the first run's formatting
                    for r in runs[1:]:
                        r.text = ""
                else:
                    p.text = new
        out = _out_path(src, target, ".docx")
        doc.save(str(out))
        return out
    if ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(str(src))
        frames = [para for slide in prs.slides for shape in slide.shapes
                  if getattr(shape, "has_text_frame", False) for para in shape.text_frame.paragraphs]
        texts = ["".join(r.text for r in para.runs) for para in frames]
        translated = translate_segments(texts, target, source=source, ask=ask)
        for para, old, new in zip(frames, texts, translated):
            if old.strip() and para.runs:
                para.runs[0].text = new
                for r in para.runs[1:]:
                    r.text = ""
        out = _out_path(src, target, ".pptx")
        prs.save(str(out))
        return out
    from jarvis.knowledge import extract
    if ext not in extract.SUPPORTED_EXTS:
        raise ValueError(f"cannot translate {ext} files yet")
    _, text = extract.extract_file(src)
    if not text.strip():
        raise ValueError("no readable text in that file (a scanned PDF needs OCR first)")
    text = text[:MAX_DOC_CHARS]
    result = translate_text(text, target, source=source, ask=ask)
    if ext == ".pdf":
        from docx import Document
        doc = Document()
        for para in result.split("\n\n"):
            if para.strip():
                doc.add_paragraph(para.strip())
        out = _out_path(src, target, ".docx")
        doc.save(str(out))
        return out
    out = _out_path(src, target, ".md" if ext in (".md", ".markdown") else ".txt")
    out.write_text(result, encoding="utf-8")
    return out


# ── history ────────────────────────────────────────────────────────────────
_hist_lock = threading.Lock()


def _history_path() -> Path:
    from jarvis.core.user_data import user_data_dir
    folder = user_data_dir() / "translate"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "history.jsonl"


def _remember(source: str, result: str, target: str) -> None:
    try:
        path = _history_path()
        entry = json.dumps({"t": int(time.time()), "to": target[:40], "src": source[:500], "out": result[:500]},
                           ensure_ascii=False)
        with _hist_lock:
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            lines = (lines + [entry])[-HISTORY_KEEP:]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return


def history(limit: int = 10) -> list[dict]:
    try:
        lines = _history_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-max(1, limit):]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(out))
