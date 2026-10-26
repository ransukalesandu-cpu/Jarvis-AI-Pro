"""Focused tests for pure Gemini Live audio helpers."""

from __future__ import annotations

import base64
import unittest
from types import SimpleNamespace

from core.live_audio import (
    CHANNELS,
    RECEIVE_SAMPLE_RATE,
    _MIN_LIVE_AUDIO_FRAME_BYTES,
    _PLAYBACK_SLICE_BYTES,
    _error_text,
    _is_live_operation_aborted,
    _is_quota_error,
    _is_transient_live_disconnect,
    _live_audio_chunks,
    _output_write_is_unpaced,
    _pcm_level,
    _take_playback_pcm,
)


class LiveAudioHelperTests(unittest.TestCase):
    def test_audio_format_constants_describe_mono_24khz_pcm(self):
        self.assertEqual(CHANNELS, 1)
        self.assertEqual(RECEIVE_SAMPLE_RATE, 24_000)
        self.assertEqual(_MIN_LIVE_AUDIO_FRAME_BYTES, 480)
        self.assertEqual(_PLAYBACK_SLICE_BYTES, 2_400)

    def test_playback_pcm_emits_only_full_aligned_slices_during_streaming(self):
        pending = bytearray(b"\\x01\\x00" * 1_201)
        result = _take_playback_pcm(pending)
        self.assertEqual(result, b"\\x01\\x00" * 1_200)
        self.assertEqual(pending, bytearray(b"\\x01\\x00"))

    def test_playback_pcm_flushes_valid_final_tail(self):
        pending = bytearray(b"\\x02\\x00" * 600)
        self.assertEqual(_take_playback_pcm(pending, final=True), b"\\x02\\x00" * 600)
        self.assertEqual(pending, bytearray())

    def test_playback_pcm_does_not_emit_tiny_final_tail(self):
        pending = bytearray(_MIN_LIVE_AUDIO_FRAME_BYTES - 2)
        self.assertEqual(_take_playback_pcm(pending, final=True), b"")
        self.assertEqual(len(pending), _MIN_LIVE_AUDIO_FRAME_BYTES - 2)

    def test_output_pacing_detector_has_a_full_second_guard(self):
        self.assertFalse(_output_write_is_unpaced(0.99, 0.0))
        self.assertTrue(_output_write_is_unpaced(1.2, 0.1))
        self.assertFalse(_output_write_is_unpaced(1.2, 0.3))

    def test_pcm_level_handles_empty_silence_and_normalized_loudness(self):
        self.assertEqual(_pcm_level([]), 0.0)
        self.assertEqual(_pcm_level([0] * 16), 0.0)
        self.assertEqual(_pcm_level([60] * 16), 0.0)
        self.assertAlmostEqual(_pcm_level([1_330] * 16), 0.5)
        self.assertEqual(_pcm_level([6_000] * 16), 1.0)

    def test_live_audio_chunks_collects_audio_parts_and_ignores_other_mime_types(self):
        response = SimpleNamespace(
            server_content=SimpleNamespace(
                model_turn=SimpleNamespace(
                    parts=[
                        SimpleNamespace(inline_data=SimpleNamespace(mime_type="audio/pcm", data=b"first")),
                        SimpleNamespace(inline_data=SimpleNamespace(mime_type="image/png", data=b"not audio")),
                        SimpleNamespace(inline_data=SimpleNamespace(mime_type="audio/pcm", data=b"second")),
                    ]
                )
            ),
            data=b"convenience-data-should-not-duplicate",
        )
        self.assertEqual(_live_audio_chunks(response), [b"first", b"second"])

    def test_live_audio_chunks_decodes_base64_part_data(self):
        encoded = base64.b64encode(b"\\x10\\x00voice").decode("ascii")
        response = SimpleNamespace(
            server_content=SimpleNamespace(
                model_turn=SimpleNamespace(
                    parts=[SimpleNamespace(inline_data=SimpleNamespace(mime_type="audio/pcm", data=encoded))]
                )
            ),
            data=None,
        )
        self.assertEqual(_live_audio_chunks(response), [b"\\x10\\x00voice"])

    def test_live_audio_chunks_falls_back_to_convenience_data(self):
        self.assertEqual(_live_audio_chunks(SimpleNamespace(data=b"fallback")), [b"fallback"])
        self.assertEqual(_live_audio_chunks(SimpleNamespace(data=None)), [])

    def test_error_text_includes_chained_causes(self):
        try:
            try:
                raise TimeoutError("timed out while closing connection")
            except TimeoutError as cause:
                raise ConnectionError("keepalive ping timeout") from cause
        except ConnectionError as error:
            text = _error_text(error).upper()
        self.assertIn("KEEPALIVE PING TIMEOUT", text)
        self.assertIn("TIMED OUT WHILE CLOSING CONNECTION", text)

    def test_quota_classifier_recognizes_status_and_message(self):
        class QuotaError(RuntimeError):
            status_code = 429

        self.assertTrue(_is_quota_error(QuotaError("request failed")))
        self.assertTrue(_is_quota_error(RuntimeError("RESOURCE_EXHAUSTED: quota")))
        self.assertFalse(_is_quota_error(RuntimeError("invalid argument")))

    def test_transient_disconnect_classifier_handles_nested_failures(self):
        grouped = ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [ConnectionError("1006 abnormal closure; no close frame received")],
        )
        self.assertTrue(_is_transient_live_disconnect(grouped))
        self.assertFalse(_is_transient_live_disconnect(RuntimeError("invalid argument")))

    def test_aborted_operation_classifier_requires_both_close_and_reason(self):
        self.assertTrue(_is_live_operation_aborted(RuntimeError("1008 policy violation: operation was aborted")))
        self.assertFalse(_is_live_operation_aborted(RuntimeError("1008 unrelated close")))


if __name__ == "__main__":
    unittest.main()
