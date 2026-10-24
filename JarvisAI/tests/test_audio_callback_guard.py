"""Offline tests for resilient audio callback handling."""
from __future__ import annotations

import unittest
from unittest.mock import Mock

from core.audio_callback_guard import guarded_audio_callback


class AudioCallbackGuardTests(unittest.TestCase):
    def test_successful_callback_returns_true(self):
        callback = Mock()
        self.assertTrue(guarded_audio_callback("test:success", callback, 1, value="x"))
        callback.assert_called_once_with(1, value="x")

    def test_callback_exception_is_swallowed_and_reported(self):
        reporter = Mock()
        callback = Mock(side_effect=RuntimeError("mic callback failed"))
        result = guarded_audio_callback(
            "test:callback-error-unique",
            callback,
            on_error=reporter,
            cooldown_seconds=30,
        )
        self.assertFalse(result)
        reporter.assert_called_once()
        self.assertIsInstance(reporter.call_args.args[0], RuntimeError)
        self.assertEqual(reporter.call_args.args[1], "test:callback-error-unique")

    def test_repeated_failure_is_rate_limited(self):
        reporter = Mock()
        callback = Mock(side_effect=ValueError("detector unavailable"))
        operation = "test:rate-limit-unique"
        self.assertFalse(guarded_audio_callback(operation, callback, on_error=reporter))
        self.assertFalse(guarded_audio_callback(operation, callback, on_error=reporter))
        self.assertEqual(callback.call_count, 2)
        reporter.assert_called_once()

    def test_diagnostic_failure_does_not_escape(self):
        reporter = Mock(side_effect=OSError("log disk unavailable"))
        callback = Mock(side_effect=RuntimeError("callback failed"))
        self.assertFalse(
            guarded_audio_callback(
                "test:reporter-failure-unique", callback, on_error=reporter
            )
        )


if __name__ == "__main__":
    unittest.main()
