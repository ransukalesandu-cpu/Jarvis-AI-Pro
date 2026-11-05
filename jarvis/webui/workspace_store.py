"""Named window layouts for the web UI, saved as JSON.

The legacy HUD keeps dock-based snapshots in config/workspaces.json (core/window_manager.py). The web UI
uses free-form rectangles, so its layouts live in a separate file until the legacy view is retired (Phase 3).
Everything read from disk or from the page is validated; a bad or outdated layout is dropped, never applied.
No Qt in this module.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

WINDOW_KINDS = frozenset({"monitor", "models", "activity", "log", "timer", "bento"})
WINDOW_STATES = frozenset({"normal", "minimized", "maximized"})
PAGES = frozenset({"home", "chat", "activity", "models", "research", "reminders", "apps", "files", "memory", "automation", "monitor", "security"})
MAX_WINDOWS = 12
MAX_WORKSPACES = 24
LAST = "_last"                      # autosaved layout restored on start; hidden from the user's list
_NAME = re.compile(r"^[a-z0-9][a-z0-9 _-]{0,31}$")


def default_path() -> Path:
    base = Path(sys.executable).parent / "config" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent / "config"
    return base / "web_workspaces.json"


def clean_name(name: Any, *, allow_internal: bool = False) -> str | None:
    if not isinstance(name, str):
        return None
    n = name.strip().lower()
    if allow_internal and n == LAST:
        return n
    return n if _NAME.match(n) else None


def _num(v: Any, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


def validate_layout(layout: Any) -> dict | None:
    """Return a cleaned copy of a layout, or None if any part of it is invalid."""
    if not isinstance(layout, dict) or set(layout) - {"windows", "page"}:
        return None
    wins = layout.get("windows")
    page = layout.get("page", "home")
    if not isinstance(wins, list) or len(wins) > MAX_WINDOWS or page not in PAGES:
        return None
    out, seen = [], set()
    for w in wins:
        if not isinstance(w, dict) or set(w) != {"id", "kind", "x", "y", "w", "h", "z", "state"}:
            return None
        if not (isinstance(w["id"], str) and 0 < len(w["id"]) <= 40 and w["id"] not in seen):
            return None
        if w["kind"] not in WINDOW_KINDS or w["state"] not in WINDOW_STATES:
            return None
        if not (_num(w["x"], -4000, 8000) and _num(w["y"], -4000, 8000) and _num(w["w"], 200, 8000)
                and _num(w["h"], 120, 8000) and _num(w["z"], 0, 100000)):
            return None
        seen.add(w["id"])
        out.append({"id": w["id"], "kind": w["kind"], "x": float(w["x"]), "y": float(w["y"]),
                    "w": float(w["w"]), "h": float(w["h"]), "z": int(w["z"]), "state": w["state"]})
    return {"windows": out, "page": page}


class WorkspaceStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_path()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            return True
        except OSError:
            return False

    def names(self) -> list[str]:
        return sorted(n for n in self._read() if clean_name(n) is not None)

    def save(self, name: Any, layout: Any) -> bool:
        n = clean_name(name, allow_internal=True)
        lay = validate_layout(layout)
        if n is None or lay is None:
            return False
        data = self._read()
        if n not in data and n != LAST and len(self.names()) >= MAX_WORKSPACES:
            return False
        data[n] = lay
        return self._write(data)

    def load(self, name: Any) -> dict | None:
        n = clean_name(name, allow_internal=True)
        if n is None:
            return None
        return validate_layout(self._read().get(n))   # outdated/corrupt entries come back as None

    def delete(self, name: Any) -> bool:
        n = clean_name(name)
        if n is None:
            return False
        data = self._read()
        if data.pop(n, None) is None:
            return False
        return self._write(data)
