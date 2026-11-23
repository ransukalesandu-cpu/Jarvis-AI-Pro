"""Offline voice loop: decision, VAD cutting, listen → transcribe → submit."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from jarvis.voice import offline_loop
from jarvis.voice.offline_loop import BLOCK, OfflineVoiceLoop, UtteranceCutter, should_run


def _tone(seconds: float, amp: float = 0.2) -> list:
    n = int(seconds * 16000)
    t = np.arange(n) / 16000
    sig = (amp * np.sin(2 * np.pi * 220 * t)).astype("float32")
    return [sig[i:i + BLOCK] for i in range(0, n, BLOCK)]


def _silence(seconds: float) -> list:
    return [np.zeros(BLOCK, dtype="float32") for _ in range(int(seconds * 16000 / BLOCK))]


class FakeStream:
    def __init__(self, blocks, done: threading.Event):
        self.blocks = list(blocks)
        self.done = done

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n):
        if self.blocks:
            return self.blocks.pop(0).reshape(-1, 1), False
        self.done.set()
        time.sleep(0.01)
        return np.zeros((n, 1), dtype="float32"), False


# ── decision ──────────────────────────────────────────────────────────────
def test_should_run_rules(monkeypatch):
    monkeypatch.delenv("JARVIS_OFFLINE_VOICE", raising=False)
    assert not should_run(live_up=True, down_for_s=99, offline=True, stt_ready=True)
    assert not should_run(live_up=False, down_for_s=99, offline=False, stt_ready=False)
    assert not should_run(live_up=False, down_for_s=1, offline=False, stt_ready=True)
    assert should_run(live_up=False, down_for_s=9, offline=False, stt_ready=True)
    assert should_run(live_up=False, down_for_s=0, offline=True, stt_ready=True)
    monkeypatch.setenv("JARVIS_OFFLINE_VOICE", "off")
    assert not should_run(live_up=False, down_for_s=99, offline=True, stt_ready=True)


# ── VAD ───────────────────────────────────────────────────────────────────
def test_cutter_returns_one_utterance_with_preroll():
    cutter = UtteranceCutter()
    out = []
    for block in _silence(0.5) + _tone(1.0) + _silence(1.5):
        got = cutter.push(block)
        if got is not None:
            out.append(got)
    assert len(out) == 1
    # speech (1.0 s) + pre-roll + the closing silence window
    assert 1.0 < out[0].size / 16000 < 3.0


def test_cutter_drops_short_clicks():
    cutter = UtteranceCutter()
    results = [cutter.push(b) for b in _tone(0.1) + _silence(1.5)]
    assert all(r is None for r in results)
    assert not cutter.active


def test_cutter_caps_long_speech():
    cutter = UtteranceCutter(max_s=2.0)
    results = [cutter.push(b) for b in _tone(3.0)]
    assert any(r is not None for r in results)


# ── loop ──────────────────────────────────────────────────────────────────
def _run_loop(blocks, **kw):
    done = threading.Event()
    submitted, logs = [], []
    loop = OfflineVoiceLoop(
        submit=submitted.append,
        transcribe=kw.pop("transcribe", lambda audio: {"text": "open notepad"}),
        stream_factory=lambda: FakeStream(blocks, done),
        logger=logs.append,
        **kw,
    )
    loop.start()
    assert done.wait(5)
    loop.stop()
    return submitted, logs


def test_loop_submits_transcript():
    submitted, logs = _run_loop(_silence(0.3) + _tone(0.8) + _silence(1.5))
    assert submitted == ["open notepad"]
    assert any("Offline voice active" in m for m in logs)


def test_loop_ignores_audio_while_jarvis_speaks():
    submitted, _ = _run_loop(_tone(0.8) + _silence(1.5), is_speaking=lambda: True)
    assert submitted == []


def test_loop_feeds_wake_word_while_asleep():
    frames = []
    submitted, _ = _run_loop(_tone(0.8) + _silence(1.5), is_awake=lambda: False, wake_feed=frames.append)
    assert submitted == []
    assert frames and frames[0].dtype == np.int16


def test_loop_skips_empty_transcripts():
    submitted, _ = _run_loop(_tone(0.8) + _silence(1.5), transcribe=lambda a: {"text": "  "})
    assert submitted == []


def test_loop_survives_stt_failure():
    def boom(_audio):
        raise RuntimeError("model missing")
    submitted, logs = _run_loop(_tone(0.8) + _silence(1.5), transcribe=boom)
    assert submitted == []
    assert any("speech-to-text failed" in m for m in logs)


# ── local TTS choice ──────────────────────────────────────────────────────
def test_pick_local_tts_offline_without_local_engine(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: None if name in {"kokoro", "piper"} else real(name, *a))
    monkeypatch.setenv("OFFLINE", "1")
    monkeypatch.delenv("JARVIS_OFFLINE_TTS", raising=False)
    assert offline_loop.pick_local_tts() is None


def test_pick_local_tts_online_uses_edge(monkeypatch):
    pytest.importorskip("edge_tts")
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: None if name in {"kokoro", "piper"} else real(name, *a))
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.delenv("JARVIS_OFFLINE", raising=False)
    monkeypatch.delenv("JARVIS_OFFLINE_TTS", raising=False)
    player = offline_loop.pick_local_tts()
    assert player is not None
    assert type(player._engine).__name__ == "EdgeTTSEngine"


# ── JarvisLive wiring ─────────────────────────────────────────────────────
def test_mixin_routes_utterance_through_typed_command_path():
    from jarvis.core.runtime.live_offline_voice import OfflineVoiceMixin

    class Ui:
        def __init__(self):
            self.logs = []

        def write_log(self, m):
            self.logs.append(m)

    class Live(OfflineVoiceMixin):
        def __init__(self):
            self.ui = Ui()
            self.typed = []
            self._last_user_speech = 0.0

        def _on_text_command(self, text):
            self.typed.append(text)

    live = Live()
    live._on_offline_utterance("what time is it")
    assert live.typed == ["what time is it"]
    assert live._last_user_speech > 0
    # Not speaking when the loop is not running (Live answers itself).
    live._speak_offline("hello")
    assert live._offline_tts is None


def test_jarvis_live_has_offline_voice():
    pytest.importorskip("google.genai")
    from jarvis import main

    assert hasattr(main.JarvisLive, "_offline_voice_watch")
    assert hasattr(main.JarvisLive, "_speak_offline")
