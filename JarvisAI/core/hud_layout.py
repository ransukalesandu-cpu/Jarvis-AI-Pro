"""Sizes for the HUD's floating chrome, as a function of the window size.

The left icon rail was a hard ``44 px`` and the right dropdown a hard ``300 px``.
On a small window that pair steals 344 px of a 800 px screen and pushes the
hologram into a sliver; on a 4K screen the dropdown stays comically narrow while
the rail floats in space.

These are the rules that decide both, kept Qt-free so they can be asserted
without a display. The HUD only *applies* the numbers — it does not decide them.
"""

from __future__ import annotations

__all__ = [
    "RAIL_WIDE",
    "RAIL_COMPACT",
    "RAIL_NARROW",
    "DROPDOWN_WIDE",
    "DROPDOWN_MIN",
    "rail_width",
    "rail_button_size",
    "dropdown_width",
    "dropdown_height",
    "dropdown_x",
]

RAIL_WIDE = 44
RAIL_COMPACT = 38
RAIL_NARROW = 32
#: Below this width the rail would eat more than ~5 % of the screen.
RAIL_COMPACT_BELOW = 1000
RAIL_NARROW_BELOW = 720

DROPDOWN_WIDE = 300
DROPDOWN_MIN = 208
#: The dropdown may never take more than this fraction of the window.
DROPDOWN_MAX_FRACTION = 0.34
DROPDOWN_MAX_HEIGHT = 650
DROPDOWN_MIN_HEIGHT = 260
#: Gap kept between the dropdown and the window edge, and at the top.
DROPDOWN_EDGE = 12
DROPDOWN_TOP = 50


def rail_width(window_width: int) -> int:
    """Icon rail width: full size when there is room, slimmer when there is not."""
    try:
        width = int(window_width)
    except (TypeError, ValueError):
        return RAIL_WIDE
    if width < RAIL_NARROW_BELOW:
        return RAIL_NARROW
    if width < RAIL_COMPACT_BELOW:
        return RAIL_COMPACT
    return RAIL_WIDE


def rail_button_size(window_width: int) -> int:
    """Square rail buttons, inset from the rail so they never clip it."""
    return max(24, rail_width(window_width) - 4)


def dropdown_width(window_width: int, preferred: int = DROPDOWN_WIDE) -> int:
    """Dropdown width: the preferred width, capped so the hologram keeps room.

    It never drops below :data:`DROPDOWN_MIN` — a panel narrower than that
    cannot show its checkboxes and labels, so horizontal scrolling would be
    worse than a slightly thicker overlay.
    """
    try:
        width = max(0, int(window_width))
    except (TypeError, ValueError):
        return int(preferred)
    cap = max(DROPDOWN_MIN, int(width * DROPDOWN_MAX_FRACTION))
    return max(DROPDOWN_MIN, min(int(preferred), cap))


def dropdown_height(window_height: int, preferred: int = DROPDOWN_MAX_HEIGHT) -> int:
    """Dropdown height: clipped to the window so its last row stays reachable."""
    try:
        height = max(0, int(window_height))
    except (TypeError, ValueError):
        return int(preferred)
    room = height - DROPDOWN_TOP - DROPDOWN_EDGE
    return max(DROPDOWN_MIN_HEIGHT, min(int(preferred), room))


def dropdown_x(window_width: int, panel_width: int, edge: int = DROPDOWN_EDGE) -> int:
    """Left edge of the dropdown; never negative on a tiny window."""
    try:
        width = int(window_width)
        panel = int(panel_width)
    except (TypeError, ValueError):
        return 0
    return max(8, width - panel - int(edge))
