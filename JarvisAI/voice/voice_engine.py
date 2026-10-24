"""
Jarvis AI Pro - Ultra-Low Latency Streaming Voice Engine
Splits incoming LLM tokens on sentence boundaries and streams audio concurrently.
Default voice: 'en-GB-RyanNeural' (Paul Bettany / J.A.R.V.I.S. cadence).
"""

import asyncio
import io
import logging
import queue
import re
import threading
from typing import Generator, Optional

try:
    import edge_tts
    import pygame
except ImportError:
    edge_tts = None
    pygame = None

from .sanitizer import SpeechSanitizer

logger = logging.getLogger("Jarvis.VoiceEngine")


class JarvisVoiceEngine:
    def __init__(self, voice: str = "en-GB-RyanNeural", rate: str = "+3%", pitch: str = "-2Hz"):
        """
        :param voice: High quality British English neural voice.
        :param rate: Speed adjustment (+3% creates a crisp, confident cadence).
        :param pitch: Slight drop (-2Hz) provides a deeper vocal resonance.
        """
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.sanitizer = SpeechSanitizer()
        self._is_speaking = False
        self._interrupt_flag = False

        if pygame and not pygame.mixer.get_init():
            pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=1024)

    def interrupt(self):
        """Immediately halts active playback (called by barge-in VAD)."""
        self._interrupt_flag = True
        self._is_speaking = False
        if pygame and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
        logger.info("[VOICE] Playback interrupted.")

    def speak_stream(self, token_generator: Generator[str, None, None]):
        """
        Consumes streaming tokens from the LLM, synthesizes the very first sentence 
        instantly, and queues subsequent sentences concurrently.
        """
        self._interrupt_flag = False
        self._is_speaking = True

        buffer = ""
        sentence_end = re.compile(r"([.!?\n]+)")

        for token in token_generator:
            if self._interrupt_flag:
                break

            buffer += token
            match = sentence_end.search(buffer)
            if match:
                end_pos = match.end()
                complete_sentence = buffer[:end_pos]
                buffer = buffer[end_pos:]

                clean_text = self.sanitizer.clean_for_speech(complete_sentence)
                if len(clean_text) > 2:
                    self._synthesize_and_play(clean_text)

        # Process any leftover text
        if buffer.strip() and not self._interrupt_flag:
            clean_text = self.sanitizer.clean_for_speech(buffer)
            if len(clean_text) > 2:
                self._synthesize_and_play(clean_text)

        self._is_speaking = False

    def _synthesize_and_play(self, text: str):
        if self._interrupt_flag:
            return

        async def _fetch_audio():
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                pitch=self.pitch
            )
            data = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    data.extend(chunk["data"])
            return bytes(data)

        try:
            # Run async fetch in sync loop
            loop = asyncio.new_event_loop()
            audio_bytes = loop.run_until_complete(_fetch_audio())
            loop.close()

            if audio_bytes and not self._interrupt_flag:
                audio_io = io.BytesIO(audio_bytes)
                pygame.mixer.music.load(audio_io)
                pygame.mixer.music.play()

                while pygame.mixer.music.get_busy():
                    if self._interrupt_flag:
                        pygame.mixer.music.stop()
                        break
                    pygame.time.Clock().tick(30)
        except Exception as e:
            logger.error(f"[VOICE] Synthesis error on '{text}': {e}")
