"""Regression tests for the Phase 4 "stops speaking mid-sentence" fixes.

The playback worker is driven with a fake output stream and fake host, so no
audio hardware is needed.
"""
from __future__ import annotations

import asyncio
import io
import threading
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from core.audio_playback import drop_pending_pcm, run_audio_playback
from core.barge_in import HeldAudio
from core.live_audio import _output_write_is_unpaced

CHUNK = 4800  # 100 ms of 24 kHz mono int16


def chunk(value: int) -> bytes:
    return bytes([value]) * CHUNK


class PacingCheckTests(unittest.TestCase):
    def test_default_behaviour_is_unchanged(self):
        self.assertFalse(_output_write_is_unpaced(0.99, 0.0))
        self.assertTrue(_output_write_is_unpaced(1.2, 0.1))
        self.assertFalse(_output_write_is_unpaced(1.2, 0.3))

    def test_device_buffer_is_not_mistaken_for_a_silent_endpoint(self):
        # 1.0 s submitted; a 0.85 s buffer absorbed most of it instantly and the
        # remaining 0.15 s took real time. The old check called this unpaced.
        self.assertTrue(_output_write_is_unpaced(1.0, 0.15))
        self.assertFalse(_output_write_is_unpaced(1.0, 0.15, 0.85))
        # A healthy 500 ms-buffer device judged after 1.5 s of audio.
        self.assertFalse(_output_write_is_unpaced(1.5, 0.95, 0.5))

    def test_truly_unpaced_endpoint_is_still_detected(self):
        self.assertTrue(_output_write_is_unpaced(1.5, 0.01, 0.5))
        self.assertFalse(_output_write_is_unpaced(1.0, 0.0, 1.2))
        self.assertFalse(_output_write_is_unpaced(1.5, 0.01, "bad"))


class HeldAudioPrependTests(unittest.TestCase):
    def test_prepend_keeps_playback_order(self):
        held = HeldAudio()
        held.prepend(b"x")                  # inactive: ignored
        self.assertEqual(held.chunks, [])
        held.begin([b"queued"])
        held.hold(b"later")
        held.prepend(b"worker")
        self.assertEqual(held.chunks, [b"worker", b"queued", b"later"])


class DropPendingPcmTests(unittest.TestCase):
    def test_explicit_interrupt_discards(self):
        held = HeldAudio()
        host = SimpleNamespace(_held_audio_state=lambda: held)
        pending = bytearray(b"abc")
        self.assertFalse(drop_pending_pcm(host, pending))
        self.assertEqual(pending, bytearray())
        self.assertEqual(held.chunks, [])

    def test_provisional_barge_in_keeps_the_words(self):
        held = HeldAudio()
        held.begin([b"queued"])
        host = SimpleNamespace(_held_audio_state=lambda: held)
        pending = bytearray(b"worker")
        drop_pending_pcm(host, pending)
        self.assertEqual(pending, bytearray())
        self.assertEqual(held.chunks, [b"worker", b"queued"])

    def test_host_without_held_audio(self):
        pending = bytearray(b"abc")
        drop_pending_pcm(SimpleNamespace(), pending)
        self.assertEqual(pending, bytearray())


class FakeStream:
    """Blocking-write stand-in. ``on_write`` may raise to simulate an abort."""

    def __init__(self, on_write):
        self.on_write = on_write
        self.written: list[bytes] = []
        self.active = True
        self.latency = 0.05

    def start(self):
        self.active = True

    def abort(self):
        self.active = False

    def stop(self):
        self.active = False

    def close(self):
        pass

    def write(self, data):
        self.on_write(self, bytes(data))
        self.written.append(bytes(data))
        return False


class PlaybackWorkerTests(unittest.TestCase):
    @staticmethod
    def make_host(held=None):
        return SimpleNamespace(
            _playback_interrupt_requested=threading.Event(),
            _shutdown_requested=False,
            audio_in_queue=asyncio.Queue(),
            _turn_done_event=asyncio.Event(),
            _assistant_turn_pending=True,
            set_speaking=lambda _value: None,
            ui=SimpleNamespace(write_log=lambda _m: None, push_visemes=lambda *a: None,
                               set_audio_level=lambda _l: None, muted=False),
            _out_latency=0.05,
            _play_cursor=0.0,
            _visemes=SimpleNamespace(frames=lambda frames, hop: []),
            _echo=SimpleNamespace(note_output=lambda *a: None),
            _out_level=0.0,
            _phone_active=False,
            _dashboard=None,
            _output_stream=None,
            _held_audio_state=lambda: held or HeldAudio(),
        )

    @staticmethod
    def playback(host, stream):
        backend = SimpleNamespace(RawOutputStream=lambda **_kw: stream,
                                  query_devices=lambda *a: {}, query_hostapis=lambda: [])
        service = SimpleNamespace(resolve=lambda *_a: None)
        return run_audio_playback(
            host, audio_backend=backend, device_service=service,
            get_output_device_fn=lambda: "", pcm_visemes_fn=lambda pcm, sr: [],
            output_executor=None, tail_margin=0.1, first_sound_delay=0.0,
            cursor_slack=0.1, viseme_hop=480,
        )

    def run_worker(self, on_write, *, held=None, chunks=(1, 2, 3, 4)):
        async def scenario():
            host = self.make_host(held)
            for value in chunks:
                host.audio_in_queue.put_nowait(chunk(value))
            stream = FakeStream(lambda s, data: on_write(host, s, data))
            await asyncio.wait_for(self.playback(host, stream), timeout=5.0)
            return stream

        with redirect_stdout(io.StringIO()):
            return asyncio.run(scenario())

    @staticmethod
    def interrupt_during_second_write(next_answer: int, held=None):
        """Abort the 2nd write the way _interrupt_on_loop does, then queue a new answer."""
        state = {"writes": 0}

        def on_write(host, stream, data):
            if data[0] == next_answer:
                host._shutdown_requested = True
                return
            state["writes"] += 1
            if state["writes"] == 2:
                host._playback_interrupt_requested.set()
                if held is not None:
                    held.begin([])
                while not host.audio_in_queue.empty():
                    host.audio_in_queue.get_nowait()
                host.audio_in_queue.put_nowait(chunk(next_answer))
                host._turn_done_event.set()
                stream.abort()
                raise RuntimeError("Stream is stopped")
        return on_write

    def test_aborted_write_does_not_replay_the_interrupted_answer(self):
        stream = self.run_worker(self.interrupt_during_second_write(99))
        firsts = [data[0] for data in stream.written]
        # chunk 3 was in the worker's private buffer when the write aborted;
        # before the fix it played after the interrupt.
        self.assertEqual(firsts, [1, 99])

    def test_aborted_write_on_provisional_barge_in_holds_the_buffered_words(self):
        held = HeldAudio()
        stream = self.run_worker(self.interrupt_during_second_write(99, held), held=held)
        self.assertEqual([data[0] for data in stream.written], [1, 99])
        self.assertEqual(held.chunks, [chunk(3)])


    def test_interrupt_during_prebuffer_holds_the_buffered_words_in_order(self):
        # Interrupt before the first write: chunks 1 and 2 sit in the worker's
        # prebuffer (200 ms < 300 ms target), chunk 3 is still queued.
        held = HeldAudio()

        async def scenario():
            host = self.make_host(held)
            stream = FakeStream(lambda s, data: None)
            worker = asyncio.ensure_future(self.playback(host, stream))
            host.audio_in_queue.put_nowait(chunk(1))
            host.audio_in_queue.put_nowait(chunk(2))
            await asyncio.sleep(0.3)               # the worker takes both, then waits
            host.audio_in_queue.put_nowait(chunk(3))
            queued = []                            # what _interrupt_on_loop does
            while not host.audio_in_queue.empty():
                queued.append(host.audio_in_queue.get_nowait())
            held.begin(queued)
            host._playback_interrupt_requested.set()
            await asyncio.sleep(0.3)
            host._shutdown_requested = True
            await asyncio.wait_for(worker, timeout=5.0)
            return host, stream

        with redirect_stdout(io.StringIO()):
            host, stream = asyncio.run(scenario())
        self.assertEqual(stream.written, [])                    # nothing played early
        self.assertFalse(host._playback_interrupt_requested.is_set())
        self.assertEqual(held.chunks, [chunk(1) + chunk(2), chunk(3)])

if __name__ == "__main__":
    unittest.main()
