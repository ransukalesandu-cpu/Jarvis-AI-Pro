"""The per-user data folder for state that must stay out of the checkout.

Windows: %LOCALAPPDATA%\\JarvisAI
macOS:   ~/Library/Application Support/JarvisAI
Linux:   $XDG_DATA_HOME/jarvisai (default ~/.local/share/jarvisai)

``JARVIS_DATA_DIR`` overrides the location (tests use it to stay isolated).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    override = os.environ.get("JARVIS_DATA_DIR", "").strip()
    if override:
        root = Path(override)
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "jarvis"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "jarvis"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "jarvisai"
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_data_file(name: str) -> Path:
    return user_data_dir() / name
