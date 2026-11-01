"""Tests for chunk-aligned buffering of Gemini Live PCM output."""
from __future__ import annotations

import unittest

from main import (
    _MIN_LIVE_AUDIO_FRAME_BYTES,
    _MIN_PREBUFFER_BYTES,
    _OUTPUT_BLOCKSIZE,
    _next_prebuffer_ms,
    _PLAYBACK_SLICE_BYTES,
    _error_text,
    _is_live_operation_aborted,
    _is_transient_live_disconnect,
    _output_write_is_unpaced,
    _take_playback_pcm,
)
from core.live_audio import (
    _audio_event_timing,
    _resumable_session_handle,
    _turn_output_diagnostic,
)


class LivePcmBufferingTests(unittest.TestCase):
    def test_audio_event_timing_reports_only_significant_arrival_gaps(self):
        duration, gap = _audio_event_timing(4800, 10.50, 10.0, 0.10)
        self.assertAlmostEqual(duration, 0.10)
        self.assertAlmostEqual(gap, 0.50)

        duration, gap = _audio_event_timing(4800, 10.15, 10.0, 0.10)
        self.assertAlmostEqual(duration, 0.10)
        self.assertIsNone(gap)

    def test_audio_event_timing_handles_first_event_and_invalid_input(self):
        duration, gap = _audio_event_timing(4800, 10.0, None, 0.0)
        self.assertAlmostEqual(duration, 0.10)
        self.assertIsNone(gap)
        self.assertEqual(_audio_event_timing("bad", 10.0, 9.0, 0.1), (0.0, None))

    def test_session_resumption_helper_accepts_only_resumable_handles(self):
        class Update:
            def __init__(self, resumable, handle):
                self.resumable = resumable
                self.new_handle = handle

        class Response:
            def __init__(self, update):
                self.session_resumption_update = update

        self.assertEqual(
            _resumable_session_handle(Response(Update(True, "resume-token"))),
            "resume-token",
        )
        self.assertIsNone(
            _resumable_session_handle(Response(Update(False, "unsafe-token")))
        )
        self.assertIsNone(
            _resumable_session_handle(Response(Update(True, "")))
        )
        self.assertIsNone(_resumable_session_handle(object()))

    def test_turn_output_diagnostic_reports_text_and_partial_audio(self):
        message = _turn_output_diagnostic(
            True, 960, output_audio_checkpointed=False,
            interrupted=False, min_frame_bytes=480,
        )
        self.assertEqual(
            message,
            "[AudioTrace 3→4/AUDIO] Assistant text arrived, but only "
            "960 PCM byte(s) arrived this turn; no complete 10 ms frame "
            "(480 bytes) reached playback. Check Live model/audio output.",
        )

    def test_turn_output_diagnostic_reports_text_without_audio(self):
        self.assertEqual(
            _turn_output_diagnostic(
                True, 0, output_audio_checkpointed=False,
                interrupted=False, min_frame_bytes=480,
            ),
            "[AudioTrace 3→4/AUDIO] Assistant text arrived but Gemini "
            "returned no audio payload for this turn.",
        )

    def test_turn_output_diagnostic_reports_audio_without_text(self):
        self.assertEqual(
            _turn_output_diagnostic(
                False, 240, output_audio_checkpointed=False,
                interrupted=False, min_frame_bytes=480,
            ),
            "[AudioTrace 3→4/AUDIO] Only 240 PCM byte(s) arrived without "
            "a playable frame or assistant text.",
        )

    def test_turn_output_diagnostic_reports_empty_turn(self):
        self.assertEqual(
            _turn_output_diagnostic(
                False, 0, output_audio_checkpointed=False,
                interrupted=False, min_frame_bytes=480,
            ),
            "[AudioTrace 3/LIVE] Turn completed without assistant "
            "transcription or audio payload.",
        )

    def test_turn_output_diagnostic_is_suppressed_after_audio_or_interrupt(self):
        for kwargs in (
            {"output_audio_checkpointed": True, "interrupted": False},
            {"output_audio_checkpointed": False, "interrupted": True},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertIsNone(
                    _turn_output_diagnostic(
                        True, 960, min_frame_bytes=480, **kwargs
                    )
                )

    def test_live_receive_diagnostics_reset_turn_without_resetting_event_count(self):
        from core.live_audio import LiveReceiveDiagnostics

        diagnostics = LiveReceiveDiagnostics()
        diagnostics.live_events_received = 4
        diagnostics.input_checkpoint_logged = True
        diagnostics.output_text_checkpoint_logged = True
        diagnostics.output_audio_checkpoint_logged = True
        diagnostics.short_audio_fragment_logged = True
        diagnostics.output_audio_bytes_seen = 9600
        diagnostics.last_audio_event_at = 12.5
        diagnostics.last_audio_event_duration = 0.2

        diagnostics.reset_turn()
        self.assertEqual(diagnostics.live_events_received, 4)
        self.assertFalse(diagnostics.input_checkpoint_logged)
        self.assertFalse(diagnostics.output_text_checkpoint_logged)
        self.assertFalse(diagnostics.output_audio_checkpoint_logged)
        self.assertFalse(diagnostics.short_audio_fragment_logged)
        self.assertEqual(diagnostics.output_audio_bytes_seen, 0)
        self.assertEqual(diagnostics.last_audio_event_at, 12.5)

        diagnostics.reset_audio_timing()
        self.assertIsNone(diagnostics.last_audio_event_at)
        self.assertEqual(diagnostics.last_audio_event_duration, 0.0)

    def test_live_receive_diagnostics_accumulates_output_audio_bytes(self):
        from core.live_audio import LiveReceiveDiagnostics

        diagnostics = LiveReceiveDiagnostics()
        self.assertEqual(diagnostics.record_output_audio_bytes(480), 480)
        self.assertEqual(diagnostics.record_output_audio_bytes(960), 1440)
        self.assertEqual(diagnostics.record_output_audio_bytes(0), 1440)
        diagnostics.reset_turn()
        self.assertEqual(diagnostics.output_audio_bytes_seen, 0)

    def test_live_receive_diagnostics_turn_output_snapshot(self):
        from core.live_audio import LiveReceiveDiagnostics

        diagnostics = LiveReceiveDiagnostics()
        self.assertEqual(diagnostics.turn_output_snapshot(), (False, 0))
        diagnostics.claim_checkpoint("output_text")
        diagnostics.record_output_audio_bytes(960)
        self.assertEqual(diagnostics.turn_output_snapshot(), (True, 960))
        diagnostics.reset_turn()
        self.assertEqual(diagnostics.turn_output_snapshot(), (False, 0))

    def test_live_receive_diagnostics_counts_events_and_identifies_first(self):
        from core.live_audio import LiveReceiveDiagnostics

        diagnostics = LiveReceiveDiagnostics()
        self.assertTrue(diagnostics.record_live_event())
        self.assertEqual(diagnostics.live_events_received, 1)
        self.assertFalse(diagnostics.record_live_event())
        self.assertEqual(diagnostics.live_events_received, 2)

    def test_live_receive_diagnostics_claims_each_checkpoint_once_per_turn(self):
        from core.live_audio import LiveReceiveDiagnostics

        diagnostics = LiveReceiveDiagnostics()
        self.assertTrue(diagnostics.claim_checkpoint("input"))
        self.assertFalse(diagnostics.claim_checkpoint("input"))
        self.assertTrue(diagnostics.claim_checkpoint("output_text"))
        self.assertTrue(diagnostics.claim_checkpoint("output_audio"))
        self.assertTrue(diagnostics.claim_checkpoint("short_audio_fragment"))
        self.assertFalse(diagnostics.claim_checkpoint("unknown"))
        self.assertFalse(diagnostics.checkpoint_claimed("unknown"))
        self.assertTrue(diagnostics.checkpoint_claimed("input"))
        self.assertFalse(diagnostics.checkpoint_claimed("output_audio"))
        diagnostics.reset_turn()
        self.assertTrue(diagnostics.claim_checkpoint("input"))
        self.assertTrue(diagnostics.claim_checkpoint("output_audio"))

    def test_live_receive_diagnostics_records_audio_event_timing(self):
        from core.live_audio import LiveReceiveDiagnostics

        diagnostics = LiveReceiveDiagnostics()
        duration, gap, previous_duration = diagnostics.record_audio_event(4800, 10.0)
        self.assertAlmostEqual(duration, 0.10)
        self.assertIsNone(gap)
        self.assertEqual(previous_duration, 0.0)
        self.assertEqual(diagnostics.last_audio_event_at, 10.0)

        duration, gap, previous_duration = diagnostics.record_audio_event(4800, 10.5)
        self.assertAlmostEqual(duration, 0.10)
        self.assertAlmostEqual(gap, 0.40)
        self.assertAlmostEqual(previous_duration, 0.10)
        self.assertEqual(diagnostics.last_audio_event_at, 10.5)
        self.assertAlmostEqual(diagnostics.last_audio_event_duration, 0.10)

    def test_live_playback_prebuffer_and_output_blocksize(self):
        # 24 kHz * mono * int16 * 0.3 seconds = 14,400 bytes.
        self.assertEqual(_MIN_PREBUFFER_BYTES, 14_400)
        self.assertEqual(_OUTPUT_BLOCKSIZE, 2048)

    def test_adaptive_prebuffer_grows_after_underrun_and_shrinks_after_stability(self):
        self.assertEqual(_next_prebuffer_ms(300, underrun=True), 350)
        self.assertEqual(_next_prebuffer_ms(600, underrun=True), 600)
        self.assertEqual(_next_prebuffer_ms(150, stable_turns=3), 150)
        self.assertEqual(_next_prebuffer_ms(400, stable_turns=3), 375)
        self.assertEqual(_next_prebuffer_ms(400, stable_turns=2), 400)
        self.assertEqual(_next_prebuffer_ms(900), 600)

    def test_live_abort_classifier_recognizes_policy_close_1008(self):
        self.assertTrue(
            _is_live_operation_aborted(
                RuntimeError("1008 None. The operation was aborted.")
            )
        )
        self.assertFalse(
            _is_live_operation_aborted(
                RuntimeError("1008 None. unrelated failure")
            )
        )

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
