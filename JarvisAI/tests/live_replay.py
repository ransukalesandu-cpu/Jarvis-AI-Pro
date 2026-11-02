"""Replay harness for the Gemini Live receive -> playback pipeline.

It drives the real ``JarvisLive._receive_audio`` and the real
``core.audio_playback.run_audio_playback`` against:

* a fake Live session whose ``receive()`` yields a scripted list of server
  events (audio chunks, transcriptions, ``interrupted``, ``turn_complete``),
  each after a chosen delay, and
* a fake ``sounddevice`` output stream whose ``write`` blocks for the real
  duration of the PCM it was given (like a paced device), records every byte
  it accepted, and honours ``abort()``.

That makes stalls, dropped audio and slow barge-in measurable without a
microphone, a speaker, an API key or a network. A scenario is a list of
``Step`` items; :func:`run_scenario` returns a :class:`ReplayResult`.

The fixtures in tests/fixtures/live_replay/*.json use the same shape, so a
sequence captured from a real session can be replayed as a regression test.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

RATE = 24000          # Gemini Live output sample rate
BYTES_PER_SEC = RATE * 2
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "live_replay"


# ── scripted server events ────────────────────────────────────────────────────
@dataclass
class Step:
    """One server event, sent ``delay`` seconds after the previous one."""

    delay: float = 0.0
    audio_ms: int = 0                 # PCM payload length in milliseconds
    output_text: str = ""
    input_text: str = ""
    interrupted: bool = False
    turn_complete: bool = False
    generation_complete: bool = False
    # Local action to run at this point instead of (or before) the event,
    # for example a false local barge-in: ``action="local_interrupt"``.
    action: str = ""


def steps_from_fixture(name: str) -> list[Step]:
    """Load a fixture. A row may carry ``"repeat": N`` to expand into N steps."""
    data = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    steps: list[Step] = []
    for row in data["steps"]:
        row = dict(row)
        repeat = int(row.pop("repeat", 1))
        steps.extend(Step(**row) for _ in range(repeat))
    return steps


def _pcm(ms: int, marker: int) -> bytes:
    """Non-silent PCM whose sample value identifies the turn it came from."""
    samples = int(RATE * ms / 1000)
    value = (marker & 0x7F) + 1
    return bytes([value, 0]) * samples


def _event(step: Step, marker: int):
    parts = []
    if step.audio_ms:
        parts.append(SimpleNamespace(inline_data=SimpleNamespace(
            mime_type="audio/pcm;rate=24000", data=_pcm(step.audio_ms, marker))))
    model_turn = SimpleNamespace(parts=parts) if parts else None
    sc = SimpleNamespace(
        model_turn=model_turn,
        output_transcription=SimpleNamespace(text=step.output_text) if step.output_text else None,
        input_transcription=SimpleNamespace(text=step.input_text) if step.input_text else None,
        interrupted=step.interrupted,
        turn_complete=step.turn_complete,
        generation_complete=step.generation_complete,
    )
    return SimpleNamespace(server_content=sc, tool_call=None, session_resumption_update=None,
                           data=None)


class FakeSession:
    """Plays a script through ``receive()``; records what the client sends."""

    def __init__(self, steps: list[Step], host_ref: Callable[[], Any]):
        self._steps = steps
        self._host_ref = host_ref
        self.sent: list[dict] = []
        self.done = asyncio.Event()
        self.marks: dict[str, float] = {}

    async def receive(self):
        marker = 1
        for step in self._steps:
            if step.delay:
                await asyncio.sleep(step.delay)
            if step.action == "local_interrupt":
                # Explicit stop (wake word, stop word, UI button).
                self._host_ref()._interrupt_on_loop()
                continue
            if step.action == "local_bargein":
                # VAD/echo barge-in while JARVIS speaks: provisional.
                self._host_ref()._interrupt_on_loop(provisional=True)
                continue
            if step.action == "client_turn":
                # A turn JARVIS injected itself (speak(), proactive, monitor):
                # the model answers with no input transcription first.
                marker += 1
                continue
            if step.input_text:
                marker += 1
            if step.interrupted:
                self.marks.setdefault("server_interrupted", time.monotonic())
            yield _event(step, marker)
        self.done.set()
        # Keep the receiver parked like a live socket with no traffic.
        await asyncio.sleep(3600)

    async def send_client_content(self, **kwargs):
        self.sent.append({"client_content": kwargs})

    async def send_tool_response(self, **kwargs):
        self.sent.append({"tool_response": kwargs})

    async def send_realtime_input(self, **kwargs):
        self.sent.append({"realtime": kwargs})


# ── paced fake output device ─────────────────────────────────────────────────
class FakeStream:
    def __init__(self):
        self.active = True
        self.latency = 0.05
        self.written = bytearray()
        self.write_log: list[tuple[float, int, int]] = []   # (t, bytes, marker)
        self.aborts: list[float] = []
        self._abort = threading.Event()
        self._lock = threading.Lock()

    def write(self, data: bytes) -> None:
        if not self.active:
            raise RuntimeError("stream stopped")
        duration = len(data) / BYTES_PER_SEC
        # Block like a paced device, but return early on abort().
        if self._abort.wait(duration):
            self._abort.clear()
            raise RuntimeError("aborted")
        with self._lock:
            self.written.extend(data)
            marker = data[0] if data else 0
            self.write_log.append((time.monotonic(), len(data), marker))

    def abort(self) -> None:
        self.aborts.append(time.monotonic())
        self.active = False
        self._abort.set()

    def start(self) -> None:
        self._abort.clear()
        self.active = True

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.active = False


class FakeSD:
    def __init__(self):
        self.stream = FakeStream()

    def RawOutputStream(self, **_kwargs):   # noqa: N802 - mirrors sounddevice
        return self.stream

    def OutputStream(self, **_kwargs):   # noqa: N802
        return self.stream

    def query_devices(self, *_a, **_k):
        return []


class _DeviceService:
    @staticmethod
    def resolve(_name, _kind):
        return None


# ── host construction ────────────────────────────────────────────────────────
_HOST_CACHE: dict = {}


def build_host():
    """A real JarvisLive (headless UI) with fresh per-run asyncio state.

    Constructing JarvisLive discovers actions and plugins, which takes a couple
    of seconds, so one instance is built per process and its live-session
    state is reset before each scenario.
    """
    import main
    from core.ui_coordinator import HeadlessJarvisUI
    from core.vocal_behavior import VocalPlan

    host = _HOST_CACHE.get("host")
    if host is None:
        host = main.JarvisLive(HeadlessJarvisUI())
        _HOST_CACHE["host"] = host
        _HOST_CACHE["registries"] = (host._action_registry, host._plugin_registry)
    # A test may swap in its own registry; every scenario starts from the real one.
    host._action_registry, host._plugin_registry = _HOST_CACHE["registries"]
    host.__dict__.pop("_announcements", None)
    host.__dict__.pop("_session_tool_calls", None)
    host._loop = asyncio.get_running_loop()
    host.audio_in_queue = asyncio.Queue()
    host.out_queue = asyncio.Queue(maxsize=200)
    host._turn_done_event = asyncio.Event()
    host._playback_interrupt_requested = threading.Event()
    host._output_stream = None
    host._is_speaking = False
    host._assistant_turn_pending = False
    host._briefing_active = False
    host._briefing_cancelled = False
    host._briefing_task = None
    host._vocal_plan = VocalPlan()
    host._vocal_plan_ready = False
    host._vocal_audio_started = False
    host._play_cursor = 0.0
    host._out_latency = 0.05
    host._tail_until = 0.0
    host._phone_active = False
    host._dashboard = None
    host._shutdown_requested = False
    host._interrupted = False
    host._awake = True
    return host


@dataclass
class ReplayResult:
    written_ms_by_marker: dict[int, float] = field(default_factory=dict)
    sent_ms_by_marker: dict[int, float] = field(default_factory=dict)
    write_log: list[tuple[float, int, int]] = field(default_factory=list)
    aborts: list[float] = field(default_factory=list)
    marks: dict[str, float] = field(default_factory=dict)
    max_write_gap_ms: float = 0.0
    elapsed: float = 0.0


async def run_scenario(steps: list[Step], *, settle: float = 0.6,
                       timeout: float = 120.0) -> ReplayResult:
    """Play ``steps`` through the real receive + playback code and measure."""
    import main
    from core import audio_playback

    host = build_host()
    session = FakeSession(steps, lambda: host)
    host.session = session
    fake_sd = FakeSD()

    # Expected PCM per turn marker, computed the same way FakeSession assigns it.
    sent: dict[int, float] = {}
    marker = 1
    for step in steps:
        if step.action == "client_turn" or step.input_text:
            marker += 1
        if step.audio_ms:
            sent[marker] = sent.get(marker, 0.0) + step.audio_ms

    started = time.monotonic()
    receiver = asyncio.create_task(host._receive_audio())
    player = asyncio.create_task(audio_playback.run_audio_playback(
        host,
        audio_backend=fake_sd,
        device_service=_DeviceService(),
        get_output_device_fn=lambda: "",
        pcm_visemes_fn=main._pcm_visemes,
        output_executor=main._AUDIO_OUTPUT_EXECUTOR,
        tail_margin=main._TAIL_MARGIN,
        first_sound_delay=main._FIRST_SOUND,
        cursor_slack=main._CURSOR_SLACK,
        viseme_hop=main._VIS_HOP,
    ))
    try:
        await asyncio.wait_for(session.done.wait(), timeout)
        # Let playback drain whatever is still queued.
        deadline = time.monotonic() + timeout
        last = -1
        while time.monotonic() < deadline:
            await asyncio.sleep(settle)
            now_len = len(fake_sd.stream.written)
            if now_len == last and host.audio_in_queue.empty():
                break
            last = now_len
    finally:
        host._shutdown_requested = True
        for task in (receiver, player):
            task.cancel()
        await asyncio.gather(receiver, player, return_exceptions=True)

    stream = fake_sd.stream
    written: dict[int, float] = {}
    for _t, n, m in stream.write_log:
        # PCM sample bytes carry (marker & 0x7F) + 1; undo the +1.
        written[m - 1] = written.get(m - 1, 0.0) + n / BYTES_PER_SEC * 1000
    gaps = [
        (b[0] - a[0]) * 1000 - (b[1] / BYTES_PER_SEC * 1000)
        for a, b in zip(stream.write_log, stream.write_log[1:])
        if a[2] == b[2]
    ]
    return ReplayResult(
        written_ms_by_marker=written,
        sent_ms_by_marker=sent,
        write_log=list(stream.write_log),
        aborts=list(stream.aborts),
        marks=dict(session.marks),
        max_write_gap_ms=max(gaps) if gaps else 0.0,
        elapsed=time.monotonic() - started,
    )


def run(steps: list[Step], **kwargs) -> ReplayResult:
    return asyncio.run(run_scenario(steps, **kwargs))
