"""
Tests for Jarvis voice engine and speech manager exception handling and safety.
"""

import unittest
from unittest.mock import MagicMock, patch

from voice.speech_engine import SafeSpeechManager
from voice.voice_engine import JarvisVoiceEngine


class TestVoiceEngineAndSpeechManager(unittest.TestCase):
    def test_speech_manager_handles_missing_pyttsx3(self):
        manager = SafeSpeechManager()
        with patch.dict("sys.modules", {"pyttsx3": None}):
            # Should log error/warning without throwing an exception in worker thread
            manager.speak("Testing missing pyttsx3")
            manager.speech_queue.join()

    def test_voice_engine_handles_missing_edge_tts(self):
        with patch("voice.voice_engine.edge_tts", None):
            engine = JarvisVoiceEngine()
            # Should log error and return safely without crash
            engine.speak_stream((token for token in ["Hello", " world."]))

    def test_voice_engine_handles_missing_pygame(self):
        with patch("voice.voice_engine.pygame", None):
            engine = JarvisVoiceEngine()
            engine.interrupt()
            self.assertFalse(engine._is_speaking)

    def test_voice_engine_synthesis_stream(self):
        mock_communicate = MagicMock()

        async def _mock_stream():
            yield {"type": "audio", "data": b"fake_audio_bytes"}

        mock_communicate.stream = _mock_stream

        with patch("voice.voice_engine.edge_tts") as mock_edge_tts, \
             patch("voice.voice_engine.pygame") as mock_pygame:
            mock_edge_tts.Communicate.return_value = mock_communicate
            mock_pygame.mixer.get_init.return_value = True
            mock_pygame.mixer.music.get_busy.side_effect = [True, False]

            engine = JarvisVoiceEngine()
            engine.speak_stream((token for token in ["Hello", " world."]))

            mock_edge_tts.Communicate.assert_called_once()
            mock_pygame.mixer.music.play.assert_called_once()


if __name__ == "__main__":
    unittest.main()
