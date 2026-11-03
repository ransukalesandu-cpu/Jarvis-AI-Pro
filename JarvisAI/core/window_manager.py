"""The HUD's window manager: where glass windows go, and which ones sleep.

Windows live in two docks, left and right of the stage (core/ui_layout.py), so
the hologram in the middle is never covered. In each dock the open windows
tile top to bottom without overlapping; when a dock runs out of room the
window used longest ago is minimised to make space. On a resize everything
reflows from the new layout.

Web-backed windows (music, video, news) are expensive, so only the few most
recently used stay live; the rest are listed by :meth:`frozen` and the Qt
layer freezes their pages (QWebEnginePage lifecycle) until they are used
again.

Workspaces are named snapshots of which windows are open, on which side and
in which order, saved as JSON.

No Qt here; the widgets in ui/glass_window.py follow these numbers.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.ui_layout import Layout, Rect

SIDES = ("left", "right")

# kind -> title, default side, web-backed, minimum height (design px), weight
KINDS: dict[str, dict] = {
    "timer": {"title": "TIMER", "side": "right", "web": False, "min_h": 150, "weight": 0.7},
    "youtube_music": {"title": "YOUTUBE MUSIC", "side": "left", "web": True, "min_h": 260, "weight": 1.3},
    "music": {"title": "MUSIC", "side": "left", "web": True, "min_h": 220, "weight": 1.0},
    "video": {"title": "VIDEO", "side": "left", "web": True, "min_h": 240, "weight": 1.4},
    "image": {"title": "IMAGE", "side": "right", "web": False, "min_h": 200, "weight": 1.0},
    "news": {"title": "NEWS", "side": "right", "web": False, "min_h": 220, "weight": 1.2},
    "downloads": {"title": "DOWNLOADS", "side": "right", "web": False, "min_h": 180, "weight": 0.9},
}


@dataclass
class Win:
    id: str
    kind: str
    side: str
    order: int = 0
    minimized: bool = False
    last_used: int = 0
    payload: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        return KINDS[self.kind]["title"]

    @property
    def web(self) -> bool:
        return bool(KINDS[self.kind]["web"])


class WindowManager:
    def __init__(self, layout: Layout, *, max_live_web: int = 2):
        self.layout = layout
        self.max_live_web = max(0, int(max_live_web))
        self._wins: dict[str, Win] = {}
        self._clock = itertools.count(1)
        self._ids = itertools.count(1)

    # ── queries ─────────────────────────────────────────────────────────────
    def windows(self) -> list[Win]:
        return sorted(self._wins.values(), key=lambda w: (SIDES.index(w.side), w.order))

    def get(self, wid: str) -> Win | None:
        return self._wins.get(wid)

    def find(self, kind: str) -> Win | None:
        for w in self._wins.values():
            if w.kind == kind:
                return w
        return None

    def in_dock(self, side: str) -> list[Win]:
        return sorted((w for w in self._wins.values() if w.side == side), key=lambda w: w.order)

    # ── changes ─────────────────────────────────────────────────────────────
    def open(self, kind: str, side: str | None = None, payload: dict | None = None) -> Win:
        """Open a window of ``kind`` (or bring back the open one), on ``side``
        if given, else its usual side, else the emptier dock."""
        if kind not in KINDS:
            raise KeyError(f"unknown window kind: {kind}")
        if side is not None and side not in SIDES:
            raise ValueError(f"side must be left or right, not {side!r}")
        w = self.find(kind)
        if w is None:
            side = side or self._pick_side(kind)
            w = Win(id=f"{kind}-{next(self._ids)}", kind=kind, side=side,
                    order=len(self.in_dock(side)), payload=dict(payload or {}))
            self._wins[w.id] = w
        else:
            if payload:
                w.payload.update(payload)
            if side and side != w.side:
                self.move(w.id, side)
        w.minimized = False
        self.focus(w.id)
        self._fit(w.side)
        return w

    def _pick_side(self, kind: str) -> str:
        pref = KINDS[kind]["side"]
        other = "right" if pref == "left" else "left"
        if len(self.in_dock(pref)) > len(self.in_dock(other)) + 1:
            return other
        return pref

    def close(self, wid: str) -> bool:
        w = self._wins.pop(wid, None)
        if w is None:
            return False
        self._renumber(w.side)
        return True

    def move(self, wid: str, side: str, index: int | None = None) -> None:
        w = self._wins[wid]
        if side not in SIDES:
            raise ValueError(side)
        old = w.side
        w.side = side
        dock = [x for x in self.in_dock(side) if x.id != wid]
        index = len(dock) if index is None else max(0, min(len(dock), index))
        dock.insert(index, w)
        for i, x in enumerate(dock):
            x.order = i
        if old != side:
            self._renumber(old)
        self.focus(wid)
        self._fit(side)

    def drop(self, wid: str, x: float, y: float) -> None:
        """A window dragged and let go at (x, y): the nearer dock, in the slot
        under the pointer."""
        side = "left" if x < self.layout.stage.center[0] else "right"
        geo = self.geometry()
        index = sum(1 for w in self.in_dock(side)
                    if w.id != wid and w.id in geo and geo[w.id].center[1] < y)
        self.move(wid, side, index)

    def focus(self, wid: str) -> None:
        w = self._wins.get(wid)
        if w is not None:
            w.last_used = next(self._clock)

    def minimize(self, wid: str, on: bool = True) -> None:
        w = self._wins[wid]
        w.minimized = on
        if not on:
            self.focus(wid)
            self._fit(w.side)

    def set_layout(self, layout: Layout) -> None:
        """Reflow everything for a new window size."""
        self.layout = layout
        for side in SIDES:
            self._fit(side)

    def tile(self) -> None:
        """Restore every window and spread them evenly over both docks."""
        wins = sorted(self._wins.values(), key=lambda w: -w.last_used)
        for i, w in enumerate(wins):
            w.side = SIDES[i % 2]
            w.minimized = False
        for side in SIDES:
            self._renumber(side)
            self._fit(side)

    def _renumber(self, side: str) -> None:
        for i, w in enumerate(self.in_dock(side)):
            w.order = i

    # ── tiling ──────────────────────────────────────────────────────────────
    def _min_h(self, w: Win) -> float:
        return KINDS[w.kind]["min_h"] * self.layout.scale

    def _fit(self, side: str) -> None:
        """Minimise the least recently used windows until the dock fits."""
        dock = self.layout.docks[side]
        gap = self.layout.gap
        while True:
            shown = [w for w in self.in_dock(side) if not w.minimized]
            need = sum(self._min_h(w) for w in shown) + gap * max(0, len(shown) - 1)
            if need <= dock.h or len(shown) <= 1:
                return
            min(shown, key=lambda w: w.last_used).minimized = True

    def geometry(self) -> dict[str, Rect]:
        """Rectangles for every visible window: tiled, never overlapping, never
        on the stage. Minimised windows are absent."""
        out: dict[str, Rect] = {}
        gap = self.layout.gap
        for side in SIDES:
            dock = self.layout.docks[side]
            shown = [w for w in self.in_dock(side) if not w.minimized]
            if not shown:
                continue
            free = dock.h - gap * (len(shown) - 1)
            mins = [self._min_h(w) for w in shown]
            weights = [KINDS[w.kind]["weight"] for w in shown]
            spare = max(0.0, free - sum(mins))
            total_w = sum(weights) or 1.0
            y = dock.y
            for w, m, wt in zip(shown, mins, weights):
                h = min(free, m + spare * wt / total_w)
                out[w.id] = Rect(dock.x, y, dock.w, h)
                y += h + gap
        return out

    def frozen(self) -> set[str]:
        """Web windows whose pages should sleep: minimised ones, and all but
        the ``max_live_web`` most recently used."""
        web = sorted((w for w in self._wins.values() if w.web), key=lambda w: -w.last_used)
        live = [w for w in web if not w.minimized][: self.max_live_web]
        return {w.id for w in web} - {w.id for w in live}

    # ── workspaces ──────────────────────────────────────────────────────────
    def snapshot(self) -> list[dict]:
        return [{"kind": w.kind, "side": w.side, "order": w.order, "minimized": w.minimized,
                 "payload": w.payload} for w in self.windows()]

    def restore(self, snap: list[dict]) -> None:
        """Replace the open windows with a snapshot (unknown kinds skipped)."""
        self._wins.clear()
        for item in sorted(snap, key=lambda d: (str(d.get("side")), int(d.get("order", 0)))):
            kind, side = item.get("kind"), item.get("side")
            if kind not in KINDS or side not in SIDES or self.find(kind):
                continue
            w = Win(id=f"{kind}-{next(self._ids)}", kind=kind, side=side,
                    order=len(self.in_dock(side)), minimized=bool(item.get("minimized")),
                    payload=dict(item.get("payload") or {}), last_used=next(self._clock))
            self._wins[w.id] = w
        for side in SIDES:
            self._fit(side)


class Workspaces:
    """Named window snapshots in one JSON file."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def names(self) -> list[str]:
        return sorted(self._read())

    def save(self, name: str, wm: WindowManager) -> None:
        name = str(name).strip().lower() or "default"
        data = self._read()
        data[name] = wm.snapshot()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def load(self, name: str, wm: WindowManager) -> bool:
        snap = self._read().get(str(name).strip().lower())
        if snap is None:
            return False
        wm.restore(snap)
        return True

    def delete(self, name: str) -> bool:
        data = self._read()
        if data.pop(str(name).strip().lower(), None) is None:
            return False
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True


def as_dict(w: Win) -> dict:
    return asdict(w)
