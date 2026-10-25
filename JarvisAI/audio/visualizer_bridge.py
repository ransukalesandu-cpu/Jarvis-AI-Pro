"""
Audio Graph Energy Tapping Bridge for Jarvis AI Pro HUD Visualizer.

Taps incoming microphone PCM data and outgoing speech/TTS audio buffers,
calculates non-blocking RMS energy normalized to [0.0, 1.0], applies lerp smoothing,
and emits Qt signals across threads safely.
"""

from __future__ import annotations

import math
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

try:
    import numpy as np
except ImportError:
    np = None


class VisualizerBridge(QObject):
    """
    Thread-safe bridge that processes raw audio buffers (mic / TTS)
    and state transitions, emitting signals for the UI components.
    """

    # Signals for UI binding
    sig_audio_energy = pyqtSignal(float)
    sig_auth_state_changed = pyqtSignal(str)
    sig_state_changed = pyqtSignal(str)
    sig_telemetry_updated = pyqtSignal(dict)

    def __init__(self, parent: Optional[QObject] = None, lerp_factor: float = 0.25):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._lerp_factor = max(0.01, min(0.99, float(lerp_factor)))
        self._current_energy = 0.0
        self._target_energy = 0.0
        self._current_state = "IDLE"

    @property
    def current_energy(self) -> float:
        with self._lock:
            return self._current_energy

    @property
    def current_state(self) -> str:
        with self._lock:
            return self._current_state

    def calculate_rms(self, audio_data: bytes | list | np.ndarray) -> float:
        """
        Calculate normalized RMS (Root Mean Square) energy from audio buffer (0.0 to 1.0).
        Supports bytes (16-bit PCM), lists, or numpy arrays.
        """
        if not audio_data:
            return 0.0

        try:
            if np is not None and isinstance(audio_data, np.ndarray):
                if audio_data.size == 0:
                    return 0.0
                samples = audio_data.astype(np.float32)
                if np.max(np.abs(samples)) > 1.0:
                    samples = samples / 32768.0
                rms = np.sqrt(np.mean(np.square(samples)))
                return float(np.clip(rms * 2.5, 0.0, 1.0))

            if isinstance(audio_data, (bytes, bytearray, memoryview)):
                raw_bytes = bytes(audio_data)
                count = len(raw_bytes) // 2
                if count == 0:
                    return 0.0
                sum_sq = 0.0
                # Process 16-bit signed PCM samples
                for i in range(0, count * 2, 2):
                    sample = int.from_bytes(raw_bytes[i:i + 2], byteorder="little", signed=True)
                    norm_sample = sample / 32768.0
                    sum_sq += norm_sample * norm_sample
                rms = math.sqrt(sum_sq / count)
                return min(1.0, max(0.0, rms * 2.5))

            if isinstance(audio_data, (list, tuple)):
                if not audio_data:
                    return 0.0
                sum_sq = 0.0
                for item in audio_data:
                    val = float(item)
                    if abs(val) > 1.0:
                        val = val / 32768.0
                    sum_sq += val * val
                rms = math.sqrt(sum_sq / len(audio_data))
                return min(1.0, max(0.0, rms * 2.5))

        except Exception:
            return 0.0

        return 0.0

    def tap_audio_buffer(self, audio_data: bytes | list | np.ndarray) -> float:
        """
        Thread-safe entry point to tap raw audio buffers (mic input or speaker output).
        Calculates RMS, applies lerp smoothing, and emits sig_audio_energy.
        """
        rms = self.calculate_rms(audio_data)
        return self.push_audio_energy(rms)

    def push_audio_energy(self, level: float) -> float:
        """
        Thread-safe entry point to push normalized energy level [0.0, 1.0].
        Applies linear interpolation (lerp) smoothing and emits sig_audio_energy.
        """
        clamped = max(0.0, min(1.0, float(level)))
        with self._lock:
            self._target_energy = clamped
            # Lerp update
            self._current_energy += (self._target_energy - self._current_energy) * self._lerp_factor
            val = round(self._current_energy, 4)

        self.sig_audio_energy.emit(val)
        return val

    def update_auth_state(self, auth_state: str) -> None:
        """Thread-safe update of AuthState."""
        self.sig_auth_state_changed.emit(str(auth_state))

    def update_state(self, state: str) -> None:
        """Thread-safe update of visualizer state (IDLE, LISTENING, THINKING, SPEAKING, PRIVACY_LOCK)."""
        with self._lock:
            self._current_state = str(state)
        self.sig_state_changed.emit(str(state))


_global_bridge: Optional[VisualizerBridge] = None


def get_visualizer_bridge() -> VisualizerBridge:
    """Singleton getter for global visualizer bridge."""
    global _global_bridge
    if _global_bridge is None:
        _global_bridge = VisualizerBridge()
    return _global_bridge
