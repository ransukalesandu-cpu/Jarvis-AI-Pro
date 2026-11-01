"""Tests for the microphone stream opening/fallback boundary."""

from __future__ import annotations

import unittest

from core.audio_capture import (
    open_input_stream_with_fallback,
    resample_input_audio,
    take_fixed_pcm_frames,
)


class FakeStream:
    def __init__(self, kwargs):
        self.kwargs = kwargs


class FakeAudioBackend:
    def __init__(self, failing_devices=()):
        self.failing_devices = set(failing_devices)
        self.calls = []

    def InputStream(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["device"] in self.failing_devices:
            raise RuntimeError(f"device {kwargs['device']} unavailable")
        return FakeStream(kwargs)


class AudioCaptureSignalTests(unittest.TestCase):
    def test_resampling_preserves_rate_matched_input(self):
        import numpy as np

        source = np.array([0, 100, -100], dtype=np.int16)
        self.assertIs(resample_input_audio(source, 16_000, 16_000), source)

    def test_resampling_changes_sample_count_and_preserves_channel_shape(self):
        import numpy as np

        source = np.array([[0], [1000], [2000], [3000]], dtype=np.int16)
        result = resample_input_audio(source, 8_000, 16_000)
        self.assertEqual(result.shape, (8, 1))
        self.assertEqual(result.dtype, np.int16)
        self.assertEqual(int(result[0, 0]), 0)
        self.assertEqual(int(result[-1, 0]), 3000)

    def test_resampling_clips_to_int16_range(self):
        import numpy as np

        source = np.array([-40_000, 40_000], dtype=np.int32)
        result = resample_input_audio(source, 8_000, 8_000)
        self.assertIs(result, source)
        converted = resample_input_audio(source, 8_000, 16_000)
        self.assertLessEqual(int(converted.max()), 32767)
        self.assertGreaterEqual(int(converted.min()), -32768)

    def test_fixed_pcm_frames_consumes_only_complete_frames(self):
        buffer = bytearray(b"abcdefghij")
        frames = take_fixed_pcm_frames(buffer, 4)
        self.assertEqual(frames, [b"abcd", b"efgh"])
        self.assertEqual(buffer, bytearray(b"ij"))

    def test_fixed_pcm_frames_can_continue_after_more_bytes_arrive(self):
        buffer = bytearray(b"abc")
        self.assertEqual(take_fixed_pcm_frames(buffer, 4), [])
        buffer.extend(b"d")
        self.assertEqual(take_fixed_pcm_frames(buffer, 4), [b"abcd"])
        self.assertEqual(buffer, bytearray())

    def test_fixed_pcm_frames_rejects_non_positive_frame_size(self):
        with self.assertRaises(ValueError):
            take_fixed_pcm_frames(bytearray(b"data"), 0)


class AudioCaptureTests(unittest.TestCase):
    def setUp(self):
        self.callback = lambda *args: None

    def test_opens_selected_microphone_without_fallback(self):
        backend = FakeAudioBackend()
        result = open_input_stream_with_fallback(
            audio_backend=backend,
            selected_device=7,
            sample_rate=16_000,
            channels=1,
            blocksize=1_024,
            callback=self.callback,
        )

        self.assertFalse(result.used_default)
        self.assertIsNone(result.selected_device_error)
        self.assertEqual(result.stream.kwargs["device"], 7)
        self.assertIs(result.stream.kwargs["callback"], self.callback)
        self.assertEqual([call["device"] for call in backend.calls], [7])

    def test_selected_device_failure_retries_system_default_once(self):
        backend = FakeAudioBackend(failing_devices={7})
        result = open_input_stream_with_fallback(
            audio_backend=backend,
            selected_device=7,
            sample_rate=16_000,
            channels=1,
            blocksize=1_024,
            callback=self.callback,
        )

        self.assertTrue(result.used_default)
        self.assertIsInstance(result.selected_device_error, RuntimeError)
        self.assertIn("device 7 unavailable", str(result.selected_device_error))
        self.assertIsNone(result.stream.kwargs["device"])
        self.assertEqual([call["device"] for call in backend.calls], [7, None])

    def test_system_default_failure_is_not_retried(self):
        backend = FakeAudioBackend(failing_devices={None})
        with self.assertRaisesRegex(RuntimeError, "device None unavailable"):
            open_input_stream_with_fallback(
                audio_backend=backend,
                selected_device=None,
                sample_rate=16_000,
                channels=1,
                blocksize=1_024,
                callback=self.callback,
            )
        self.assertEqual([call["device"] for call in backend.calls], [None])

    def test_missing_backend_reports_portaudio_failure(self):
        with self.assertRaisesRegex(RuntimeError, "PortAudio missing"):
            open_input_stream_with_fallback(
                audio_backend=None,
                selected_device=None,
                sample_rate=16_000,
                channels=1,
                blocksize=1_024,
                callback=self.callback,
            )


if __name__ == "__main__":
    unittest.main()
