"""Turn a file or web page into plain text for the knowledge base.

Every extractor is fail-soft: an unreadable file returns "" and the caller
records the source as failed instead of raising. Heavy parsers (pdfplumber,
python-docx, python-pptx) are imported lazily so importing this module costs
nothing.
"""
from __future__ import annotations

import html
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_URL_BYTES = 3 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".log", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs",
    ".php", ".rb", ".kt", ".swift", ".sql", ".sh", ".ps1", ".bat", ".css", ".scss", ".xml",
}
HTML_EXTS = {".html", ".htm"}
DOC_EXTS = {".pdf", ".docx", ".pptx"}
SUPPORTED_EXTS = TEXT_EXTS | HTML_EXTS | DOC_EXTS


def supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTS


class _TextParser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(raw: str) -> tuple[str, str]:
    """Return (title, text) for an HTML document."""
    p = _TextParser()
    try:
        p.feed(raw)
        p.close()
    except Exception:
        return "", re.sub(r"<[^>]+>", " ", html.unescape(raw))
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return p.title.strip(), text.strip()


def _read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError:
            return ""
    return ""


def _pdf(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n\n".join((page.extract_text() or "") for page in pdf.pages)
    except ImportError:
        pass
    except Exception:
        return ""
    try:
        import PyPDF2
        with open(path, "rb") as f:
            return "\n\n".join((page.extract_text() or "") for page in PyPDF2.PdfReader(f).pages)
    except Exception:
        return ""


def _docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    except Exception:
        return ""


def _pptx(path: Path) -> str:
    try:
        from pptx import Presentation
        out = []
        for i, slide in enumerate(Presentation(str(path)).slides, 1):
            out.append(f"# Slide {i}")
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    out.append(shape.text_frame.text)
        return "\n".join(out)
    except Exception:
        return ""


def extract_file(path: Path) -> tuple[str, str]:
    """Return (title, text) for a local file; ("", "") when unsupported or unreadable."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return "", ""
    except OSError:
        return "", ""
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        text = _read_text(path)
    elif ext in HTML_EXTS:
        title, text = html_to_text(_read_text(path))
        return title or path.name, text[:MAX_TEXT_CHARS]
    elif ext == ".pdf":
        text = _pdf(path)
    elif ext == ".docx":
        text = _docx(path)
    elif ext == ".pptx":
        text = _pptx(path)
    else:
        return "", ""
    return path.name, (text or "")[:MAX_TEXT_CHARS]


def fetch_url(url: str, *, timeout: float = 15.0) -> tuple[str, str]:
    """Download a web page and return (title, text). Raises on network errors."""
    if not re.match(r"^https?://", url, re.I):
        raise ValueError("only http(s) URLs can be added")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (JARVIS knowledge base)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme checked above
        raw = resp.read(MAX_URL_BYTES + 1)[:MAX_URL_BYTES]
        charset = resp.headers.get_content_charset() or "utf-8"
        ctype = (resp.headers.get_content_type() or "").lower()
    body = raw.decode(charset, errors="replace")
    if "html" in ctype or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        title, text = html_to_text(body)
    else:
        title, text = "", body
    return title or url, text[:MAX_TEXT_CHARS]


def chunk_text(text: str, *, size: int = 900, overlap: int = 150) -> list[str]:
    """Split text into overlapping chunks, preferring paragraph and sentence boundaries."""
    text = re.sub(r"\r\n?", "\n", text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for p in paras:
        if len(p) <= size:
            pieces.append(p)
            continue
        sentences = re.split(r"(?<=[.!?।])\s+", p)
        buf = ""
        for s in sentences:
            while len(s) > size:                     # one huge "sentence": hard split
                if buf:
                    pieces.append(buf)
                    buf = ""
                pieces.append(s[:size])
                s = s[size - overlap:]
            if len(buf) + len(s) + 1 > size and buf:
                pieces.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            pieces.append(buf)
    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        if len(cur) + len(piece) + 2 <= size:
            cur = f"{cur}\n\n{piece}".strip()
            continue
        if cur:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = f"{tail}\n\n{piece}".strip() if tail and len(tail) + len(piece) + 2 <= size else piece
        else:
            cur = piece
    if cur:
        chunks.append(cur)
    return chunks
