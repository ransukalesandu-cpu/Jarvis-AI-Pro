"""Lazy access to the two "immersive" UI modules that pull in Qt WebEngine.

Qt WebEngine is the heaviest optional dependency in the project: importing it
maps Chromium's shared libraries into the process, and the first page/profile
can start a helper process. Its only consumers are the legacy UI's immersive
"neural hand" overlay, the Earth globe panel and the document/media workspace.

The shipped Hologram HUD (`ui/hud_main.py`) never constructs any of those, yet
`import ui` used to import all of them - so every launch paid for a feature most
sessions never open.

This module defers those imports and remembers the answer, which keeps the
existing "feature unavailable" branches honest:

* ``import ui`` and ``import ui.hud_main`` no longer touch Chromium;
* the first construction of a WebEngine-backed panel imports it, exactly as
  before (so behaviour on a machine with WebEngine is unchanged);
* on a machine without WebEngine ``available()`` stays ``False`` and the
  callers' existing fallbacks run.

Nothing here creates a page, a profile or a process by itself.
"""

from __future__ import annotations

import threading
from typing import Any

__all__ = ["available", "classes", "ensure", "load", "reset_for_tests"]

_CLASS_NAMES = (
    "QWebEnginePage",
    "QWebEngineProfile",
    "QWebEngineSettings",
    "QWebEngineUrlRequestInterceptor",
    "QWebEngineView",
)

_lock = threading.Lock()
_tried = False
_classes: dict[str, Any] = {}


def ensure() -> bool:
    """Import Qt WebEngine once. Returns True when it is usable."""
    global _tried
    with _lock:
        if _tried:
            return bool(_classes)
        _tried = True
        try:
            from PyQt6.QtWebEngineCore import (  # noqa: F401 - availability probe
                QWebEnginePage,
                QWebEngineProfile,
                QWebEngineSettings,
                QWebEngineUrlRequestInterceptor,
            )
            from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

            _classes.update(
                {
                    "QWebEnginePage": QWebEnginePage,
                    "QWebEngineProfile": QWebEngineProfile,
                    "QWebEngineSettings": QWebEngineSettings,
                    "QWebEngineUrlRequestInterceptor": QWebEngineUrlRequestInterceptor,
                    "QWebEngineView": QWebEngineView,
                }
            )
        except Exception:
            # Minimal installs, or a platform where Chromium cannot load: the
            # feature simply stays unavailable. Import failures here are
            # expected and must never stop the HUD from starting.
            _classes.clear()
        return bool(_classes)


def available() -> bool:
    """True when Qt WebEngine imported successfully."""
    return ensure()


def classes() -> dict[str, Any]:
    """The imported Qt classes, or ``{}`` when WebEngine is unavailable."""
    ensure()
    return dict(_classes)


def load() -> dict[str, Any]:
    """Alias for :func:`classes`, kept for readability at call sites."""
    return classes()


def reset_for_tests() -> None:
    """Forget what was learned (tests only; never called by the app)."""
    global _tried
    with _lock:
        _tried = False
        _classes.clear()
