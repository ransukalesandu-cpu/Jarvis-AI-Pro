"""Shared-token theme for Qt surfaces: Fluent theme + colour, generated QSS, reduced motion."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from jarvis.core import failsoft
from jarvis.ui.theme.tokens import THEMES

THEME_DIR = Path(__file__).resolve().parent.parent / "theme"
_state = {"theme": "dark"}


def current_theme() -> str:
    return _state["theme"]


def token(name: str, theme: str | None = None) -> str:
    """Qt-ready value of a shared token (#rrggbb / rgba(r,g,b,a 0-255) / '12px' / '220ms')."""
    t = theme or _state["theme"]
    return THEMES.get(t, THEMES["dark"]).get(name) or THEMES["dark"][name]


def px(name: str) -> int:
    return int(round(float(token(name).removesuffix("px"))))


def ms(name: str) -> int:
    return 0 if reduced_motion() else int(round(float(token(name).removesuffix("ms"))))


def qss(theme: str | None = None) -> str:
    t = theme or _state["theme"]
    name = "jarvis.qss" if t == "dark" else f"jarvis.{t}.qss"
    return (THEME_DIR / name).read_text(encoding="utf-8")


def reduced_motion() -> bool:
    """Owner or OS asked for less motion: env, the web UI's saved setting, or Windows' animation switch."""
    env = os.environ.get("JARVIS_REDUCED_MOTION", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        from jarvis.core.user_data import user_data_dir
        prefs = json.loads((user_data_dir() / "config" / "web_workspaces.json").read_text(encoding="utf-8"))
        if isinstance(prefs.get("_prefs"), dict) and prefs["_prefs"].get("reducedMotion") is True:
            return True
    except FileNotFoundError:
        pass                      # no saved web setting is the normal case
    except Exception:  # noqa: BLE001
        failsoft.suppress("ui.components.theme:reduced_motion_prefs")
    if sys.platform == "win32":
        try:
            import ctypes
            on = ctypes.c_int(1)
            SPI_GETCLIENTAREAANIMATION = 0x1042
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(on), 0):
                return not bool(on.value)
        except Exception:  # noqa: BLE001
            failsoft.suppress("ui.components.theme:reduced_motion_win32")
            return False
    return False


def apply_theme(widget=None, theme: str = "dark") -> None:
    """Set the Fluent theme and accent from the tokens; give ``widget`` (a container) the token QSS.

    The QSS goes on the container, not the whole application, so the classic HUD's own styling is untouched.
    """
    from ._fluent import fluent

    _state["theme"] = theme if theme in THEMES else "dark"
    fluent.setTheme(fluent.Theme.LIGHT if _state["theme"] == "light" else fluent.Theme.DARK, lazy=True)
    fluent.setThemeColor(token("primary"), lazy=True)
    if widget is not None:
        widget.setStyleSheet(qss(_state["theme"]))
