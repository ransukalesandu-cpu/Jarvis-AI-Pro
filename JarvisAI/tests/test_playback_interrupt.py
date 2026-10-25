import threading
import unittest
from unittest.mock import Mock

from core.playback_interrupt import interrupt_playback


class PlaybackInterruptTests(unittest.TestCase):
    """Verify playback interrupts signal the worker and stop device output."""

    def test_sets_event_and_aborts_active_output(self):
        event = threading.Event()
        stream = Mock()
        self.assertTrue(interrupt_playback(event, stream))
        self.assertTrue(event.is_set())
        stream.abort.assert_called_once_with()

    def test_sets_event_even_if_device_abort_fails(self):
        event = threading.Event()
        stream = Mock()
        stream.abort.side_effect = OSError("device unavailable")
        report = Mock()

        self.assertFalse(interrupt_playback(event, stream, on_error=report))
        self.assertTrue(event.is_set())
        report.assert_called_once_with("OSError")

    def test_sets_event_when_no_output_stream_exists(self):
        event = threading.Event()
        self.assertTrue(interrupt_playback(event))
        self.assertTrue(event.is_set())


if __name__ == "__main__":
    unittest.main()
