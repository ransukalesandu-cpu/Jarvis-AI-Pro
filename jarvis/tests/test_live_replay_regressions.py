"""Replay regressions for the Live receive -> playback pipeline.

Each test replays a fixture from tests/fixtures/live_replay through the real
``JarvisLive._receive_audio`` and ``run_audio_playback`` with a paced fake
speaker (see tests/live_replay.py). They run in real time, so the fixtures are
kept to a few seconds of audio. Set ``JARVIS_SLOW_TESTS=1`` to also run the
60-second answer from the acceptance criteria.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from live_replay import Step, run, steps_from_fixture  # noqa: E402

# Audio already inside the playback worker's private buffer (at most one
# 100 ms batch plus one 50 ms slice) is lost when playback pauses.
PAUSE_LOSS_MS = 200


class LiveReplayRegressionTests(unittest.TestCase):
    def test_injected_turn_after_explicit_stop_is_not_silenced(self):
        # Root cause of "JARVIS never finishes the answer": the discard gate
        # opened by an interruption stayed open past turn_complete when the
        # interrupted turn had no user transcript, so the next injected turn
        # was thrown away.
        result = run(steps_from_fixture("explicit_stop_then_injected_turn.json"))
        self.assertLess(result.written_ms_by_marker.get(2, 0), 1000)
        self.assertEqual(result.written_ms_by_marker.get(3), result.sent_ms_by_marker[3])

    def test_false_barge_in_resumes_the_answer(self):
        result = run(steps_from_fixture("false_bargein_resumes.json"))
        self.assertGreaterEqual(
            result.written_ms_by_marker.get(2, 0),
            result.sent_ms_by_marker[2] - PAUSE_LOSS_MS,
        )
        self.assertEqual(result.written_ms_by_marker.get(3), result.sent_ms_by_marker[3])

    def test_confirmed_barge_in_discards_held_audio_and_answers_next_question(self):
        result = run(steps_from_fixture("real_bargein_discards.json"))
        # Only what played before the pause is heard of the old answer.
        self.assertLess(result.written_ms_by_marker.get(2, 0), 1000)
        self.assertEqual(result.written_ms_by_marker.get(3), result.sent_ms_by_marker[3])

    def test_server_interruption_silences_within_300_ms(self):
        result = run(steps_from_fixture("server_interrupted_mid_answer.json"))
        interrupted_at = result.marks["server_interrupted"]
        # Markers: each user transcript starts a new turn (first answer = 2).
        old_writes = [t for t, _n, m in result.write_log if m - 1 == 2]
        self.assertTrue(old_writes, "the first answer should have started playing")
        # A write is logged when it completes; anything finishing more than
        # 300 ms after the interruption would have been audible.
        self.assertLessEqual(max(old_writes) - interrupted_at, 0.30)
        self.assertEqual(result.written_ms_by_marker.get(3), result.sent_ms_by_marker[3])

    def test_long_answer_with_server_gap_plays_every_byte(self):
        result = run(steps_from_fixture("long_answer_with_server_gap.json"))
        self.assertEqual(result.written_ms_by_marker.get(2), result.sent_ms_by_marker[2])

    @unittest.skipUnless(os.environ.get("JARVIS_SLOW_TESTS"), "set JARVIS_SLOW_TESTS=1")
    def test_sixty_second_answer_plays_to_the_end(self):
        steps = [Step(input_text="explain something at length")]
        steps += [Step(delay=0.035, audio_ms=40, output_text="word ") for _ in range(1500)]
        steps += [Step(delay=0.01, turn_complete=True)]
        result = run(steps, timeout=180)
        self.assertEqual(result.written_ms_by_marker.get(2), 60000)
        self.assertLess(result.max_write_gap_ms, 250)


if __name__ == "__main__":
    unittest.main()
