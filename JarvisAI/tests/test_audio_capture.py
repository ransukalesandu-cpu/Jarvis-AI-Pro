"""Tests for the microphone stream opening/fallback boundary."""

from __future__ import annotations

import unittest

from core.audio_capture import open_input_stream_with_fallback


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
