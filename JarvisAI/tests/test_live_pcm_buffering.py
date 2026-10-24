"""Tests for chunk-aligned buffering of Gemini Live PCM output."""
from __future__ import annotations

import unittest

from main import (
    _MIN_LIVE_AUDIO_FRAME_BYTES,
    _PLAYBACK_SLICE_BYTES,
    _error_text,
    _is_transient_live_disconnect,
    _output_write_is_unpaced,
    _take_playback_pcm,
)


class LivePcmBufferingTests(unittest.TestCase):
    def test_transient_classifier_recognizes_websocket_close_1006(self):
        class AbnormalClosure(Exception):
            code = 1006

        self.assertTrue(
            _is_transient_live_disconnect(
                AbnormalClosure("abnormal closure [internal]")
            )
        )
        self.assertTrue(
            _is_transient_live_disconnect(
                RuntimeError("1006 None. abnormal closure [internal]")
            )
        )

    def test_taskgroup_classifier_sees_chained_keepalive_failure(self):
        try:
            try:
                raise TimeoutError("timed out while closing connection")
            except TimeoutError as cause:
                raise ConnectionError(
                    "sent 1011 (internal error) keepalive ping timeout; "
                    "no close frame received"
                ) from cause
        except ConnectionError as websocket_error:
            grouped = ExceptionGroup(
                "unhandled errors in a TaskGroup", [websocket_error]
            )

        flattened = _error_text(grouped).upper()
        self.assertIn("KEEPALIVE PING TIMEOUT", flattened)
        self.assertIn("TIMED OUT WHILE CLOSING CONNECTION", flattened)
        self.assertTrue(_is_transient_live_disconnect(grouped))

    def test_output_pacing_detector_waits_until_one_second_of_audio(self):
        self.assertFalse(_output_write_is_unpaced(0.99, 0.0))

    def test_output_pacing_detector_flags_writes_that_are_too_fast(self):
        self.assertTrue(_output_write_is_unpaced(1.2, 0.1))
        self.assertFalse(_output_write_is_unpaced(1.2, 0.3))

    def test_streaming_emits_full_slices_and_keeps_tiny_tail(self):
        buffer = bytearray(b"\x01\x00" * 6001)  # 12,002 bytes
        pcm = _take_playback_pcm(buffer)

        self.assertEqual(len(pcm), 5 * _PLAYBACK_SLICE_BYTES)
        self.assertEqual(len(buffer), 2)

    def test_sub_slice_fragments_are_coalesced(self):
        buffer = bytearray(b"\x01\x00" * 600)  # 1,200 bytes, 25 ms
        self.assertEqual(_take_playback_pcm(buffer), b"")
        self.assertEqual(len(buffer), 1200)

        buffer.extend(b"\x02\x00" * 600)
        pcm = _take_playback_pcm(buffer)
        self.assertEqual(len(pcm), _PLAYBACK_SLICE_BYTES)
        self.assertEqual(buffer, bytearray())

    def test_turn_end_flushes_valid_short_tail(self):
        buffer = bytearray(b"\x01\x00" * 600)  # 1,200 bytes, 25 ms
        pcm = _take_playback_pcm(buffer, final=True)

        self.assertEqual(len(pcm), 1200)
        self.assertEqual(buffer, bytearray())

    def test_turn_end_does_not_emit_tiny_tail(self):
        buffer = bytearray(_MIN_LIVE_AUDIO_FRAME_BYTES - 2)
        pcm = _take_playback_pcm(buffer, final=True)

        self.assertEqual(pcm, b"")
        self.assertEqual(len(buffer), _MIN_LIVE_AUDIO_FRAME_BYTES - 2)

    def test_odd_sample_byte_is_never_emitted(self):
        buffer = bytearray(_PLAYBACK_SLICE_BYTES + 1)
        pcm = _take_playback_pcm(buffer)

        self.assertEqual(len(pcm), _PLAYBACK_SLICE_BYTES)
        self.assertEqual(buffer, bytearray(b"\x00"))


if __name__ == "__main__":
    unittest.main()
