"""Tests for the optional ElevenLabs dual voice engine (no network/audio required)."""
from jarvis.core import tts


def test_auto_mode_selects_cinematic_for_system_alerts():
    assert tts.DualVoiceTTSEngine.select_mode("Warning: battery low") == "cinematic"


def test_auto_mode_defaults_to_natural_for_conversation():
    assert tts.DualVoiceTTSEngine.select_mode("How can I help you today?") == "natural"


def test_explicit_mode_overrides_classifier():
    assert tts.DualVoiceTTSEngine.select_mode("System online", "natural") == "natural"
    assert tts.DualVoiceTTSEngine.select_mode("Hello", "cinematic") == "cinematic"


def test_missing_key_uses_edge_fallback(monkeypatch):
    calls = []
    class FakeEdge:
        def __init__(self, voice):
            calls.append(("init", voice))
        def speak(self, text):
            calls.append(("speak", text))

    monkeypatch.setattr(tts, "EdgeTTSEngine", FakeEdge)
    engine = tts.DualVoiceTTSEngine("", "cinematic-id", "natural-id")
    engine.speak("Hello")
    assert calls[-1] == ("speak", "Hello")
    assert engine.last_provider == "edge-tts"


def test_elevenlabs_quota_error_falls_back_without_playback(monkeypatch):
    calls = []
    class FakeEdge:
        def __init__(self, voice):
            pass
        def speak(self, text):
            calls.append(("fallback", text))

    class FakeEleven:
        def __init__(self, **kwargs):
            calls.append(("voice", kwargs["voice_id"]))
        def synthesize(self, text):
            raise RuntimeError("HTTP 429 quota exceeded")

    monkeypatch.setattr(tts, "EdgeTTSEngine", FakeEdge)
    monkeypatch.setattr(tts, "ElevenLabsTTSEngine", FakeEleven)
    monkeypatch.setattr(tts, "_play_audio_bytes", lambda audio: calls.append(("play", audio)))
    engine = tts.DualVoiceTTSEngine("secret", "cinematic-id", "natural-id")
    engine.speak("System online")
    assert ("voice", "cinematic-id") in calls
    assert ("fallback", "System online") in calls
    assert not any(call[0] == "play" for call in calls)
    assert engine.last_provider == "edge-tts-fallback"


def test_success_plays_once_and_uses_natural_voice(monkeypatch):
    calls = []
    class FakeEdge:
        def __init__(self, voice):
            pass
        def speak(self, text):
            calls.append(("fallback", text))

    class FakeEleven:
        def __init__(self, **kwargs):
            calls.append(("voice", kwargs["voice_id"]))
        def synthesize(self, text):
            return b"audio-bytes"

    monkeypatch.setattr(tts, "EdgeTTSEngine", FakeEdge)
    monkeypatch.setattr(tts, "ElevenLabsTTSEngine", FakeEleven)
    monkeypatch.setattr(tts, "_play_audio_bytes", lambda audio: calls.append(("play", audio)))
    engine = tts.DualVoiceTTSEngine("secret", "cinematic-id", "natural-id")
    engine.speak("Good morning")
    assert ("voice", "natural-id") in calls
    assert calls.count(("play", b"audio-bytes")) == 1
    assert engine.last_provider == "elevenlabs"


def test_factory_reads_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    player = tts.create_tts_player({
        "tts_engine": "dual",
        "elevenlabs_cinematic_voice_id": "cinematic",
        "elevenlabs_natural_voice_id": "natural",
    })
    assert isinstance(player._engine, tts.DualVoiceTTSEngine)
    assert player._engine.api_key == "test-key"



def test_dual_engine_synthesize_returns_elevenlabs_bytes(monkeypatch):
    class FakeEdge:
        def __init__(self, voice):
            pass
        def synthesize(self, text):
            return b"edge-audio"

    class FakeEleven:
        def __init__(self, **kwargs):
            self.voice_id = kwargs["voice_id"]
        def synthesize(self, text):
            return b"elevenlabs-audio"

    monkeypatch.setattr(tts, "EdgeTTSEngine", FakeEdge)
    monkeypatch.setattr(tts, "ElevenLabsTTSEngine", FakeEleven)
    engine = tts.DualVoiceTTSEngine("secret", "cinematic-id", "natural-id")
    assert engine.synthesize("Hello there") == b"elevenlabs-audio"
    assert engine.last_provider == "elevenlabs"
    assert engine.last_mode == "natural"


def test_dual_engine_synthesize_uses_edge_bytes_after_provider_failure(monkeypatch):
    class FakeEdge:
        def __init__(self, voice):
            pass
        def synthesize(self, text):
            return b"edge-fallback"

    class FakeEleven:
        def __init__(self, **kwargs):
            pass
        def synthesize(self, text):
            raise RuntimeError("quota exceeded")

    monkeypatch.setattr(tts, "EdgeTTSEngine", FakeEdge)
    monkeypatch.setattr(tts, "ElevenLabsTTSEngine", FakeEleven)
    engine = tts.DualVoiceTTSEngine("secret", "cinematic-id", "natural-id")
    assert engine.synthesize("System online") == b"edge-fallback"
    assert engine.last_provider == "edge-tts-fallback"


def test_save_tts_settings_validates_and_preserves_other_config(monkeypatch, tmp_path):
    from jarvis.memory import config_manager

    config_file = tmp_path / "api_keys.json"
    monkeypatch.setattr(config_manager, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_manager, "CONFIG_FILE", config_file)
    config_manager._write_config({"gemini_api_key": "keep-this"})
    config_manager.save_tts_settings({
        "tts_engine": "elevenlabs_dual",
        "tts_voice_mode": "cinematic",
        "elevenlabs_api_key": "local-secret",
        "elevenlabs_cinematic_voice_id": "cinematic-id",
        "elevenlabs_natural_voice_id": "natural-id",
        "tts_speed": 1.4,
    })
    saved = config_manager.load_api_keys()
    assert saved["gemini_api_key"] == "keep-this"
    assert saved["elevenlabs_api_key"] == "local-secret"
    assert saved["tts_engine"] == "elevenlabs_dual"
    assert saved["tts_speed"] == 1.2
    assert config_manager.get_tts_settings()["tts_voice_mode"] == "cinematic"


def test_save_tts_settings_rejects_unknown_engine():
    from jarvis.memory import config_manager
    import pytest

    with pytest.raises(ValueError):
        config_manager.save_tts_settings({"tts_engine": "unknown"})



def test_external_tts_decoder_returns_24khz_mono_int16(monkeypatch):
    import sys
    from types import SimpleNamespace
    from jarvis.main import _decode_external_tts_to_live_pcm

    fake_miniaudio = SimpleNamespace(
        SampleFormat=SimpleNamespace(FLOAT32="float32"),
        decode=lambda audio, **kwargs: SimpleNamespace(
            samples=[0.0, 0.5, -0.5, 0.25],
            sample_rate=24000,
        ),
    )
    monkeypatch.setitem(sys.modules, "miniaudio", fake_miniaudio)
    pcm = _decode_external_tts_to_live_pcm(b"fake-audio")
    assert len(pcm) == 8
    assert int.from_bytes(pcm[2:4], "little", signed=True) > 0
    assert int.from_bytes(pcm[4:6], "little", signed=True) < 0


def test_external_tts_decoder_resamples_to_live_rate(monkeypatch):
    import sys
    from types import SimpleNamespace
    from jarvis.main import _decode_external_tts_to_live_pcm

    fake_miniaudio = SimpleNamespace(
        SampleFormat=SimpleNamespace(FLOAT32="float32"),
        decode=lambda audio, **kwargs: SimpleNamespace(
            samples=[0.0, 0.25, 0.5, 0.25, 0.0, -0.25, -0.5, -0.25],
            sample_rate=48000,
        ),
    )
    monkeypatch.setitem(sys.modules, "miniaudio", fake_miniaudio)
    pcm = _decode_external_tts_to_live_pcm(b"fake-audio")
    assert len(pcm) == 8


def test_save_tts_settings_rejects_unsafe_voice_id(monkeypatch, tmp_path):
    from jarvis.memory import config_manager
    import pytest

    monkeypatch.setattr(config_manager, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_manager, "CONFIG_FILE", tmp_path / "api_keys.json")
    with pytest.raises(ValueError):
        config_manager.save_tts_settings({
            "tts_engine": "elevenlabs_dual",
            "elevenlabs_cinematic_voice_id": "voice/with/path",
        })


def test_auto_mode_selects_cinematic_for_sinhala_alert():
    assert tts.DualVoiceTTSEngine.select_mode("පද්ධති අනතුරු ඇඟවීම") == "cinematic"
