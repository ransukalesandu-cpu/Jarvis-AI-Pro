"""Wake word, double-clap wake and auto-sleep handling.

Part of ``JarvisLive`` (JarvisAI/main.py), which inherits this mixin. The
methods were moved here verbatim; they run with ``self`` bound to the live
session object, so every attribute they use is set up in ``JarvisLive.__init__``.
"""


import asyncio
import time
from core.clap_wake import DoubleClapDetector
from core.wake_word import (
    install_and_download as wake_install,
    is_ready as wake_is_ready,
    WakeWordDetector,
)
from memory.config_manager import save_wake_word_enabled


class WakeSleepMixin:
    """Wake word, double-clap wake and auto-sleep handling."""

    # ── Wake word: state machine ─────────────────────────────────────────────

    def _wake_state(self) -> dict:
        # A loaded, running detector is definitively ready; otherwise fall back
        # to the cheap on-disk model-file check (no Model construction).
        ready = bool(self._wake_detector and self._wake_detector.ready) or wake_is_ready()
        return {
            "enabled": self._wake_enabled,
            "awake": self._awake,
            "ready": ready,
            "clap_ready": bool(self._clap_detector and self._clap_detector.ready),
        }

    def _ensure_clap_detector(self) -> bool:
        """Start the local clap listener independently from Hey Jarvis support."""
        if self._clap_detector is None:
            self._clap_detector = DoubleClapDetector(
                on_detect=self._on_double_clap_detected,
                logger=lambda m: print(f"[Wake] {m}"),
            )
        if not self._clap_detector.ready:
            return self._clap_detector.start()
        return True

    def _ensure_wake_detector(self) -> bool:
        """Load the detector once (model loads on first start). Idempotent."""
        self._ensure_clap_detector()
        if self._wake_detector is None:
            self._wake_detector = WakeWordDetector(
                on_detect=self._on_wake_detected,
                logger=lambda m: print(f"[Wake] {m}"),
                notify=lambda m: self.ui.write_log(f"SYS: {m}"),
            )
        if not self._wake_detector.ready:
            return self._wake_detector.start()
        return True

    def _on_wake_detected(self) -> None:
        """Interrupt speech or wake only on the local 'Hey Jarvis' detection."""
        # A voice-barge-in callback is already queued; avoid a duplicate stop.
        if self._voice_barge_in_pending.is_set():
            return
        with self._speaking_lock:
            speaking = self._is_speaking
        if speaking or self._assistant_turn_pending or self._briefing_active:
            print("[Wake] 'Hey Jarvis' detected during a JARVIS response; interrupt requested.")
            self.ui.write_log("SYS: 'Hey Jarvis' detected — interrupting speech.")
            # Count a local barge-in as user activity immediately. The Live
            # transcript may arrive only after its response has been cancelled,
            # and a reconnect during that gap must not immediately auto-sleep.
            self._last_user_speech = time.monotonic()
            # The user normally starts their actual request immediately after
            # the wake phrase. Bypass the output echo guard briefly so its tail
            # cannot clip the beginning of that request after barge-in.
            self._barge_in_until = time.monotonic() + 3.0
            loop = self._loop
            if loop and loop.is_running():
                with self._wake_interrupt_lock:
                    replay = list(self._wake_interrupt_audio)
                    self._wake_interrupt_audio.clear()
                loop.call_soon_threadsafe(self._interrupt_on_loop, replay)
            return
        # While awake, the phrase is ordinary user audio and is already being
        # streamed to Live. The detector still needs its quiet frames so it can
        # re-arm after a previous barge-in, but must not start a second briefing.
        if not self._awake:
            self.wake(reason="wake word", announce=True)

    def _on_voice_barge_in(self) -> None:
        """Stop JARVIS when sustained user speech is distinguished from speaker echo."""
        with self._speaking_lock:
            speaking = self._is_speaking
        if not (speaking or self._assistant_turn_pending or self._briefing_active):
            self._voice_barge_in_pending.clear()
            self._voice_barge_in_run = 0
            return

        # Treat the interruption as user activity and preserve the last ~1.5 s
        # of mic audio so the beginning of the spoken request reaches Gemini.
        self._last_user_speech = time.monotonic()
        self._barge_in_until = time.monotonic() + 3.0
        with self._wake_interrupt_lock:
            replay = list(self._wake_interrupt_audio)
            self._wake_interrupt_audio.clear()
        print("[Voice] User speech detected during JARVIS playback; interrupting.")
        self.ui.write_log("SYS: Voice detected — interrupting JARVIS.")
        # The microphone callback has already marshalled this handler onto
        # the asyncio loop, so keep queue and playback lifecycle changes here.
        self._interrupt_on_loop(replay)

    def _on_double_clap_detected(self) -> None:
        """The clap worker calls from its own thread; marshal state changes."""
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(self._schedule_clap_wake_briefing)

    def _schedule_clap_wake_briefing(self) -> None:
        """Wake on the event loop and run the normal time/news briefing."""
        if self._awake:
            return
        self.wake(reason="two claps")
        asyncio.create_task(self._send_startup_briefing(wake_trigger=True))

    def _announce_wake(self) -> None:
        """Ask the Live voice to give the short wake greeting."""
        self.speak('Say exactly: "I\'m awake, sir. How can I help?"')

    def wake(self, reason: str = "wake word", announce: bool = False) -> None:
        if self._awake:
            return
        self._awake = True
        self._last_user_speech = time.monotonic()   # start the auto-sleep clock now
        if not self.ui.muted:
            self.ui.set_state("LISTENING")
        self.ui.write_log(f"SYS: Awake — {reason}.")
        if announce:
            self._announce_wake()

    def sleep(self, reason: str = "timeout") -> None:
        if not self._awake:
            return
        self._awake = False
        self.set_speaking(False)
        self.ui.set_state("SLEEPING")
        wake_methods = "clap twice or tap WAKE NOW"
        if self._wake_enabled:
            wake_methods = "say 'Hey Jarvis', " + wake_methods
        self.ui.write_log(
            f"SYS: Sleeping — {reason}. {wake_methods} to wake me."
        )

    async def _run_sleep_watch(self) -> None:
        """Auto-sleep after inactivity; clap wake remains available in standby."""
        while True:
            await asyncio.sleep(5)
            if not self._awake:
                continue
            with self._speaking_lock:
                speaking = self._is_speaking
            # A long news fetch or tool turn can be silent for longer than the
            # idle timeout. Do not treat that silence as user inactivity: the
            # active turn/briefing still owns the conversation, and sleeping
            # here can discard a wake interruption when the Live socket later
            # reconnects.
            if (speaking or self._assistant_turn_pending
                    or self._briefing_active or self._interrupted):
                continue
            if (time.monotonic() - self._last_user_speech) > self._wake_sleep_timeout:
                self.sleep(reason="no speech for 2 minutes")

    # ── Wake word: UI callbacks (called from the Qt thread) ──────────────────

    def _ui_wake_toggle(self, enable: bool) -> str:
        """Enable/disable wake word from the settings UI. Returns a status token:
        'enabled' | 'disabled' | 'need_download'."""
        if enable:
            if not wake_is_ready():
                return "need_download"
            self._wake_enabled = True
            save_wake_word_enabled(True)
            self._ensure_wake_detector()
            self.sleep(reason="wake word enabled")
            return "enabled"
        else:
            self._wake_enabled = False
            save_wake_word_enabled(False)
            # Keep the independent two-clap listener active. If JARVIS was
            # asleep, it remains asleep and can still be woken by clapping.
            return "disabled"

    def _ui_wake_manual(self) -> None:
        """Manual sleep/wake button in the UI."""
        if self._awake:
            self.sleep(reason="you tapped sleep")
        else:
            self.wake(reason="you tapped wake", announce=True)

    def _ui_wake_install(self) -> tuple[bool, str]:
        """Download openwakeword + the model (runs in a UI worker thread)."""
        # Triggered by the user pressing the button, so its progress is exactly
        # what they are waiting to see.
        return wake_install(logger=lambda m: print(f"[Wake] {m}"),
                            notify=lambda m: self.ui.write_log(f"SYS: {m}"))
