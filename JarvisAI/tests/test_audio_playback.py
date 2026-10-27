"""Unit tests for output stream opening and fallback helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.audio_playback import (
    describe_output_route,
    open_output_stream,
    open_output_stream_with_fallback,
    stream_device_index,
)


class FakeStream:
    def __init__(self, device):
        self.device = device
        self.started = False

    def start(self):
        self.started = True


class FakeAudioBackend:
    def __init__(self, failing_devices=()):
        self.failing_devices = set(failing_devices)
        self.calls = []

    def RawOutputStream(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["device"] in self.failing_devices:
            raise RuntimeError(f"device {kwargs['device']} unavailable")
        return FakeStream(kwargs["device"])

    def query_devices(self, device, direction):
        return {"name": "Test speaker", "hostapi": 0}

    def query_hostapis(self):
        return [{"name": "FakeHost"}]


class AudioPlaybackSetupTests(unittest.TestCase):
    def test_opens_and_starts_selected_output(self):
        backend = FakeAudioBackend()
        stream = open_output_stream(backend, 4, 24_000, 1, 2_048)
        self.assertTrue(stream.started)
        self.assertEqual(backend.calls[0]["device"], 4)
        self.assertEqual(backend.calls[0]["dtype"], "int16")
        self.assertEqual(backend.calls[0]["samplerate"], 24_000)

    def test_selected_output_falls_back_to_default_once(self):
        backend = FakeAudioBackend(failing_devices={4})
        result = open_output_stream_with_fallback(
            audio_backend=backend,
            selected_device=4,
            sample_rate=24_000,
            channels=1,
            blocksize=2_048,
        )
        self.assertTrue(result.used_default)
        self.assertIsInstance(result.selected_device_error, RuntimeError)
        self.assertTrue(result.stream.started)
        self.assertEqual([call["device"] for call in backend.calls], [4, None])

    def test_default_output_failure_is_not_retried(self):
        backend = FakeAudioBackend(failing_devices={None})
        with self.assertRaisesRegex(RuntimeError, "device None unavailable"):
            open_output_stream_with_fallback(
                audio_backend=backend,
                selected_device=None,
                sample_rate=24_000,
                channels=1,
                blocksize=2_048,
            )
        self.assertEqual([call["device"] for call in backend.calls], [None])

    def test_missing_backend_produces_clear_error(self):
        with self.assertRaisesRegex(RuntimeError, "PortAudio missing"):
            open_output_stream(None, None, 24_000, 1, 2_048)

    def test_route_description_is_best_effort(self):
        self.assertEqual(
            describe_output_route(FakeAudioBackend(), 2),
            "Test speaker via FakeHost",
        )
        self.assertEqual(describe_output_route(None, 2), "2")

    def test_device_index_handles_tuple_or_missing_metadata(self):
        self.assertEqual(stream_device_index(MagicMock(device=(7, 8)), None), 8)
        self.assertEqual(stream_device_index(MagicMock(device=None), 5), 5)


if __name__ == "__main__":
    unittest.main()
