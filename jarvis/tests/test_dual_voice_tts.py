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
