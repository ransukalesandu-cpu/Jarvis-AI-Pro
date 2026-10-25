"""Small QSettings-backed preferences for the optional Bihansa mode.

This module deliberately does not change voice providers or the existing JARVIS
mode. Provider-specific female voice selection belongs in a later integration
step after the current Gemini Live session configuration has been inspected.
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings


class BihansaModeSettings:
    """Persist Bihansa appearance preferences without touching other settings."""

    GROUP = "bihansa"

    def __init__(self, settings: QSettings | None = None):
        self._settings = settings or QSettings("JarvisAI", "JarvisAIPro")

    def _get(self, key: str, default):
        self._settings.beginGroup(self.GROUP)
        try:
            return self._settings.value(key, default)
        finally:
            self._settings.endGroup()

    def _set(self, key: str, value) -> None:
        self._settings.beginGroup(self.GROUP)
        try:
            self._settings.setValue(key, value)
            self._settings.sync()
        finally:
            self._settings.endGroup()

    @property
    def assistant_mode(self) -> str:
        value = str(self._get("assistant_mode", "jarvis")).strip().lower()
        return value if value in {"jarvis", "bihansa"} else "jarvis"

    @assistant_mode.setter
    def assistant_mode(self, value: str) -> None:
        normalized = str(value or "jarvis").strip().lower()
        if normalized not in {"jarvis", "bihansa"}:
            normalized = "jarvis"
        self._set("assistant_mode", normalized)

    @property
    def reduced_motion(self) -> bool:
        value = self._get("reduced_motion", False)
        return value if isinstance(value, bool) else str(value).lower() in {"1", "true", "yes", "on"}

    @reduced_motion.setter
    def reduced_motion(self, value: bool) -> None:
        self._set("reduced_motion", bool(value))

    @property
    def glow_intensity(self) -> float:
        try:
            return max(0.0, min(1.5, float(self._get("glow_intensity", 1.0))))
        except (TypeError, ValueError):
            return 1.0

    @glow_intensity.setter
    def glow_intensity(self, value: float) -> None:
        try:
            normalized = max(0.0, min(1.5, float(value)))
        except (TypeError, ValueError):
            normalized = 1.0
        self._set("glow_intensity", normalized)

    @property
    def animation_speed(self) -> float:
        try:
            return max(0.0, min(2.0, float(self._get("animation_speed", 1.0))))
        except (TypeError, ValueError):
            return 1.0

    @animation_speed.setter
    def animation_speed(self, value: float) -> None:
        try:
            normalized = max(0.0, min(2.0, float(value)))
        except (TypeError, ValueError):
            normalized = 1.0
        self._set("animation_speed", normalized)

    def restore_bihansa_defaults(self) -> None:
        """Reset only Bihansa preferences; preserve unrelated app settings."""
        self._settings.beginGroup(self.GROUP)
        try:
            self._settings.remove("")
            self._settings.setValue("assistant_mode", "jarvis")
            self._settings.setValue("reduced_motion", False)
            self._settings.setValue("glow_intensity", 1.0)
            self._settings.setValue("animation_speed", 1.0)
            self._settings.sync()
        finally:
            self._settings.endGroup()
