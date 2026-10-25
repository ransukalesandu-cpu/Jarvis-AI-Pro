"""Regression tests for interrupting audio already buffered for playback."""
import asyncio
import threading
import unittest
from types import SimpleNamespace

from main import JarvisLive, VocalPlan


class PendingPlaybackInterruptTests(unittest.TestCase):
    def _assistant(self, *, turn_done=False, queued_audio=()):
        assistant = object.__new__(JarvisLive)
        assistant._speaking_lock = threading.Lock()
        assistant._is_speaking = False
        assistant._assistant_turn_pending = False
        assistant._briefing_active = False
        assistant._briefing_cancelled = False
        assistant._briefing_task = None
        assistant._interrupted = False
        assistant._playback_interrupt_requested = threading.Event()
        assistant._output_stream = None
        assistant._turn_done_event = asyncio.Event()
        if turn_done:
            assistant._turn_done_event.set()
        assistant.audio_in_queue = asyncio.Queue()
        for chunk in queued_audio:
            assistant.audio_in_queue.put_nowait(chunk)
        assistant.out_queue = None
        assistant._vocal_plan = VocalPlan()
        assistant._vocal_plan_ready = True
        assistant._vocal_audio_started = True
        assistant._visemes = SimpleNamespace(reset=lambda: None)
        assistant._play_cursor = 1.0
        assistant.set_speaking = lambda _value: None
        assistant.ui = SimpleNamespace(write_log=lambda _message: None)
        return assistant

    def test_interrupt_cancels_pcm_already_in_local_prebuffer_after_turn_complete(self):
        # The playback worker may have drained the asyncio queue into its local
        # pending_pcm bytearray. turn_complete is then the remaining signal that
        # audio is still pending, even though the assistant is not yet speaking.
        assistant = self._assistant(turn_done=True)
        self.assertTrue(assistant.audio_in_queue.empty())

        JarvisLive._interrupt_on_loop(assistant)

        self.assertTrue(assistant._interrupted)
        self.assertTrue(assistant._playback_interrupt_requested.is_set())

    def test_interrupt_cancels_audio_still_waiting_in_queue(self):
        assistant = self._assistant(queued_audio=(b"pcm",))

        JarvisLive._interrupt_on_loop(assistant)

        self.assertTrue(assistant._interrupted)
        self.assertTrue(assistant._playback_interrupt_requested.is_set())
        self.assertTrue(assistant.audio_in_queue.empty())

    def test_idle_interrupt_does_not_mark_an_inactive_turn_interrupted(self):
        assistant = self._assistant()

        JarvisLive._interrupt_on_loop(assistant)

        self.assertFalse(assistant._interrupted)
        self.assertFalse(assistant._playback_interrupt_requested.is_set())


if __name__ == "__main__":
    unittest.main()
