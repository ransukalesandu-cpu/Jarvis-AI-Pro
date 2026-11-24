"""Opt-in voice latency trace (core/latency_trace.py): per-turn state machine, summary, sink, hook guards."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from jarvis.core import latency_trace as lt

JARVIS_DIR = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def trace():
    clock, seen = Clock(), []
    return lt.LatencyTrace(clock=clock, sink=seen.append), clock, seen


LOUD, QUIET = 0.5, 0.01


def test_flag_is_off_unless_set(monkeypatch):
    monkeypatch.delenv("JARVIS_LATENCY_TRACE", raising=False)
    assert lt._flag() is False
    for value in ("1", "true", "YES", " on "):
        monkeypatch.setenv("JARVIS_LATENCY_TRACE", value)
        assert lt._flag() is True
    monkeypatch.setenv("JARVIS_LATENCY_TRACE", "0")
    assert lt._flag() is False


def test_one_voice_turn_produces_one_record(trace):
    t, clock, seen = trace
    for step in range(10):                 # the owner speaks for one second
        clock.t = 100.0 + step * 0.1
        t.mic_frame(LOUD)
    speech_end = clock.t
    clock.t += 0.3
    t.mic_frame(QUIET)                     # room silence does not move speech end
    clock.t = speech_end + 0.6
    t.server_audio()
    clock.t = speech_end + 0.75
    t.device_write(0.085)
    clock.t += 0.05
    t.device_write(0.085)                  # later writes of the same reply are ignored

    assert len(seen) == 1
    rec = seen[0]
    assert rec["turn"] == 1
    assert rec["e2e_ms"] == pytest.approx(750.0)
    assert rec["server_ms"] == pytest.approx(600.0)
    assert rec["local_ms"] == pytest.approx(150.0)
    assert rec["out_latency_ms"] == pytest.approx(85.0)
    assert rec["audible_est_ms"] == pytest.approx(835.0)
    assert rec["session"]["n"] == 1


def test_reply_without_owner_speech_is_not_measured(trace):
    t, clock, seen = trace
    t.mic_frame(QUIET)                     # typed command or proactive remark: no voiced frame
    t.server_audio()
    clock.t += 0.2
    t.device_write()
    assert seen == []


def test_frames_during_the_reply_do_not_move_speech_end(trace):
    t, clock, seen = trace
    t.mic_frame(LOUD)
    clock.t += 0.5
    t.server_audio()
    clock.t += 0.1
    t.mic_frame(LOUD)                      # a cough while the reply is buffering
    clock.t += 0.1
    t.device_write()
    assert seen[0]["e2e_ms"] == pytest.approx(700.0)


def test_interrupted_reply_goes_stale_and_the_next_turn_is_measured(trace):
    t, clock, seen = trace
    t.mic_frame(LOUD)
    clock.t += 0.5
    t.server_audio()                       # reply arrives but is interrupted: never written
    clock.t += lt.STALE_REPLY_S + 0.1
    t.mic_frame(LOUD)                      # next question re-arms the trace
    start = clock.t
    clock.t = start + 0.4
    t.server_audio()
    clock.t = start + 0.5
    t.device_write()
    assert len(seen) == 1
    assert seen[0]["e2e_ms"] == pytest.approx(500.0)


def test_implausibly_late_reply_is_discarded(trace):
    t, clock, seen = trace
    t.mic_frame(LOUD)
    clock.t += lt.MAX_PLAUSIBLE_S + 1
    t.server_audio()
    clock.t += 0.1
    t.device_write()
    assert seen == []
    assert t.summary()["discarded"] == 1


def test_summary_percentiles():
    values = [float(v) for v in range(100, 1001, 100)]        # 100 .. 1000
    s = lt.summarize(values)
    assert (s["n"], s["p50_ms"], s["p90_ms"], s["max_ms"]) == (10, 500.0, 900.0, 1000.0)
    assert s["mean_ms"] == pytest.approx(550.0)
    assert lt.summarize([])["n"] == 0
    assert lt.percentile([], 50) is None
    assert lt.percentile([42.0], 90) == 42.0


def test_background_sink_prints_and_appends_jsonl(tmp_path, capsys):
    sink = lt._BackgroundSink(log_dir=lambda: tmp_path)
    t = lt.LatencyTrace(clock=Clock(), sink=sink)
    t.mic_frame(LOUD)
    t._clock.t += 0.6
    t.server_audio()
    t._clock.t += 0.2
    t.device_write(0.05)
    deadline = time.monotonic() + 5
    files = []
    while time.monotonic() < deadline and not files:
        files = list(tmp_path.glob("latency-*.jsonl"))
        time.sleep(0.02)
    assert files, "the background sink never wrote its JSONL file"
    deadline = time.monotonic() + 5
    rows = []
    while time.monotonic() < deadline and not rows:
        rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line]
        time.sleep(0.02)
    assert rows[0]["e2e_ms"] == pytest.approx(800.0)
    assert set(rows[0]) == {"ts", "turn", "e2e_ms", "server_ms", "local_ms", "out_latency_ms", "audible_est_ms"}
    assert "speech end -> audio written 800 ms" in capsys.readouterr().out


def test_record_holds_timings_only(trace):
    t, clock, seen = trace
    t.mic_frame(LOUD)
    clock.t += 0.3
    t.server_audio()
    clock.t += 0.1
    t.device_write()
    assert all(isinstance(v, (int, float)) for k, v in seen[0].items() if k != "session")


def test_trace_through_the_real_receive_and_playback_pipeline(monkeypatch):
    """Hooks 2 and 3 fire from the real JarvisLive._receive_audio and run_audio_playback.

    tests/live_replay.py scripts the Gemini server and a paced fake speaker; the mic hook is stood in
    for by marking speech end just before the scenario starts.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from live_replay import Step, run

    seen = []
    trace = lt.LatencyTrace(sink=seen.append)
    monkeypatch.setattr(lt, "ACTIVE", True)
    monkeypatch.setattr(lt, "TRACE", trace)
    trace.mic_frame(LOUD)                      # the owner just stopped speaking
    run([Step(input_text="what time is it"), Step(delay=0.25, audio_ms=400),
         Step(delay=0.05, audio_ms=400), Step(delay=0.05, turn_complete=True)])

    assert len(seen) == 1, "expected one record for one voice turn"
    rec = seen[0]
    assert rec["server_ms"] >= 200             # the scripted server waited 250 ms before replying
    assert rec["local_ms"] >= 0
    assert rec["e2e_ms"] == pytest.approx(rec["server_ms"] + rec["local_ms"], abs=0.2)


@pytest.mark.parametrize("path,call", [
    ("main.py", "latency_trace.mic_frame("),
    ("main.py", "latency_trace.server_audio("),
    ("core/audio_playback.py", "latency_trace.device_write("),
])
def test_live_audio_hooks_are_guarded(path, call):
    """With the trace off, the audio path must not even compute the mic level for it."""
    lines = (JARVIS_DIR / path).read_text(encoding="utf-8").splitlines()
    hits = [i for i, line in enumerate(lines) if call in line]
    assert len(hits) == 1, f"expected exactly one {call} in {path}"
    previous = lines[hits[0] - 1].strip()
    assert re.match(r"if latency_trace\.ACTIVE:", previous), f"{call} in {path} is not behind the ACTIVE guard"
