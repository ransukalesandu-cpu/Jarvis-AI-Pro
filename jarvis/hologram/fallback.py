"""Inert stand-in used when QtWebEngine is unavailable (or JARVIS_HOLOGRAM=off).

It keeps the HUD running and records what it was told, so the rest of the UI (and its tests)
can rely on the same API as the real host without spawning a browser process.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel

from jarvis.hologram import protocol


class NullHologram(QLabel):
    ready = pyqtSignal(dict)
    failed = pyqtSignal(str)
    quality_changed = pyqtSignal(str)
    is_ready = False
    is_failed = True

    def __init__(self, parent=None, reason: str = "Hologram unavailable"):
        super().__init__(reason, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("color:#00e5ff;background:transparent;font:11pt 'Courier New';")
        self.state = "idle"
        self.profile = "jarvis"
        self.reduced_motion = False
        self.budget: tuple[int, float, float] | None = None
        self.glow: float | None = None
        self.effects = True
        self.voice_reactive = True
        self.input_level = 0.0
        self.output_level = 0.0
        self.output_ended = 0
        self.shut_down = False

    def set_state(self, name: str) -> None:
        self.state = protocol.normalize_state(name)

    def set_profile(self, profile_id: str) -> None:
        self.profile = profile_id if profile_id in protocol.PROFILES else "jarvis"

    def set_audio_energy(self, level: float) -> None:
        self.input_level = max(0.0, min(1.0, float(level)))

    def set_output_level(self, level: float, openness=None, width=None) -> None:
        self.output_level = max(0.0, min(1.0, float(level)))

    def end_output(self) -> None:
        self.output_ended += 1
        self.output_level = 0.0

    def set_performance_budget(self, frame_interval_ms: int, particle_scale: float, glow_scale: float) -> None:
        self.budget = (int(frame_interval_ms), float(particle_scale), float(glow_scale))

    def set_reduced_motion(self, enabled: bool) -> None:
        self.reduced_motion = bool(enabled)

    def set_glow_intensity(self, value: float) -> None:
        self.glow = float(value)

    def set_effects_enabled(self, enabled: bool) -> None:
        self.effects = bool(enabled)

    def set_voice_reactive(self, enabled: bool) -> None:
        self.voice_reactive = bool(enabled)

    def shutdown(self) -> None:
        self.shut_down = True

    def set_viseme(self, *_a) -> None:
        return

    def set_animation_speed(self, *_a) -> None:
        return

    def set_quality(self, *_a) -> None:
        return

    def set_visible_hint(self, *_a) -> None:
        return
