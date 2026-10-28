"""
Unit tests for Production Hardening, Audio Resilience, Echo-Guard, and Lockdown.
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure JarvisAI package is in path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for path in (str(ROOT_DIR), str(JARVIS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from security.auth_manager import configured_cooldown_seconds
from security.lockdown import clamp_lockdown_duration, lock_workstation, teardown_audio_stream
from core.echo import EchoGuard


class TestHardening(unittest.TestCase):

    def test_gitignore_exclusions(self):
        """Verify .gitignore files strictly exclude all specified local files."""
        root_gitignore = (ROOT_DIR / ".gitignore").read_text(encoding="utf-8")
        jarvis_gitignore = (JARVIS_DIR / ".gitignore").read_text(encoding="utf-8")

        required_patterns = [
            "*.emb",
            "*.vault",
            "*.hash",
            "*.db",
            "*.sqlite",
            "*.sqlite3",
            "Jarvis_Received_Files/",
            ".env",
            "secrets.json",
        ]

        combined = root_gitignore + "\n" + jarvis_gitignore
        for pattern in required_patterns:
            self.assertIn(
                pattern,
                combined,
                f"Required exclusion pattern '{pattern}' missing from .gitignore",
            )

    def test_audio_teardown_suppresses_portaudio_error(self):
        """Verify audio teardown functions suppress PortAudioError cleanly."""
        class MockPortAudioError(Exception):
            pass

        mock_stream = MagicMock()
        mock_stream.stop_stream.side_effect = MockPortAudioError("PortAudioError (-9988): Device unavailable")
        mock_stream.close.side_effect = MockPortAudioError("PortAudioError (-9988): Stream closed")

        mock_instance = MagicMock()
        mock_instance.terminate.side_effect = MockPortAudioError("PortAudioError (-9988): Host error")

        # Must execute without throwing unhandled exceptions
        result = teardown_audio_stream(mock_stream, mock_instance)
        self.assertTrue(result)
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_instance.terminate.assert_called_once()

    def test_lockdown_duration_clamping(self):
        """Verify lockdown duration clamping strictly enforces 60s to 300s."""
        self.assertEqual(clamp_lockdown_duration(10), 60)
        self.assertEqual(clamp_lockdown_duration(0), 60)
        self.assertEqual(clamp_lockdown_duration(-100), 60)
        self.assertEqual(clamp_lockdown_duration(60), 60)
        self.assertEqual(clamp_lockdown_duration(180), 180)
        self.assertEqual(clamp_lockdown_duration(300), 300)
        self.assertEqual(clamp_lockdown_duration(500), 300)
        self.assertEqual(clamp_lockdown_duration("invalid"), 60)

        # Verify configured_cooldown_seconds in auth_manager
        with patch.dict(os.environ, {"JARVIS_PRIVACY_LOCK_MINUTES": "0"}):
            self.assertEqual(configured_cooldown_seconds(), 60)
        with patch.dict(os.environ, {"JARVIS_PRIVACY_LOCK_MINUTES": "10"}):
            self.assertEqual(configured_cooldown_seconds(), 60)
        with patch.dict(os.environ, {"JARVIS_PRIVACY_LOCK_MINUTES": "3"}):
            self.assertEqual(configured_cooldown_seconds(), 180)

    def test_lock_workstation_return_code(self):
        """Verify lock_workstation return code handling and ctypes error logging."""
        if sys.platform == "win32":
            with patch("ctypes.windll.user32.LockWorkStation", return_value=0), \
                 patch("ctypes.GetLastError", return_value=5):
                success, err = lock_workstation()
                self.assertFalse(success)
                self.assertEqual(err, 5)

            with patch("ctypes.windll.user32.LockWorkStation", return_value=1):
                success, err = lock_workstation()
                self.assertTrue(success)
                self.assertEqual(err, 0)
        else:
            success, err = lock_workstation()
            self.assertFalse(success)
            self.assertEqual(err, 0)

    def test_barge_in_echo_refractory_and_adaptive_threshold(self):
        """Verify barge-in refractory guardband (350ms) and adaptive threshold scaling."""
        guard = EchoGuard()
        now = time.monotonic()
        pcm_sample = [10000] * 1024

        # Register output history so EchoGuard compares microphone audio against output
        guard.note_output(pcm_sample, 16000, 0.5, when=now)

        # 1. Start TTS speaking
        guard.set_tts_speaking(True, when=now)

        # 2. Within 350ms refractory period, is_user_speech should return False regardless of audio
        res_refractory = guard.is_user_speech(pcm_sample, sr=16000, level=0.5, when=now + 0.100, fast=True)
        self.assertFalse(res_refractory, "Speech within 350ms refractory guardband must be suppressed")

        # 3. After 350ms refractory period, test adaptive threshold factor and continuous duration
        t_after = now + 0.400
        guard.note_output(pcm_sample, 16000, 0.5, when=t_after)
        user_speech_pcm = [20000 if i % 2 == 0 else -20000 for i in range(1024)]
        res_1 = guard.is_user_speech(user_speech_pcm, sr=16000, level=0.5, when=t_after, fast=True)
        self.assertFalse(res_1, "Continuous speech <150ms must not trigger barge-in immediately")

        # Continuous speech for >150ms (from t_after to t_after + 0.200s)
        guard.note_output(pcm_sample, 16000, 0.5, when=t_after + 0.200)
        res_2 = guard.is_user_speech(user_speech_pcm, sr=16000, level=0.5, when=t_after + 0.200, fast=True)
        self.assertTrue(res_2, "Continuous speech >150ms after refractory period should trigger barge-in")


if __name__ == "__main__":
    unittest.main()
