"""Opt-in voice latency trace: from the end of the owner's speech to JARVIS's reply reaching the speakers.

Off unless ``JARVIS_LATENCY_TRACE=1``. When off, each hook is one attribute read, so the live audio path
pays nothing. When on, every voice turn produces one record with three timestamps:

* **speech end**   the last microphone frame sent to Gemini that was louder than room noise
                   (``mic_frame``, called from the mic callback's send branch);
* **server audio** the first reply PCM of the turn received from Gemini Live (``server_audio``);
* **written**      the first reply PCM of the turn handed to the output device (``device_write``).

``speech end -> written`` is the number the +50 ms budget of the production-architecture plan is
judged on. The device's own output buffer (reported by PortAudio) is added separately as
``audible_est_ms``. The server share includes Gemini's end-of-speech detection, the network and
generation, so it is only meaningful as a before/after comparison on the same machine and connection.

Privacy: a record holds timings only (no audio, no text, no device names). It is printed and appended
to ``<user data>/latency/latency-YYYY-MM-DD.jsonl``; nothing leaves the machine. Printing and file
writes happen on a background thread so measuring never delays the audio being measured.

Measure in a quiet room: room noise above ``VOICE_LEVEL`` keeps moving "speech end" forward.
"""
from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

#: 0..1 mic level (core.live_audio._pcm_level) above which a frame counts as the owner speaking.
VOICE_LEVEL = 0.08
#: A reply that starts later than this after the last voiced frame is not an answer to it
#: (for example a proactive remark after a text-only turn); it is counted as discarded.
MAX_PLAUSIBLE_S = 15.0
#: Reply audio that never reached the device (interrupted turn) stops blocking the next turn after this.
STALE_REPLY_S = 3.0
#: Records kept in memory for the session summary.
MAX_RECORDS = 500


def _flag() -> bool:
    return os.environ.get("JARVIS_LATENCY_TRACE", "").strip().lower() in {"1", "true", "yes", "on"}


#: Read once at import. Hooks check this before doing any work.
ACTIVE = _flag()


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (no numpy needed). None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(pct / 100.0 * len(ordered))))
    return ordered[rank - 1]


def summarize(e2e_ms: list[float]) -> dict:
    """n, p50, p90, mean and max of speech-end -> written latencies, in ms."""
    if not e2e_ms:
        return {"n": 0, "p50_ms": None, "p90_ms": None, "mean_ms": None, "max_ms": None}
    return {
        "n": len(e2e_ms),
        "p50_ms": round(percentile(e2e_ms, 50), 1),
        "p90_ms": round(percentile(e2e_ms, 90), 1),
        "mean_ms": round(sum(e2e_ms) / len(e2e_ms), 1),
        "max_ms": round(max(e2e_ms), 1),
    }


def default_log_dir() -> Path:
    from jarvis.core.user_data import user_data_dir
    return user_data_dir() / "latency"


class LatencyTrace:
    """Per-turn state machine: idle -> listening (owner spoke) -> replying (server audio) -> idle (written).

    The three hooks run on three different threads (PortAudio callback, Live receive loop, playback
    worker). Each one only assigns floats or compares them under a small lock; the expensive part
    (formatting, printing, file I/O) is handed to ``sink``.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 sink: Callable[[dict], None] | None = None):
        self._clock = clock
        self._sink = sink
        self._lock = threading.Lock()
        self._state = "idle"
        self._voice_end: float | None = None
        self._server_at: float | None = None
        self._turn = 0
        self.discarded = 0
        self.records: list[dict] = []

    # ── hooks ──────────────────────────────────────────────────────────
    def mic_frame(self, level: float) -> None:
        if level < VOICE_LEVEL:
            return
        now = self._clock()
        with self._lock:
            if self._state == "replying":
                # Frames sent while a reply is on its way are not the end of the question,
                # unless that reply never reached the speakers (interrupted) and went stale.
                if self._server_at is not None and now - self._server_at < STALE_REPLY_S:
                    return
            self._state = "listening"
            self._voice_end = now
            self._server_at = None

    def server_audio(self) -> None:
        now = self._clock()
        with self._lock:
            if self._state != "listening" or self._voice_end is None:
                return
            if now - self._voice_end > MAX_PLAUSIBLE_S:
                self.discarded += 1
                self._state, self._voice_end = "idle", None
                return
            self._state, self._server_at = "replying", now

    def device_write(self, out_latency_s: float = 0.0) -> None:
        now = self._clock()
        with self._lock:
            if self._state != "replying" or self._voice_end is None or self._server_at is None:
                return
            self._turn += 1
            e2e = (now - self._voice_end) * 1000.0
            out_ms = max(0.0, float(out_latency_s or 0.0)) * 1000.0
            record = {
                "turn": self._turn,
                "e2e_ms": round(e2e, 1),
                "server_ms": round((self._server_at - self._voice_end) * 1000.0, 1),
                "local_ms": round((now - self._server_at) * 1000.0, 1),
                "out_latency_ms": round(out_ms, 1),
                "audible_est_ms": round(e2e + out_ms, 1),
            }
            self.records.append(record)
            if len(self.records) > MAX_RECORDS:
                del self.records[0]
            self._state, self._voice_end, self._server_at = "idle", None, None
            session = summarize([r["e2e_ms"] for r in self.records])
        if self._sink is not None:
            self._sink({**record, "session": session})

    # ── reading ────────────────────────────────────────────────────────
    def summary(self) -> dict:
        with self._lock:
            out = summarize([r["e2e_ms"] for r in self.records])
            out["discarded"] = self.discarded
            return out


def format_record(record: dict) -> str:
    s = record.get("session") or {}
    return (
        f"[LatencyTrace] turn {record['turn']}: speech end -> audio written {record['e2e_ms']:.0f} ms "
        f"(server {record['server_ms']:.0f} ms + local {record['local_ms']:.0f} ms; "
        f"device buffer +{record['out_latency_ms']:.0f} ms) | session n={s.get('n', 0)} "
        f"p50={s.get('p50_ms')} p90={s.get('p90_ms')} ms"
    )


class _BackgroundSink:
    """Prints each record and appends it as one JSON line, off the audio threads."""

    def __init__(self, log_dir: Callable[[], Path] = default_log_dir):
        self._log_dir = log_dir
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def __call__(self, record: dict) -> None:
        self._queue.put(record)
        if self._thread is None:
            with self._start_lock:
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name="jarvis-latency-trace", daemon=True)
                    self._thread.start()

    def _run(self) -> None:
        while True:
            record = self._queue.get()
            try:
                print(format_record(record))
                directory = self._log_dir()
                directory.mkdir(parents=True, exist_ok=True)
                line = {"ts": datetime.now().isoformat(timespec="seconds"),
                        **{k: v for k, v in record.items() if k != "session"}}
                with (directory / f"latency-{datetime.now():%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(line) + "\n")
            except Exception:  # measuring must never take the app down
                from jarvis.core import failsoft
                failsoft.suppress("core.latency_trace:sink")


TRACE = LatencyTrace(sink=_BackgroundSink())


# Module-level hooks: the call sites guard with ``if latency_trace.ACTIVE`` so that, when the trace is
# off, they do not even compute the mic level.
def mic_frame(level: float) -> None:
    TRACE.mic_frame(level)


def server_audio() -> None:
    TRACE.server_audio()


def device_write(out_latency_s: float = 0.0) -> None:
    TRACE.device_write(out_latency_s)
