"""Piper TTS engine: both piper-tts APIs, missing voice, offline-loop preference."""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from jarvis.core import tts


class Chunk:
    def __init__(self, n, rate):
        self.audio_float_array = np.full(n, 0.1, dtype=np.float32)
        self.sample_rate = rate


class NewVoice:                     # piper1-gpl 1.3+
    loaded = []

    @classmethod
    def load(cls, path):
        cls.loaded.append(path)
        return cls()

    def synthesize(self, text, syn_config=None):
        self.cfg = syn_config
        yield Chunk(100, 22050)
        yield Chunk(50, 22050)


class OldVoice:                     # piper-tts 1.2
    config = types.SimpleNamespace(sample_rate=16000)

    @classmethod
    def load(cls, path):
        return cls()

    def synthesize_stream_raw(self, text, length_scale=1.0):
        self.length_scale = length_scale
        yield (np.ones(80, dtype=np.int16) * 1000).tobytes()


@pytest.fixture
def piper_env(tmp_path, monkeypatch):
    monkeypatch.setattr(tts.PiperTTSEngine, "voices_dir", staticmethod(lambda: tmp_path))
    played = []
    monkeypatch.setattr(tts, "_play_np", lambda arr, rate: played.append((len(arr), rate)))
    return tmp_path, played


def _install(monkeypatch, voice_cls, with_config=True):
    mod = types.ModuleType("piper")
    mod.PiperVoice = voice_cls
    if with_config:
        mod.SynthesisConfig = lambda length_scale=1.0: types.SimpleNamespace(length_scale=length_scale)
    monkeypatch.setitem(sys.modules, "piper", mod)


def test_new_api_plays_chunks(piper_env, monkeypatch):
    tmp, played = piper_env
    (tmp / "en_US-lessac-medium.onnx").write_bytes(b"x")
    _install(monkeypatch, NewVoice)
    tts.PiperTTSEngine(speed=2.0).speak("hello")
    assert played == [(100, 22050), (50, 22050)]


def test_old_api_converts_int16(piper_env, monkeypatch):
    tmp, played = piper_env
    (tmp / "en_US-amy-low.onnx").write_bytes(b"x")
    _install(monkeypatch, OldVoice, with_config=False)
    tts.PiperTTSEngine(voice="en_US-amy-low").speak("hi")
    assert played == [(80, 16000)]


def test_missing_voice_explains_download(piper_env, monkeypatch):
    _install(monkeypatch, NewVoice)
    with pytest.raises(RuntimeError, match="download_voices"):
        tts.PiperTTSEngine().speak("hi")


def test_factory_and_full_path(tmp_path):
    player = tts.create_tts_player({"tts_engine": "piper", "tts_voice": str(tmp_path / "v.onnx")})
    assert isinstance(player._engine, tts.PiperTTSEngine)
    assert player._engine.model_path() == tmp_path / "v.onnx"


def test_offline_loop_prefers_piper_when_voice_present(piper_env, monkeypatch):
    tmp, _ = piper_env
    (tmp / "en_US-lessac-medium.onnx").write_bytes(b"x")
    _install(monkeypatch, NewVoice)
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: types.SimpleNamespace() if name == "piper" else real(name, *a))
    monkeypatch.delenv("JARVIS_OFFLINE_TTS", raising=False)
    monkeypatch.delenv("JARVIS_PIPER_VOICE", raising=False)
    from jarvis.voice import offline_loop
    player = offline_loop.pick_local_tts()
    assert isinstance(player._engine, tts.PiperTTSEngine)
