# config/__init__.py
"""Legacy import path for JARVIS's OS helpers and API-key loader.

The real implementation lives in ``core/host_env.py``. It moved there because
this package's generic ``config`` name collides with OpenCV's bundled
``cv2/config.py`` loader, which ships on ``sys.path`` while ``cv2`` imports.
Keeping the functions here as re-exports means older code (and user
extensions) that does ``from config import is_windows`` keeps working, while
new code should import from ``core.host_env`` directly.

This directory also holds the runtime data files the app reads by path
(``api_keys.json``, ``holo_ui.json``, ``jarvis.ico``), so it is not going away.
"""

from core.host_env import (  # noqa: F401  (re-exported public API)
    CONFIG_PATH as _CONFIG_PATH,
    get_config,
    get_os,
    is_linux,
    is_mac,
    is_windows,
)

__all__ = [
    "get_config",
    "get_os",
    "is_linux",
    "is_mac",
    "is_windows",
]
