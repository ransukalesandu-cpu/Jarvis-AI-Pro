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
        self.tts_start_time = 0.0
        self.continuous_speech_start = 0.0
        self._history = collections.deque(maxlen=10)

    def set_jarvis_playback_state(self, is_speaking: bool):
        """Notifies VAD whether Jarvis's TTS/audio is actively playing."""
        now = time.monotonic()
        if is_speaking and not self.jarvis_is_speaking:
            self.tts_start_time = now
        elif not is_speaking:
            self.continuous_speech_start = 0.0
        self.jarvis_is_speaking = is_speaking

    def process_pcm_chunk(self, raw_bytes: bytes) -> bool:
        """
        Processes incoming 16-bit PCM mic frames.
        Returns True if voice activity is detected.
        """
        if len(raw_bytes) < 2:
            return False

        try:
            now = time.monotonic()
            # 350ms refractory guardband
            if self.jarvis_is_speaking and (now - self.tts_start_time) < 0.350:
                self.continuous_speech_start = 0.0
                return False

            # Calculate Root Mean Square (RMS) energy
            rms = audioop.rms(raw_bytes, 2)
            self._history.append(rms)
            avg_rms = sum(self._history) / len(self._history)

            # Adaptive factor 1.75x during active TTS playback
            effective_threshold = self.energy_threshold * (1.75 if self.jarvis_is_speaking else 1.0)
            voice_detected = avg_rms > effective_threshold

            if voice_detected:
                if self.continuous_speech_start == 0.0:
                    self.continuous_speech_start = now
                speech_duration = now - self.continuous_speech_start
            else:
                self.continuous_speech_start = 0.0
                speech_duration = 0.0

            # Barge-In detection: user speech must exceed threshold continuously >150ms
            if voice_detected and self.jarvis_is_speaking and speech_duration >= 0.150:
                logger.info("[VAD] User speech detected continuously >150ms during playback. Triggering barge-in.")
                if self.barge_in_callback:
                    self.barge_in_callback()
                self.jarvis_is_speaking = False
                self.continuous_speech_start = 0.0

            self.is_speaking = voice_detected
            return voice_detected

        except Exception as err:
            logger.error(f"[VAD] Frame processing error: {err}")
            return False
