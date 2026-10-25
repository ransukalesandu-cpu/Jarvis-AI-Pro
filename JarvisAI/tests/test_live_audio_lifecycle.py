"""Deterministic unit and regression tests for Gemini Live audio lifecycle, buffering, prebuffering, interruption, and turn-completion."""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from JarvisAI.main import (
    JarvisLive,
    _take_playback_pcm,
    _MIN_LIVE_AUDIO_FRAME_BYTES,
    _PLAYBACK_SLICE_BYTES,
    _MIN_PREBUFFER_BYTES,
)


class LiveAudioLifecycleTests(unittest.TestCase):
    def test_take_playback_pcm_slice_alignment_during_streaming(self):
        buffer = bytearray(b"\x00" * (_PLAYBACK_SLICE_BYTES + 100))
        pcm = _take_playback_pcm(buffer, final=False)
        self.assertEqual(len(pcm), _PLAYBACK_SLICE_BYTES)
        self.assertEqual(len(buffer), 100)

    def test_take_playback_pcm_short_tail_on_turn_complete(self):
        buffer = bytearray(b"\x00" * (_MIN_LIVE_AUDIO_FRAME_BYTES + 4))
        pcm = _take_playback_pcm(buffer, final=True)
        self.assertEqual(len(pcm), _MIN_LIVE_AUDIO_FRAME_BYTES + 4)
        self.assertEqual(len(buffer), 0)

    def test_take_playback_pcm_discards_tiny_unaligned_tail_on_turn_complete(self):
        buffer = bytearray(b"\x00" * (_MIN_LIVE_AUDIO_FRAME_BYTES - 2))
        pcm = _take_playback_pcm(buffer, final=True)
        self.assertEqual(len(pcm), 0)
        self.assertEqual(len(buffer), _MIN_LIVE_AUDIO_FRAME_BYTES - 2)


class LiveAudioInterruptionAndTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ui = MagicMock()
        self.jarvis = JarvisLive.__new__(JarvisLive)
        self.jarvis.ui = self.ui
        self.jarvis._loop = asyncio.get_running_loop()
        self.jarvis.audio_in_queue = asyncio.Queue()
        self.jarvis.out_queue = asyncio.Queue()
        self.jarvis._turn_done_event = asyncio.Event()
        self.jarvis._playback_interrupt_requested = MagicMock()
        self.jarvis._output_stream = MagicMock()
        self.jarvis._speaking_lock = MagicMock()
        self.jarvis._is_speaking = False
        self.jarvis._assistant_turn_pending = True
        self.jarvis._briefing_active = False
        self.jarvis._briefing_cancelled = False
        self.jarvis._briefing_task = None
        self.jarvis._wake_interrupt_audio = []
        self.jarvis._wake_interrupt_lock = MagicMock()
        self.jarvis._visemes = MagicMock()
        self.jarvis._vocal_plan = MagicMock()
        self.jarvis._vocal_plan_ready = False
        self.jarvis._vocal_audio_started = False
        self.jarvis._play_cursor = 0.0
        self.jarvis._out_latency = 0.20
        self.jarvis._tail_until = 0.0

    async def test_interrupt_on_loop_clears_audio_queues_and_resets_turn_state(self):
        await self.jarvis.audio_in_queue.put(b"audio_chunk_1")
        await self.jarvis.audio_in_queue.put(b"audio_chunk_2")

        self.jarvis._interrupt_on_loop()

        self.assertTrue(self.jarvis._interrupted)
        self.assertTrue(self.jarvis.audio_in_queue.empty())
        self.assertTrue(self.jarvis._turn_done_event.is_set())
        self.assertFalse(self.jarvis._assistant_turn_pending)
        self.jarvis.ui.write_log.assert_called_with("SYS: Interrupted — listening...")


if __name__ == "__main__":
    unittest.main()
