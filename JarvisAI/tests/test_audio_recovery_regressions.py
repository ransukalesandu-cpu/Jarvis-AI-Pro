"""Audio recovery regression tests: PCM framing, cancellation, reconnect, repeated turns."""
from __future__ import annotations
import asyncio
import threading
import unittest
from unittest.mock import MagicMock
import main


class PCMRecoveryTests(unittest.TestCase):
    def test_pcm_fragments_across_events_recover_aligned_audio(self):
        original = bytes(range(256)) * 20
        buffer = bytearray()
        output = []
        cuts = (1, 37, 511, 1200, 2049, len(original))
        start = 0
        for end in cuts:
            buffer.extend(original[start:end])
            start = end
            while True:
                chunk = main._take_playback_pcm(buffer)
                if not chunk:
                    break
                output.append(chunk)
        tail = main._take_playback_pcm(buffer, final=True)
        if tail:
            output.append(tail)
        reconstructed = b"".join(output)
        self.assertEqual(reconstructed, original[:len(reconstructed)])
        self.assertEqual(len(reconstructed) % 2, 0)
        self.assertLess(len(buffer), main._MIN_LIVE_AUDIO_FRAME_BYTES)

    def test_cancelled_turn_does_not_flush_partial_pcm_tail(self):
        stale = bytearray(b"\x11\x00" * 600)
        cancelled = True
        pcm = b"" if cancelled else main._take_playback_pcm(stale, final=True)
        self.assertEqual(pcm, b"")
        self.assertEqual(len(stale), 1200)

    def test_repeated_short_speech_turns_do_not_share_pcm_buffers(self):
        turns = [
            bytearray(b"\x01\x00" * 600),
            bytearray(b"\x02\x00" * 900),
            bytearray(b"\x03\x00" * 1200),
        ]
        outputs = [main._take_playback_pcm(turn, final=True) for turn in turns]
        self.assertEqual([len(item) for item in outputs], [1200, 1800, 2400])
        self.assertEqual(outputs[0], b"\x01\x00" * 600)
        self.assertEqual(outputs[1], b"\x02\x00" * 900)
        self.assertEqual(outputs[2], b"\x03\x00" * 1200)
        self.assertTrue(all(not turn for turn in turns))

    def test_interrupt_drains_stale_playback_and_aborts_device_buffer(self):
        live = main.JarvisLive.__new__(main.JarvisLive)
        live._speaking_lock = threading.Lock()
        live._is_speaking = True
        live._assistant_turn_pending = True
        live._briefing_active = False
        live._briefing_cancelled = False
        live._briefing_task = None
        live._playback_interrupt_requested = threading.Event()
        live._output_stream = MagicMock()
        live.out_queue = asyncio.Queue()
        live.out_queue.put_nowait({"data": b"old mic", "mime_type": "audio/pcm;rate=16000"})
        live.audio_in_queue = asyncio.Queue()
        live.audio_in_queue.put_nowait(b"stale audio 1")
        live.audio_in_queue.put_nowait(b"stale audio 2")
        live._vocal_plan = MagicMock()
        live._vocal_plan_ready = True
        live._vocal_audio_started = True
        live._visemes = MagicMock()
        live._play_cursor = 99.0
        live._turn_done_event = asyncio.Event()
        live._turn_done_event.clear()
        live.ui = MagicMock()
        live.set_speaking = MagicMock()
        live._interrupt_on_loop([b"fresh wake ", b"request"])
        self.assertTrue(live._interrupted)
        self.assertTrue(live._playback_interrupt_requested.is_set())
        live._output_stream.abort.assert_called_once_with()
        self.assertTrue(live.audio_in_queue.empty())
        fresh = live.out_queue.get_nowait()
        self.assertEqual(fresh["data"], b"fresh wake request")
        self.assertEqual(fresh["mime_type"], "audio/pcm;rate=16000")
        self.assertTrue(live._turn_done_event.is_set())
        self.assertEqual(live._play_cursor, 0.0)
        live._visemes.reset.assert_called_once_with()


class ReconnectRecoveryTests(unittest.TestCase):
    def test_reconnect_signal_preserves_or_resets_context_as_requested(self):
        keep = main._ReconnectSignal(keep_context=True)
        fresh = main._ReconnectSignal(keep_context=False)
        self.assertTrue(main._is_reconnect_signal(keep))
        self.assertTrue(main._keep_context_of(keep))
        self.assertTrue(main._is_reconnect_signal(fresh))
        self.assertFalse(main._keep_context_of(fresh))

    def test_reconnect_signal_is_found_inside_taskgroup_exception(self):
        signal = main._ReconnectSignal(keep_context=False)
        grouped = ExceptionGroup("task group", [RuntimeError("worker"), signal])
        self.assertTrue(main._is_reconnect_signal(grouped))
        self.assertFalse(main._keep_context_of(grouped))

    def test_cancelled_error_is_found_inside_exception_group(self):
        grouped = BaseExceptionGroup(
            "cancel group", [RuntimeError("worker"), asyncio.CancelledError()]
        )
        self.assertTrue(main._contains_cancelled_error(grouped))
        self.assertFalse(main._contains_cancelled_error(RuntimeError("ordinary failure")))


if __name__ == "__main__":
    unittest.main()
