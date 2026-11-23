"""Offline voice fallback wiring for ``JarvisLive`` (see voice/offline_loop.py).

A watcher task starts the local listen → transcribe → Brain Engine → local TTS
loop while Gemini Live is down and stops it as soon as a Live session is open
again, so the two never fight over the conversation.
"""
from __future__ import annotations

import asyncio
import threading
import time

from jarvis.core import failsoft

WATCH_INTERVAL_S = 2.0


class OfflineVoiceMixin:
    """Starts/stops the offline voice loop and speaks fallback answers."""

    _offline_voice = None
    _offline_tts = None
    _offline_tts_lock = threading.Lock()

    def offline_voice_active(self) -> bool:
        loop = self._offline_voice
        return bool(loop is not None and loop.running)

    async def _offline_voice_watch(self) -> None:
        from jarvis.core import privacy
        from jarvis.voice import local_stt, offline_loop

        down_since = time.monotonic()
        announced_missing = False
        while not self._shutdown_requested:
            live_up = self.session is not None
            if live_up:
                down_since = time.monotonic()
            stt_ready = local_stt.available()
            run = offline_loop.should_run(
                live_up=live_up,
                down_for_s=time.monotonic() - down_since,
                offline=privacy.offline_enabled(),
                stt_ready=stt_ready,
            )
            if run and not self.offline_voice_active():
                self._start_offline_voice()
            elif not run and self.offline_voice_active():
                self._stop_offline_voice()
            if (not live_up and not stt_ready and not announced_missing
                    and offline_loop.mode() != "off"
                    and time.monotonic() - down_since >= offline_loop.DEFAULT_GRACE_S):
                announced_missing = True
                self.ui.write_log(
                    "SYS: Gemini Live is down. Install offline speech "
                    "(pip install -r requirements-stt.txt) to keep talking to JARVIS offline."
                )
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=WATCH_INTERVAL_S)
            except asyncio.TimeoutError:
                continue
            except Exception:
                await asyncio.sleep(WATCH_INTERVAL_S)
        self._stop_offline_voice()

    def _start_offline_voice(self) -> None:
        from jarvis.voice.offline_loop import OfflineVoiceLoop

        def wake_feed(frame):
            detector = self._wake_detector
            if detector is not None and detector.ready:
                detector.feed(frame)

        def is_speaking() -> bool:
            with self._speaking_lock:
                return bool(self._is_speaking) or self._tail_active()

        self._offline_voice = OfflineVoiceLoop(
            submit=self._on_offline_utterance,
            is_awake=lambda: bool(self._awake),
            is_speaking=is_speaking,
            wake_feed=wake_feed if self._wake_enabled else None,
            logger=self.ui.write_log,
        )
        self._offline_voice.start()

    def _stop_offline_voice(self) -> None:
        loop, self._offline_voice = self._offline_voice, None
        if loop is not None:
            try:
                loop.stop()
            except Exception:
                failsoft.suppress("core.runtime.live_offline_voice:stop")

    def _on_offline_utterance(self, text: str) -> None:
        # Spoken requests count as user activity and then follow the exact
        # typed-command path (privacy lock, PIN, wake, agent, Brain Engine).
        self._last_user_speech = time.monotonic()
        try:
            self.ui.write_log(f"YOU: {text}")
        except Exception:
            failsoft.suppress("core.runtime.live_offline_voice:log")
        self._on_text_command(text)

    def _speak_offline(self, text: str) -> None:
        """Speak a fallback answer with a local engine; blocking, call from a worker thread."""
        if not text or not self.offline_voice_active():
            return
        with self._offline_tts_lock:
            if self._offline_tts is None:
                from jarvis.voice.offline_loop import pick_local_tts
                self._offline_tts = pick_local_tts()
                if self._offline_tts is None:
                    self.ui.write_log(
                        "SYS: No local voice engine installed (pip install kokoro soundfile); "
                        "showing the answer as text only."
                    )
                    self._offline_tts = False
            player = self._offline_tts
        if not player:
            return
        from jarvis.voice.sanitizer import SpeechSanitizer
        spoken = SpeechSanitizer.clean_for_speech(text)
        if not spoken:
            return
        player.speak(spoken, on_start=lambda: self.set_speaking(True),
                     on_done=lambda: self.set_speaking(False))
