"""Navigation policy for the web UI page. Only QtCore, so it is importable (and testable) anywhere."""
from __future__ import annotations

from PyQt6.QtCore import QUrl

from . import DIST


def is_allowed_url(url: QUrl) -> bool:
    """Only the bundled dist may be navigated to (index.html with an optional query/hash)."""
    if url.scheme() != "file":
        return False
    p = url.toLocalFile().replace("\\", "/").rstrip("/")
    root = str(DIST).replace("\\", "/").rstrip("/")
    return p == root or p.startswith(root + "/")
