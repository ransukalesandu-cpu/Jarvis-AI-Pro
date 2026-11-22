"""Shapes the web UI's neural brain can form on request (form_shape tool -> ui_state -> page).

The closed set and the text rules are shared with the web contract (webui/contract.py) and
frontend/src/hologram/brain/shapes.ts. Text is short and plain on purpose: it is drawn as points.
"""
from __future__ import annotations

import itertools
import re

SHAPES = ("brain", "sphere", "cube", "torus", "helix", "heart", "globe", "star", "text")
TEXT_MAX = 16
_TEXT_OK = re.compile(r"^[A-Za-z0-9 .!?&+\-]*$")
_ALIASES = {
    "dna": "helix", "double helix": "helix", "ball": "sphere", "orb": "sphere", "box": "cube",
    "ring": "torus", "donut": "torus", "doughnut": "torus", "earth": "globe", "world": "globe",
    "love": "heart", "back": "brain", "normal": "brain", "reset": "brain", "word": "text", "name": "text",
}
_seq = itertools.count(1)


def valid_text(text: str) -> bool:
    return isinstance(text, str) and len(text) <= TEXT_MAX and bool(_TEXT_OK.match(text))


def normalise(shape: str, text: str = "") -> tuple[str, str] | None:
    """Maps what the owner said to (shape, text), or None when it cannot be drawn."""
    s = str(shape or "").strip().lower()
    s = _ALIASES.get(s, s)
    t = " ".join(str(text or "").split())
    if s not in SHAPES:
        return None
    if s != "text":
        return s, ""
    t = t.upper()
    return (s, t) if t and valid_text(t) else None


def request(shape: str, text: str = "") -> tuple[str, str] | None:
    """Ask the page to form a shape. Returns what was sent, or None if it is not drawable."""
    from jarvis.core import ui_state
    norm = normalise(shape, text)
    if norm is None:
        return None
    # A sequence number makes asking for the same shape twice re-trigger it (the bus drops repeats).
    ui_state.bus().set(ui_state.BRAIN_SHAPE, (norm[0], norm[1], next(_seq)))
    return norm
