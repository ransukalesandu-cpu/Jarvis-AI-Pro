"""Tests for chunk-aligned buffering of Gemini Live PCM output."""
from __future__ import annotations

import unittest

from main import (
    _MIN_LIVE_AUDIO_FRAME_BYTES,
    _PLAYBACK_SLICE_BYTES,
    _take_playback_pcm,
)


class LivePcmBufferingTests(unittest.TestCase):
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
