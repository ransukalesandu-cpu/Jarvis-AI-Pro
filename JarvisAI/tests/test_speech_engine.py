"""Deterministic speech tests: no native engine, devices, network, or API keys."""
import asyncio
import builtins
import queue
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from main import JarvisLive
from voice.speech_engine import SafeSpeechManager


class LegacySpeechEngineTests(unittest.TestCase):
    def setUp(self):
        # Drive the real worker synchronously so assertions cover completion,
        # without leaving a daemon thread or starting native audio in a test.
        with patch("voice.speech_engine.threading.Thread"):
            self.manager = SafeSpeechManager()

    def drain_worker(self):
        get = self.manager.speech_queue.get
        with patch.object(self.manager.speech_queue, "get", side_effect=lambda *a, **k: get(block=False)), \
             patch("voice.speech_engine.time.sleep"):
            with self.assertRaises(queue.Empty):
                self.manager._speech_worker()
        self.assertFalse(self.manager.is_speaking)
        self.assertEqual(self.manager.speech_queue.unfinished_tasks, 0)

    def test_missing_optional_package_is_explained_and_queue_is_completed(self):
        self.manager.speak("Optional legacy speech")
        with patch.dict(sys.modules, {"pyttsx3": None}), patch("builtins.print") as output:
            self.drain_worker()
        message = " ".join(str(args) for args in output.call_args_list)
        self.assertIn("Optional legacy", message)
        self.assertIn("pyttsx3 is not installed", message)
        self.assertIn("Gemini Live", message)
        self.assertNotIn("Playback error", message)
        self.assertNotIn("No module named", message)

    def test_available_engine_preserves_phrase_playback(self):
        engine = Mock()
        backend = SimpleNamespace(init=Mock(return_value=engine))
        self.manager.speak("First phrase. Second phrase")
        with patch.dict(sys.modules, {"pyttsx3": backend}):
            self.drain_worker()
        backend.init.assert_called_once_with()
        self.assertEqual(engine.say.call_args_list, [call("First phrase"), call("Second phrase")])
        self.assertEqual(engine.runAndWait.call_count, 2)

    def test_missing_backend_dependency_is_not_misreported_as_optional_package(self):
        import_module = builtins.__import__

        def broken_backend(name, *args, **kwargs):
            if name == "pyttsx3":
                raise ModuleNotFoundError("No module named 'native_driver'", name="native_driver")
            return import_module(name, *args, **kwargs)

        self.manager.speak("Broken optional backend")
        with patch("builtins.__import__", side_effect=broken_backend), patch("builtins.print") as output:
            self.drain_worker()
        output.assert_called_once_with("[Voice] Playback error: No module named 'native_driver'")

    def test_interruption_stops_remaining_phrases_and_clears_pending_speech(self):
        engine = Mock()
        engine.runAndWait.side_effect = self.manager.interrupt
        backend = SimpleNamespace(init=Mock(return_value=engine))
        self.manager.speak("First phrase. Cancel this phrase")
        self.manager.speak("Cancel this queued request")
        with patch.dict(sys.modules, {"pyttsx3": backend}), patch("builtins.print"):
            self.drain_worker()
        engine.say.assert_called_once_with("First phrase")
        self.assertTrue(self.manager.stop_event.is_set())

    def test_native_engine_unavailable_reports_failure_and_completes_queue(self):
        backend = SimpleNamespace(init=Mock(side_effect=RuntimeError("native engine unavailable")))
        self.manager.speak("No native audio engine")
        with patch.dict(sys.modules, {"pyttsx3": backend}), patch("builtins.print") as output:
            self.drain_worker()
        output.assert_called_once_with("[Voice] Playback error: native engine unavailable")

    def test_playback_error_does_not_prevent_next_request(self):
        self.manager.speak("Failed request")
        self.manager.speak("Next request")
        with patch.object(self.manager, "_play_audio_stream", side_effect=[RuntimeError("synthetic device error"), None]) as play, \
             patch("builtins.print") as output:
            self.drain_worker()
        self.assertEqual(play.call_args_list, [call("Failed request"), call("Next request")])
        output.assert_called_once_with("[Voice] Playback error: synthetic device error")


class LiveSpeechWithoutLegacyEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_speech_and_error_recovery_do_not_use_optional_tts(self):
        sent = asyncio.Queue()

        async def send_content(**kwargs):
            await sent.put(kwargs)

        live = JarvisLive.__new__(JarvisLive)
        live._loop = asyncio.get_running_loop()
        live.session = SimpleNamespace(send_client_content=send_content)
        live.ui = Mock()
        with patch.dict(sys.modules, {"pyttsx3": None}):
            live.speak("Speak through Live")
            request = await asyncio.wait_for(sent.get(), timeout=1)
            self.assertEqual(request, {
                "turns": {"role": "user", "parts": [{"text": "Speak through Live"}]},
                "turn_complete": True,
            })
            live.speak_error("test tool", "synthetic failure")
            error_request = await asyncio.wait_for(sent.get(), timeout=1)
            self.assertEqual(error_request["turns"]["parts"][0]["text"],
                             "Sir, test tool encountered an error. synthetic failure")
        live.ui.write_log.assert_called_once_with("ERR: test tool — synthetic failure")
