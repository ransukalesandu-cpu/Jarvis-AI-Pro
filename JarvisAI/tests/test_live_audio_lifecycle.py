"""Deterministic unit and regression tests for Gemini Live audio lifecycle, buffering, prebuffering, interruption, and turn-completion."""

import asyncio
import threading
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

    def test_take_playback_pcm_sample_split_across_fragments(self):
        # 16-bit PCM sample split across fragments:
        # Fragment 1: 2400 bytes (1 full 50ms slice) + 1st byte of a split 16-bit sample (0x03)
        buffer = bytearray(b"\x01\x02" * 1200 + b"\x03")
        pcm1 = _take_playback_pcm(buffer, final=False)

        self.assertEqual(len(pcm1), _PLAYBACK_SLICE_BYTES)
        self.assertEqual(len(pcm1) % 2, 0)  # Always 16-bit sample aligned
        self.assertEqual(len(buffer), 1)    # Incomplete 1-byte retained
        self.assertEqual(buffer[0], 0x03)

        # Fragment 2 arrives with the 2nd byte of the split sample (0x04) + additional frame bytes
        fragment2 = b"\x04" + b"\x05\x06" * (_MIN_LIVE_AUDIO_FRAME_BYTES // 2)
        buffer.extend(fragment2)

        pcm2 = _take_playback_pcm(buffer, final=True)
        self.assertGreaterEqual(len(pcm2), _MIN_LIVE_AUDIO_FRAME_BYTES + 2)
        self.assertEqual(len(pcm2) % 2, 0)
        # Verify reconstructed 16-bit sample (0x03, 0x04)
        self.assertEqual(pcm2[:2], b"\x03\x04")
        self.assertEqual(len(buffer), 0)


class LiveAudioInterruptionAndTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ui = MagicMock()
        self.jarvis = JarvisLive.__new__(JarvisLive)
        self.jarvis.ui = self.ui
        self.jarvis._loop = asyncio.get_running_loop()
        self.jarvis.audio_in_queue = asyncio.Queue()
        self.jarvis.out_queue = asyncio.Queue()
        self.jarvis._turn_done_event = asyncio.Event()
        self.jarvis._playback_interrupt_requested = threading.Event()
        self.jarvis._output_stream = MagicMock()
        self.jarvis._speaking_lock = threading.Lock()
        self.jarvis._is_speaking = False
        self.jarvis._assistant_turn_pending = True
        self.jarvis._briefing_active = False
        self.jarvis._briefing_cancelled = False
        self.jarvis._briefing_task = None
        self.jarvis._wake_interrupt_audio = []
        self.jarvis._wake_interrupt_lock = threading.Lock()
        self.jarvis._visemes = MagicMock()
        self.jarvis._vocal_plan = MagicMock()
        self.jarvis._vocal_plan_ready = False
        self.jarvis._vocal_audio_started = False
        self.jarvis._play_cursor = 0.0
        self.jarvis._out_latency = 0.20
        self.jarvis._tail_until = 0.0
        self.jarvis._phone_active = False
        self.jarvis._shutdown_requested = False

    async def test_interrupt_on_loop_clears_audio_queues_and_resets_turn_state(self):
        await self.jarvis.audio_in_queue.put(b"audio_chunk_1")
        await self.jarvis.audio_in_queue.put(b"audio_chunk_2")

        self.jarvis._interrupt_on_loop()

        self.assertTrue(self.jarvis._interrupted)
        self.assertTrue(self.jarvis.audio_in_queue.empty())
        self.assertTrue(self.jarvis._turn_done_event.is_set())
        self.assertFalse(self.jarvis._assistant_turn_pending)
        self.jarvis.ui.write_log.assert_called_with("SYS: Interrupted — listening...")

    async def test_completed_turn_interruption_aborts_output_stream_and_requests_cancellation(self):
        # Isolate completed-turn playback_pending branch:
        # _is_speaking = False, _assistant_turn_pending = False, but _turn_done_event is set
        self.jarvis._is_speaking = False
        self.jarvis._assistant_turn_pending = False
        self.jarvis._turn_done_event.set()

        self.jarvis._interrupt_on_loop()

        # Verify playback interrupt event is set, stream abort called, and state marked interrupted
        self.assertTrue(self.jarvis._playback_interrupt_requested.is_set())
        self.jarvis._output_stream.abort.assert_called_once()
        self.assertTrue(self.jarvis._interrupted)

    async def test_real_play_audio_worker_discards_local_pending_pcm_on_interruption(self):
        written_chunks = []
        write_started = asyncio.Event()
        write_unblock = threading.Event()

        main_loop = self.jarvis._loop

        class FakeStream:
            def __init__(self):
                self.active = True
                self.latency = 0.05
            def start(self):
                self.active = True
            def stop(self):
                self.active = False
            def close(self):
                self.active = False
            def abort(self):
                self.active = False
            def write(self, data):
                written_chunks.append(data)
                main_loop.call_soon_threadsafe(write_started.set)
                write_unblock.wait(timeout=2.0)

        fake_stream = FakeStream()
        fake_sd = MagicMock()
        fake_sd.RawOutputStream.return_value = fake_stream

        with patch("JarvisAI.main.sd", fake_sd), \
             patch("JarvisAI.main.get_output_device", return_value="custom_speaker"), \
             patch("core.audio_devices.resolve", return_value=None):

            # Enqueue 24000 bytes (5 full 4800-byte batches)
            pcm_chunk = b"\x00\x01" * 12000
            await self.jarvis.audio_in_queue.put(pcm_chunk)

            # Start real play_audio worker in background
            play_task = asyncio.create_task(self.jarvis._play_audio())

            # Wait until worker enters write for batch 1
            await asyncio.wait_for(write_started.wait(), timeout=2.0)

            # Issue interruption while batch 1 is in-flight and batch 2..5 remain in pending_pcm
            self.jarvis._interrupt_on_loop()

            # Release write call for batch 1
            write_unblock.set()

            # Wait for worker to process interruption and clear the interrupt flag
            for _ in range(50):
                if not self.jarvis._playback_interrupt_requested.is_set():
                    break
                await asyncio.sleep(0.01)

            self.jarvis._shutdown_requested = True
            await asyncio.wait_for(play_task, timeout=2.0)

            # Assert ONLY batch 1 was written; the remaining 4 batches in local pending_pcm were discarded
            self.assertEqual(len(written_chunks), 1)
            self.assertFalse(self.jarvis._playback_interrupt_requested.is_set())


if __name__ == "__main__":
    unittest.main()
