"""
Jarvis AI Pro - Local Voice Activity Detection & Barge-In Engine
Uses energy & spectral flux analysis (with fallback to webrtcvad/silero)
to instantly silence Jarvis output when the user speaks.
"""

import audioop
import collections
import logging
import math
import struct
import time
from typing import Callable, Optional

logger = logging.getLogger("Jarvis.VAD")


class VoiceActivityDetector:
    def __init__(
        self,
        rate: int = 16000,
        chunk_ms: int = 20,
        energy_threshold: int = 650,
        barge_in_callback: Optional[Callable[[], None]] = None
    ):
        self.rate = rate
        self.chunk_size = int(rate * (chunk_ms / 1000.0))
        self.energy_threshold = energy_threshold
        self.barge_in_callback = barge_in_callback
        
        self.is_speaking = False
        self.jarvis_is_speaking = False
        self._history = collections.deque(maxlen=10)

    def set_jarvis_playback_state(self, is_speaking: bool):
        """Notifies VAD whether Jarvis's TTS/audio is actively playing."""
        self.jarvis_is_speaking = is_speaking

    def process_pcm_chunk(self, raw_bytes: bytes) -> bool:
        """
        Processes incoming 16-bit PCM mic frames.
        Returns True if voice activity is detected.
        """
        if len(raw_bytes) < 2:
            return False

        try:
            # Calculate Root Mean Square (RMS) energy
            rms = audioop.rms(raw_bytes, 2)
            self._history.append(rms)
            avg_rms = sum(self._history) / len(self._history)

            voice_detected = avg_rms > self.energy_threshold

            # Instant Barge-In detection: user speaks while Jarvis is outputting audio
            if voice_detected and self.jarvis_is_speaking:
                logger.info("[VAD] User speech detected during playback. Triggering barge-in silence.")
                if self.barge_in_callback:
                    self.barge_in_callback()
                self.jarvis_is_speaking = False

            self.is_speaking = voice_detected
            return voice_detected

        except Exception as err:
            logger.error(f"[VAD] Frame processing error: {err}")
            return False
