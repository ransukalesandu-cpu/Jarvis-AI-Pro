"""Hybrid Phase 4: Live connection renewal (go_away) and the audio diagnostics.

The go_away scenarios run the real receive + playback code through the replay
harness (tests/live_replay.py) with a paced fake speaker.
"""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from live_replay import Step, run  # noqa: E402

from jarvis.core import audio_debug  # noqa: E402
from jarvis.core.live_audio import _duration_seconds  # noqa: E402


class DurationTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(_duration_seconds("12s"), 12.0)
        self.assertEqual(_duration_seconds("1.5s"), 1.5)
        self.assertEqual(_duration_seconds("PT30S"), 30.0)
        self.assertEqual(_duration_seconds(7), 7.0)
        self.assertEqual(_duration_seconds(None, default=10.0), 10.0)
        self.assertEqual(_duration_seconds("soon", default=4.0), 4.0)


class AudioDebugTests(unittest.TestCase):
    def tearDown(self):
        audio_debug.set_enabled(None)

    def test_off_by_default_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(audio_debug, "_LOG", Path(d) / "a.log"), \
                mock.patch.dict("os.environ", {audio_debug.ENV: "0"}):
            audio_debug.set_enabled(None)
            audio_debug.log("turn_complete", queued=3)
            self.assertFalse((Path(d) / "a.log").exists())

    def test_on_writes_event_lines(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(audio_debug, "_LOG", Path(d) / "a.log"), \
                mock.patch.dict("os.environ", {audio_debug.ENV: "1"}), \
                mock.patch("builtins.print"):
            audio_debug.set_enabled(None)
            self.assertTrue(audio_debug.enabled())
            audio_debug.log("barge_in_released", chunks=4, turn_complete=False)
            text = (Path(d) / "a.log").read_text(encoding="utf-8")
            self.assertIn("barge_in_released chunks=4 turn_complete=False", text)

    def test_never_raises(self):
        audio_debug.set_enabled(True)
        with mock.patch.object(audio_debug, "_LOG", Path("/nonexistent-dir/x/y.log")), \
                mock.patch("pathlib.Path.mkdir", side_effect=OSError("no")), \
                mock.patch("builtins.print"):
            audio_debug.log("speaker_write_failed", error="OSError")


class GoAwayRenewalTests(unittest.TestCase):
    def _run(self, steps):
        calls = []

        def fake_reconnect(self_, keep_context=True, reason=""):
            calls.append((time.monotonic(), keep_context, reason))
        with mock.patch("jarvis.main.JarvisLive.request_reconnect", fake_reconnect):
            result = run(steps)
        return result, calls

    def test_renewal_waits_until_the_answer_has_played(self):
        steps = [Step(input_text="tell me about the moon")]
        steps += [Step(audio_ms=100) for _ in range(5)]
        steps += [Step(go_away_s=30.0)]                         # warning mid-answer
        steps += [Step(delay=0.05, audio_ms=100) for _ in range(5)]
        steps += [Step(delay=0.05, turn_complete=True)]
        result, calls = self._run(steps)
        self.assertEqual(result.written_ms_by_marker.get(2), result.sent_ms_by_marker[2])
        self.assertEqual(len(calls), 1)
        _t, keep, reason = calls[0]
        self.assertTrue(keep)                                     # context kept
        self.assertIn("renewal", reason)
        last_write = max(t for t, _n, _m in result.write_log)
        self.assertGreaterEqual(calls[0][0], last_write)          # only after the last write

    def test_renewal_is_prompt_when_idle(self):
        steps = [Step(input_text="hi"), Step(audio_ms=100), Step(turn_complete=True),
                 Step(delay=0.8, go_away_s=30.0), Step(delay=0.5)]
        _result, calls = self._run(steps)
        self.assertEqual(len(calls), 1)


class RenewalIdleTests(unittest.TestCase):
    """The renewal waits for the speakers' tail and the prebuffered turn."""

    def _host(self, **state):
        import asyncio
        import threading
        from types import SimpleNamespace

        from jarvis import main
        host = main.JarvisLive.__new__(main.JarvisLive)
        session = SimpleNamespace()
        host.__dict__.update(dict(
            _shutdown_requested=False, session=session, audio_in_queue=asyncio.Queue(),
            _turn_done_event=asyncio.Event(), _is_speaking=False,
            _assistant_turn_pending=False, _tail_until=0.0,
            _speaking_lock=threading.Lock()))
        host.__dict__.update(state)
        return host, session

    def _renews_immediately(self, host, session):
        import asyncio
        calls = []
        host.request_reconnect = lambda **kw: calls.append(kw)

        async def go():
            task = asyncio.ensure_future(host._renew_session_when_idle(session, time.monotonic() + 5))
            await asyncio.sleep(0.25)
            task.cancel()
        asyncio.run(go())
        return bool(calls)

    def test_waits_for_the_echo_tail(self):
        host, session = self._host(_tail_until=time.monotonic() + 60)
        self.assertFalse(self._renews_immediately(host, session))

    def test_waits_while_a_completed_turn_is_still_buffered(self):
        host, session = self._host()
        host._turn_done_event.set()
        self.assertFalse(self._renews_immediately(host, session))

    def test_renews_when_really_idle(self):
        host, session = self._host()
        self.assertTrue(self._renews_immediately(host, session))


if __name__ == "__main__":
    unittest.main()
