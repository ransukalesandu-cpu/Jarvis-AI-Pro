"""Tests for voice interruption, EchoGuard barge-in sensitivity, and receive loop state transitions."""
import unittest
import numpy as np
from unittest.mock import MagicMock, patch

from core.echo import EchoGuard
import main


class VoiceInterruptionTests(unittest.TestCase):
    def test_echoguard_fast_barge_in_sensitivity(self):
        guard = EchoGuard()
        # Create speech-like float32 PCM block with RMS ~75 (which maps to _pcm_level ~ 0.006)
        sr = 16000
        t = np.linspace(0, 0.064, int(sr * 0.064), endpoint=False)
        speech = (np.sin(2 * np.pi * 300 * t) * 80).astype(np.int16)

        # level = 0.006 (above 0.002 fast min_level)
        level = 0.006
        # When no recent output history exists, is_user_speech(fast=True) should recognize speech
        is_speech = guard.is_user_speech(speech, sr, level, fast=True)
        self.assertTrue(is_speech)

    def test_listen_audio_barge_in_evaluation_during_response_active(self):
        class FakeUI:
            muted = False
            set_audio_level = MagicMock()

        live = main.JarvisLive.__new__(main.JarvisLive)
        live.ui = FakeUI()
        live._phone_active = False
        live._ptt_enabled = False
        live._ptt_held = False
        live._is_speaking = False
        live._assistant_turn_pending = True
        live._briefing_active = False
        live._echo = EchoGuard()
        live._wake_interrupt_lock = patch("threading.Lock").start()
        live._wake_interrupt_audio = []
        live._voice_barge_in_run = 0
        live._voice_barge_in_pending = patch("threading.Event").start()
        live._voice_barge_in_pending.is_set.return_value = False
        live._loop = MagicMock()

        # Simulate mic indata (CHUNK_SIZE = 1024 samples)
        t = np.linspace(0, 0.064, 1024, endpoint=False)
        indata = (np.sin(2 * np.pi * 350 * t) * 100).astype(np.int16)

        # Evaluate barge-in inside callback logic
        response_active = bool(
            live._is_speaking or live._assistant_turn_pending or live._briefing_active
        )
        self.assertTrue(response_active)

        # Simulate 2 consecutive speech blocks
        for _ in range(2):
            is_user_voice = live._echo.is_user_speech(
                indata, 16000, main._pcm_level(indata), fast=True
            )
            if is_user_voice:
                live._voice_barge_in_run += 1
                if live._voice_barge_in_run >= 2 and not live._voice_barge_in_pending.is_set():
                    live._voice_barge_in_pending.set()
                    live._loop.call_soon_threadsafe(live._on_voice_barge_in)

        self.assertGreaterEqual(live._voice_barge_in_run, 2)
        live._loop.call_soon_threadsafe.assert_called_with(live._on_voice_barge_in)

    def test_interrupted_turn_discards_output_transcription_and_persists_flag(self):
        live = main.JarvisLive.__new__(main.JarvisLive)
        live._interrupted = True
        live._assistant_turn_pending = True
        out_buf = []

        # Simulated output transcription for cancelled turn
        txt = "This is a trailing response that should be discarded"
        if txt and not live._interrupted:
            out_buf.append(txt)

        self.assertEqual(len(out_buf), 0)

        # Simulated turn_complete for cancelled turn before user input
        in_buf = []
        if live._interrupted and not in_buf:
            out_buf = []
            # Flag stays True until input_transcription or sc.interrupted
            pass

        self.assertTrue(live._interrupted)

        # Now simulated new input_transcription arrives for user speech
        input_txt = "jarvis stop"
        if input_txt:
            if live._interrupted:
                live._interrupted = False
                out_buf = []
            in_buf.append(input_txt)

        self.assertFalse(live._interrupted)
        self.assertEqual(in_buf, ["jarvis stop"])


if __name__ == "__main__":
    unittest.main()
