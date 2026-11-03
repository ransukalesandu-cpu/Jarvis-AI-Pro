"""Screen layout for the HUD, from 1366x768 to 4K.

Splits the window into a header, the persistent command bar at the bottom,
two slim menu rails, a central *stage* that is kept clear for the hologram
(about 40% of the width), and two docks either side of it where windows tile.
Everything scales with the window, from one design size (1920x1080), so the
proportions read the same on a laptop and on a 4K monitor.

No Qt: rectangles are plain ``Rect`` tuples, so the window manager and the
tests share the exact numbers the widgets use.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

DESIGN_W, DESIGN_H = 1920, 1080
MIN_SCALE, MAX_SCALE = 0.68, 2.2
SAFE_FRACTION = 0.40          # share of the width kept clear for the hologram


class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    def intersects(self, other: "Rect") -> bool:
        return (self.x < other.right and other.x < self.right
                and self.y < other.bottom and other.y < self.bottom)

    def overlap_area(self, other: "Rect") -> float:
        w = min(self.right, other.right) - max(self.x, other.x)
        h = min(self.bottom, other.bottom) - max(self.y, other.y)
        return max(0.0, w) * max(0.0, h)

    def contains(self, other: "Rect") -> bool:
        return (other.x >= self.x - 0.5 and other.y >= self.y - 0.5
                and other.right <= self.right + 0.5 and other.bottom <= self.bottom + 0.5)

    def rounded(self) -> tuple[int, int, int, int]:
        return (round(self.x), round(self.y), round(self.w), round(self.h))


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    scale: float
    header: Rect
    footer: Rect            # the persistent command bar
    left_rail: Rect
    right_rail: Rect
    stage: Rect             # kept clear for the hologram
    dock_left: Rect
    dock_right: Rect
    island: Rect            # Dynamic Island, top centre
    gap: float

    @property
    def docks(self) -> dict[str, Rect]:
        return {"left": self.dock_left, "right": self.dock_right}

    @property
    def compact(self) -> bool:
        """Too narrow for both docks beside the stage (they then overlay it)."""
        return self.dock_left.w < 240 * self.scale


def scale_for(width: int, height: int) -> float:
    s = min(width / DESIGN_W, height / DESIGN_H)
    return max(MIN_SCALE, min(MAX_SCALE, s))


def compute_layout(width: int, height: int, *, safe_fraction: float = SAFE_FRACTION,
                   left_open: bool = False, right_open: bool = False) -> Layout:
    """The HUD's regions for a window of ``width`` x ``height`` pixels.

    Open menus widen their rail; the docks give way, never the stage.
    """
    w, h = max(320, int(width)), max(240, int(height))
    s = scale_for(w, h)
    gap = round(12 * s)
    header_h = round(56 * s)
    footer_h = round(64 * s)
    rail_closed, rail_open = round(56 * s), round(232 * s)
    lr = rail_open if left_open else rail_closed
    rr = rail_open if right_open else rail_closed

    body_y = header_h
    body_h = h - header_h - footer_h
    header = Rect(0, 0, w, header_h)
    footer = Rect(0, h - footer_h, w, footer_h)
    left_rail = Rect(0, body_y, lr, body_h)
    right_rail = Rect(w - rr, body_y, rr, body_h)

    stage_w = max(min(w * max(0.2, min(0.8, safe_fraction)), w - 2 * rail_closed), 320 * s)
    stage = Rect((w - stage_w) / 2, body_y, stage_w, body_h)

    def dock(x0: float, x1: float) -> Rect:
        x0, x1 = x0 + gap, x1 - gap
        return Rect(x0, body_y + gap, max(0.0, x1 - x0), max(0.0, body_h - 2 * gap))

    dock_left = dock(left_rail.right, stage.x)
    dock_right = dock(stage.right, right_rail.x)
    iw = min(round(420 * s), w * 0.4)
    island = Rect((w - iw) / 2, round(8 * s), iw, round(36 * s))
    return Layout(w, h, s, header, footer, left_rail, right_rail, stage,
                  dock_left, dock_right, island, gap)
