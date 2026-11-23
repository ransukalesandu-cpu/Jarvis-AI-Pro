"""Next-generation web UI host (React + TypeScript + Vite inside QWebEngineView).

Nothing here imports Qt at module import time, so ``jarvis.webui.contract`` can be used and tested
without a display. See docs/architecture/NEXT_GEN_UI.md.
"""
from __future__ import annotations

import os
from pathlib import Path

DIST = Path(__file__).resolve().parent / "dist"


def dist_ready() -> bool:
    return (DIST / "index.html").is_file()


def ui_mode() -> str:
    """'web' by default when the bundle exists; JARVIS_UI=legacy (or any other value) forces the classic HUD.

    A web start-up failure (no QtWebEngine, no WebGL 2) still falls back to the classic HUD.
    """
    want = os.environ.get("JARVIS_UI", "web").strip().lower()
    return "web" if want == "web" and dist_ready() else "legacy"
