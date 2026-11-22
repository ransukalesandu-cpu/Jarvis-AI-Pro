"""Offline STT + dictation (P11 of the Cherry Studio parity plan). faster-whisper and the mic are faked."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from jarvis.voice import local_stt


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, source, language=None, vad_filter=True, beam_size=1):
        self.calls.append((source if isinstance(source, str) else getattr(source, "dtype", None), language))
        return iter([SimpleNamespace(text=" hello "), SimpleNamespace(text="world ")]), SimpleNamespace(language="en")


class FakeStream:
    def __init__(self, blocks):
        self.blocks = list(blocks)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        block = self.blocks.pop(0) if self.blocks else np.zeros(n, dtype="float32")
        return block.reshape(-1, 1), False


def test_transcribe_file_and_int16_array():
    m = FakeModel()
    assert local_stt.transcribe("clip.wav", model=m)["text"] == "hello world"
    r = local_stt.transcribe(np.zeros(16000, dtype="int16"), language="si", model=m)
    assert r["language"] == "en" and m.calls[-1] == (np.dtype("float32"), "si")


def test_missing_package_message(monkeypatch):
    monkeypatch.setattr(local_stt, "available", lambda: False)
    with pytest.raises(RuntimeError, match="requirements-stt"):
        local_stt.transcribe("x.wav")


def test_record_stops_after_silence():
    loud = np.full(1600, 0.2, dtype="float32")
    quiet = np.zeros(1600, dtype="float32")
    blocks = [loud] * 5 + [quiet] * 400
    audio = local_stt.record(stream_factory=lambda: FakeStream(blocks), silence_s=0.0)
    assert 5 * 1600 <= audio.size < 400 * 1600


def test_record_stop_event():
    stop = threading.Event()
    stop.set()
    audio = local_stt.record(stream_factory=lambda: FakeStream([]), stop=stop)
    assert audio.size == 0


def test_tool(monkeypatch, tmp_path):
    from jarvis.actions import dictation as tool

    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setattr(local_stt, "available", lambda: False)
    assert "not installed" in tool.dictation({"action": "status"})
    assert "not installed" in tool.dictation({"action": "dictate"})
    monkeypatch.setattr(local_stt, "available", lambda: True)
    monkeypatch.setattr(local_stt, "_get_model", lambda: FakeModel())
    f = tmp_path / "meeting.mp3"
    f.write_bytes(b"fake")
    out = tool.dictation({"action": "transcribe_file", "path": str(f)})
    assert "hello world" in out and (tmp_path / "meeting.txt").read_text() == "hello world"
    typed = []
    monkeypatch.setattr(local_stt, "record", lambda seconds=0, stop=None: np.zeros(10, dtype="float32"))
    monkeypatch.setattr(local_stt, "type_text", typed.append)
    assert tool.dictation({"action": "dictate"}) == "Typed: hello world" and typed == ["hello world"]
    assert tool.dictation({"action": "stop"}) == "Dictation stopped."


def test_tiers():
    from jarvis.core import security
    assert security.tier_for("dictation", {"action": "status"}) == security.TIER_SAFE
    assert security.tier_for("dictation", {"action": "dictate"}) == security.TIER_SENSITIVE
