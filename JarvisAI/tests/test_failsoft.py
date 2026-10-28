"""Tests for the fail-soft recorder and the level helper it helped uncover.

`core/failsoft.py` exists so that "this optional step failed, carry on" stops
meaning "and nobody will ever know". These tests pin the two properties that
make it useful: it records what it is told, and it can never make things worse.
"""

from __future__ import annotations

import threading
import unittest

from core import failsoft
from core.audio_playback import viseme_peak_level


class FailSoftRecordingTests(unittest.TestCase):
    def setUp(self):
        failsoft.reset()

    def tearDown(self):
        failsoft.reset()

    def test_suppress_records_the_exception_it_is_handling(self):
        try:
            raise OSError("speaker unplugged")
        except OSError:
            failsoft.suppress("core.test:probe_device")

        rows = failsoft.summary()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["feature"], "core.test:probe_device")
        self.assertEqual(rows[0]["exception_type"], "OSError")
        self.assertEqual(rows[0]["message"], "speaker unplugged")
        self.assertEqual(rows[0]["count"], 1)
        self.assertEqual(failsoft.count(), 1)

    def test_repeats_are_counted_not_duplicated(self):
        for _ in range(5):
            try:
                raise RuntimeError("no tracker")
            except RuntimeError:
                failsoft.suppress("plugins.quiz:load_state")

        rows = failsoft.summary()
        self.assertEqual(len(rows), 1, "identical failures must collapse into one row")
        self.assertEqual(rows[0]["count"], 5)
        self.assertEqual(failsoft.count(), 5)

    def test_same_feature_with_different_errors_is_reported_separately(self):
        for exc in (ValueError("a"), KeyError("b")):
            try:
                raise exc
            except Exception:
                failsoft.suppress("core.test:parse")

        self.assertEqual(len(failsoft.summary()), 2)

    def test_summary_is_ordered_by_frequency(self):
        for _ in range(3):
            try:
                raise RuntimeError("frequent")
            except RuntimeError:
                failsoft.suppress("core:a")
        try:
            raise RuntimeError("rare")
        except RuntimeError:
            failsoft.suppress("core:b")

        features = [row["feature"] for row in failsoft.summary()]
        self.assertEqual(features, ["core:a", "core:b"])

    def test_calling_it_outside_a_handler_does_not_raise(self):
        failsoft.suppress("core.test:misuse")
        self.assertGreaterEqual(failsoft.count(), 1)

    def test_long_messages_are_truncated(self):
        try:
            raise RuntimeError("x" * 5000)
        except RuntimeError:
            failsoft.suppress("core.test:huge")

        message = failsoft.summary()[0]["message"]
        self.assertLessEqual(len(message), 300)
        self.assertTrue(message.endswith("..."))

    def test_reset_clears_everything(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            failsoft.suppress("core.test:boom")
        failsoft.reset()
        self.assertEqual(failsoft.summary(), [])
        self.assertEqual(failsoft.count(), 0)

    def test_report_is_empty_when_nothing_was_suppressed(self):
        self.assertEqual(failsoft.report(), "")

    def test_report_names_the_feature_and_the_count(self):
        for _ in range(2):
            try:
                raise ValueError("bad frame")
            except ValueError:
                failsoft.suppress("core.audio:frames")
        report = failsoft.report()
        self.assertIn("core.audio:frames", report)
        self.assertIn("×2", report)
        self.assertIn("bad frame", report)

    def test_recording_is_thread_safe(self):
        """Audio callbacks swallow errors from several threads at once."""
        def worker():
            for _ in range(50):
                try:
                    raise RuntimeError("callback")
                except RuntimeError:
                    failsoft.suppress("core.audio:callback")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failsoft.count(), 200)
        self.assertEqual(len(failsoft.summary()), 1)

    def test_buffer_stays_bounded(self):
        """A failure inside a 20 Hz callback must not grow memory forever."""
        for index in range(failsoft._MAX_EVENTS + 75):
            try:
                raise RuntimeError(f"distinct failure {index}")
            except RuntimeError:
                failsoft.suppress("core.test:flood")

        self.assertEqual(len(failsoft.summary()), failsoft._MAX_EVENTS)


class VisemePeakLevelTests(unittest.TestCase):
    """The helper that keeps barge-in alive when the mouth has nothing to draw."""

    def test_empty_schedule_returns_none_instead_of_raising(self):
        # `max()` on this sequence raises ValueError; the playback loop used to
        # let that abort the echo update, so the guard never learned what
        # JARVIS was playing.
        self.assertIsNone(viseme_peak_level([]))

    def test_returns_the_loudest_frame(self):
        self.assertEqual(viseme_peak_level([(0.1, 0.2, 0.3), (0.8, 0.1, 0.1)]), 0.8)

    def test_a_malformed_frame_does_not_raise(self):
        self.assertIsNone(viseme_peak_level([object()]))
        self.assertEqual(viseme_peak_level([(0.4,), object()]), 0.4)

    def test_silence_is_zero_not_none(self):
        # Zero is a real level: it means "quiet", not "unknown".
        self.assertEqual(viseme_peak_level([(0.0, 0.0, 0.0)]), 0.0)
