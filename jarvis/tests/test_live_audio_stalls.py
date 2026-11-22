"""Replay regressions for "JARVIS stops mid-sentence / stalls during playback".

Root causes reproduced here (real ``_receive_audio`` + ``run_audio_playback``,
paced fake speaker; see tests/live_replay.py):

1. With Voice ID on, every input-transcription chunk awaited a full speaker
   verification *inside* the Live receive loop. While it ran no server event
   was read, so the reply audio already in flight stopped reaching the speaker:
   audible gaps mid-answer, worst on a slow laptop.
2. Before a tool call the model often says a short "let me check". That audio
   (below the 300 ms prebuffer) and the last <50 ms slice were only released
   at ``turn_complete``, which arrives after the tool finishes — so the
   sentence froze, then resumed glued to the answer. Each tool wait was also
   counted as an underrun and grew the prebuffer (more latency every turn).
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from live_replay import Step, build_host, run  # noqa: E402


class _SlowAuthManager:
    """Stands in for security.get_auth_manager() with a slow Voice ID check."""

    def __init__(self, seconds: float, *, silence_after: bool = False):
        self.seconds = seconds
        self.silence_after = silence_after
        self.calls: list[tuple[float, float]] = []   # (start, end)
        self._silent = False
        self._lock = threading.Lock()

    def process_voice_authentication(self, _audio, sample_rate: int = 16000):
        start = time.monotonic()
        time.sleep(self.seconds)
        with self._lock:
            self.calls.append((start, time.monotonic()))
            if self.silence_after:
                self._silent = True
        return ("ok", "")

    def is_silent(self) -> bool:
        with self._lock:
            return self._silent

    def requires_owner_reauthentication(self) -> bool:
        return False

    # Anything else the receive path may ask for.
    def __getattr__(self, _name):
        return lambda *a, **k: False


@contextmanager
def voice_id_on(manager):
    with patch("jarvis.main.voice_id.is_enabled", return_value=True), \
         patch("jarvis.main.security.get_auth_manager", return_value=manager), \
         patch("jarvis.main.JarvisLive._queue_auth_state_broadcast", lambda self: None):
        yield


def _answer(ms_total: int, chunk_ms: int = 100, *, late_inputs: int = 0) -> list[Step]:
    steps: list[Step] = []
    n = ms_total // chunk_ms
    for i in range(n):
        steps.append(Step(delay=chunk_ms / 1000 * 0.9, audio_ms=chunk_ms, output_text="w "))
        if i < late_inputs:
            # Gemini keeps sending input-transcription chunks for a while after
            # the model has started answering.
            steps.append(Step(input_text=f"more{i}"))
    return steps


class VoiceAuthDoesNotBlockPlayback(unittest.TestCase):
    def test_slow_voice_id_does_not_create_gaps_mid_answer(self):
        manager = _SlowAuthManager(0.40)
        steps = [Step(input_text="tell me a story")]
        steps += _answer(2400, late_inputs=6)
        steps += [Step(delay=0.01, turn_complete=True)]
        with voice_id_on(manager):
            result = run(steps)
        self.assertEqual(result.written_ms_by_marker.get(2), result.sent_ms_by_marker[2])
        # 2.4 s of speech must take about 2.4 s to play. Before the fix the
        # receive loop sat in six 0.4 s checks and the answer took ~4 s, with
        # silence wherever the speaker ran dry.
        span = result.write_log[-1][0] - result.write_log[0][0]
        self.assertLess(span, 2.4 + 0.5, f"2.4 s answer took {span:.2f} s to play")
        # Checks were coalesced instead of queued once per transcript chunk.
        self.assertLess(len(manager.calls), 7)

    def test_reply_is_not_played_before_the_first_voice_check_finishes(self):
        # A stranger's request: the check silences JARVIS. Nothing of the reply
        # may reach the speaker while that first check is still running.
        manager = _SlowAuthManager(0.60, silence_after=True)
        steps = [Step(input_text="who lives here")]
        steps += _answer(800)
        steps += [Step(delay=0.01, turn_complete=True)]
        with voice_id_on(manager):
            result = run(steps)
        self.assertEqual(result.written_ms_by_marker.get(2, 0), 0)

    def test_tool_call_waits_for_the_running_voice_check(self):
        manager = _SlowAuthManager(0.50)
        steps = [
            Step(input_text="open my notes"),
            Step(delay=0.02, tool_call={"name": "no_such_tool_for_test", "args": {}}),
            Step(delay=1.0, audio_ms=200, output_text="done"),
            Step(delay=0.01, turn_complete=True),
        ]
        with voice_id_on(manager):
            result = run(steps)
        self.assertTrue(manager.calls)
        self.assertIn("tool_response", result.marks)
        self.assertGreaterEqual(result.marks["tool_response"], manager.calls[0][1])


class HeldAudioAcrossReconnect(unittest.IsolatedAsyncioTestCase):
    async def test_audio_held_for_voice_id_is_dropped_after_a_reconnect(self):
        host = build_host()
        host._auth_gated_pcm = None
        with patch("jarvis.main.security.get_auth_manager", return_value=_SlowAuthManager(0)):
            host._auth_gated_pcm = []
            host._auth_gated_turn_complete = False
            host._auth_gated_queue = host.audio_in_queue
            host._enqueue_reply_pcm([b"\x01\x00" * 1200])
            import asyncio
            host.audio_in_queue = asyncio.Queue()       # run() rebuilt the session
            host._release_auth_gated_audio()
        self.assertTrue(host.audio_in_queue.empty())
        self.assertIsNone(host._auth_gated_pcm)


class ToolCallFlushesSpokenPreamble(unittest.TestCase):
    def test_short_preamble_plays_before_the_tool_finishes(self):
        steps = [
            Step(input_text="what's the weather"),
            # 230 ms "let me check": below the 300 ms prebuffer, not 50 ms aligned.
            Step(delay=0.02, audio_ms=100, output_text="Let me"),
            Step(delay=0.09, audio_ms=100, output_text=" check"),
            Step(delay=0.09, audio_ms=30),
            Step(delay=0.01, tool_call={"name": "no_such_tool_for_test", "args": {}}),
            # The server answers only after the tool round trip.
            Step(delay=1.50, audio_ms=600, output_text="It is sunny."),
            Step(delay=0.01, turn_complete=True),
        ]
        result = run(steps)
        self.assertEqual(result.written_ms_by_marker.get(2), result.sent_ms_by_marker[2])
        said = result.marks["input:what's the weather"]
        post_tool_audio_at = said + 0.02 + 0.09 + 0.09 + 0.01 + 1.50
        preamble_writes = [t for t, _n, m in result.write_log if t < post_tool_audio_at]
        written_before = sum(n for t, n, _m in result.write_log if t < post_tool_audio_at)
        self.assertTrue(preamble_writes, "the preamble waited for the tool to finish")
        # All 230 ms, including the 30 ms tail, played before the answer arrived.
        self.assertGreaterEqual(written_before, int(24000 * 2 * 0.23))

    def test_tool_wait_is_not_counted_as_an_underrun(self):
        from jarvis.core import live_audio
        raised: list[int] = []
        real = live_audio._next_prebuffer_ms

        def spy(current, *, underrun=False, stable_turns=0):
            if underrun:
                raised.append(current)
            return real(current, underrun=underrun, stable_turns=stable_turns)

        steps = [Step(input_text="check my calendar")]
        steps += _answer(600)
        steps += [Step(delay=0.01, tool_call={"name": "no_such_tool_for_test", "args": {}}),
                  Step(delay=1.20, audio_ms=400, output_text="You are free."),
                  Step(delay=0.01, turn_complete=True)]
        with patch("jarvis.core.audio_playback._next_prebuffer_ms", side_effect=spy):
            result = run(steps)
        self.assertEqual(result.written_ms_by_marker.get(2), result.sent_ms_by_marker[2])
        self.assertEqual(raised, [], "a tool round trip grew the jitter buffer")


def tearDownModule():
    # Leave the shared replay host as other test modules expect it.
    host = build_host.__globals__["_HOST_CACHE"].get("host")
    if host is not None:
        for name in ("_voice_auth_task", "_auth_gated_pcm", "_auth_gated_queue"):
            host.__dict__.pop(name, None)


if __name__ == "__main__":
    unittest.main()
