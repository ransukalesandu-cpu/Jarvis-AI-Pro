"""Desktop shell pieces: native window chrome in token colours, a frameless Fluent window, qasync helpers.

* ``apply_window_chrome(window)`` — Windows 11 caption/border/text colours from the tokens (DWM), dark
  title bar on Windows 10. Called for the main JARVIS window when the web UI is active. No-op elsewhere.
* ``JarvisShell`` — frameless window (PyQt-Frameless-Window) with a token-styled title bar and, on Windows,
  Mica (11) or Acrylic (10) behind it. ``JARVIS_WINDOW_EFFECT=mica|acrylic|off`` overrides the choice.
* ``run_async(coro, on_done)`` / ``qt_event_loop(app)`` — asyncio work from Qt widgets via qasync, so a
  component can await IO without blocking the UI thread.
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Awaitable, Callable

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qframelesswindow import FramelessWindow, StandardTitleBar

from jarvis.core import failsoft

from ._fluent import fluent
from .theme import apply_theme, current_theme, reduced_motion, token

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def _colorref(value: str) -> int:
    c = QColor(value)
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def apply_window_chrome(window: QWidget, theme: str | None = None) -> bool:
    """Colour the native title bar with the tokens. Returns True when Windows accepted it."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = wintypes.HWND(int(window.winId()))
        dwm = ctypes.windll.dwmapi
        t = theme or current_theme()

        def put(attr: int, value: int) -> bool:
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0

        ok = put(DWMWA_USE_IMMERSIVE_DARK_MODE, 0 if t == "light" else 1)
        # Windows 11 only; older builds return an error and keep the dark/light frame.
        put(DWMWA_CAPTION_COLOR, _colorref(token("bg", t)))
        put(DWMWA_TEXT_COLOR, _colorref(token("text", t)))
        put(DWMWA_BORDER_COLOR, _colorref(token("primary", t)))
        return ok
    except Exception:  # noqa: BLE001 - chrome colour is cosmetic
        failsoft.suppress("ui.components.shell:apply_window_chrome")
        return False


def window_effect() -> str:
    """'mica', 'acrylic' or 'off' for frameless Qt windows on this machine."""
    wanted = os.environ.get("JARVIS_WINDOW_EFFECT", "").strip().lower()
    if wanted in {"mica", "acrylic", "off"}:
        return wanted
    if sys.platform != "win32":
        return "off"
    return "mica" if sys.getwindowsversion().build >= 22000 else "acrylic"


class JarvisShell(FramelessWindow):
    """Frameless top-level window for Qt-only surfaces (gallery, tool windows), styled by the tokens."""

    def __init__(self, title: str, body: QWidget | None = None, *, theme: str = "dark", parent=None):
        super().__init__(parent)
        apply_theme(self, theme)
        bar = StandardTitleBar(self)
        bar.setTitle(title)
        self.setTitleBar(bar)
        self.setWindowTitle(title)
        self.setAccessibleName(title)
        self._lay = QVBoxLayout(self)
        top = self.titleBar.height()
        self._lay.setContentsMargins(0, top, 0, 0)
        if body is not None:
            self._lay.addWidget(body)
        self.effect = window_effect()
        if self.effect != "off":
            try:
                hwnd = int(self.winId())
                if self.effect == "mica":
                    self.windowEffect.setMicaEffect(hwnd, isDarkMode=theme != "light")
                else:
                    bg = QColor(token("bg", theme))
                    self.windowEffect.setAcrylicEffect(hwnd, f"{bg.red():02X}{bg.green():02X}{bg.blue():02X}CC")
            except Exception:  # noqa: BLE001 - effect is cosmetic; the token background stays
                failsoft.suppress("ui.components.shell:window_effect")
                self.effect = "off"
        if self.effect == "off":
            self.setStyleSheet(self.styleSheet() + f"\nJarvisShell {{ background: {token('bg', theme)}; }}")

    def setBody(self, body: QWidget) -> None:  # noqa: N802
        self._lay.addWidget(body)


# ── qasync ───────────────────────────────────────────────────────────────────
def qt_event_loop(app) -> asyncio.AbstractEventLoop:
    """Make asyncio run on the Qt event loop (for standalone Qt surfaces such as the gallery)."""
    import qasync

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    return loop


def _has_loop() -> bool:
    try:
        asyncio.get_event_loop_policy().get_event_loop()
        return True
    except RuntimeError:
        return False


def run_async(coro: Awaitable[Any], on_done: Callable[[Any, BaseException | None], None]) -> asyncio.Future | None:
    """Run ``coro`` on the running qasync loop; ``on_done(result, error)`` is called on the UI thread."""
    loop = asyncio.get_event_loop_policy().get_event_loop() if _has_loop() else None
    if loop is None or loop.is_closed():
        if asyncio.iscoroutine(coro):
            coro.close()          # never started: close it so Python does not warn about it
        on_done(None, RuntimeError("no Qt event loop installed (call qt_event_loop first)"))
        return None
    fut = asyncio.ensure_future(coro, loop=loop)

    def _done(f: asyncio.Future) -> None:
        if f.cancelled():
            on_done(None, asyncio.CancelledError())
        else:
            on_done(f.result() if f.exception() is None else None, f.exception())

    fut.add_done_callback(_done)
    return fut


__all__ = ["apply_window_chrome", "window_effect", "JarvisShell", "qt_event_loop", "run_async",
           "reduced_motion", "fluent"]
