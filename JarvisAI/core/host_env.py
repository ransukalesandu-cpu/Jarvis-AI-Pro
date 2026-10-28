"""Host environment helpers: OS detection and API-key config loading.

Why this module exists
----------------------
These five one-line helpers used to live only in the top-level ``config``
package (``config/__init__.py``). That package name is dangerously generic:
``opencv-python`` ships its own ``cv2/config.py`` loader and temporarily puts
the ``cv2`` directory on ``sys.path`` while it imports. If anything imports
``cv2`` before JARVIS imports ``config``, Python can resolve ``config`` to
OpenCV's loader instead, and the app dies with a confusing
``NameError: name 'LOADER_DIR' is not defined``.

``core.host_env`` is an unambiguous name that no third-party wheel claims, so
imports of the OS helpers and of the API-key file can never be hijacked. The
old ``config`` package still works and simply re-exports these functions for
backwards compatibility.

This module must stay dependency-free (standard library only) so it can be
imported by any action without dragging in Qt, audio, or network libraries.
"""

from __future__ import annotations

import json
import platform
from pathlib import Path

# JarvisAI/config/api_keys.json — the file the setup flow writes.
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"

_OS_NAMES = {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}


def _platform_os() -> str:
    """Detect the host OS that JARVIS is actually running on."""
    return _OS_NAMES.get(platform.system(), "linux")


def get_config() -> dict:
    """Return the saved config, or an empty dict when it is missing/broken."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def get_os() -> str:
    """Return the current host OS; saved config must not override reality."""
    return _platform_os()


def is_windows() -> bool:
    return get_os() == "windows"


def is_mac() -> bool:
    return get_os() == "mac"


def is_linux() -> bool:
    return get_os() == "linux"
