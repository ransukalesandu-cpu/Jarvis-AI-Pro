import queue
import unittest
from unittest.mock import patch

from core.runtime_diagnostics import hybrid_runtime_snapshot, queue_depth


class HybridRuntimeDiagnosticsTests(unittest.TestCase):
    def test_snapshot_contains_only_safe_runtime_fields(self):
        audio = queue.Queue()
        audio.put(b"pcm")
        with patch("core.runtime_diagnostics.process_rss_mb", return_value=123.4):
            snapshot = hybrid_runtime_snapshot(
                provider="groq", latency_ms=12.345, audio_queue=audio, is_speaking=True
            )
        self.assertEqual(snapshot, {
            "rss_mb": 123.4,
            "audio_queue_depth": 1,
            "provider": "groq",
            "latency_ms": 12.35,
            "playback_state": "speaking",
        })
        self.assertNotIn("prompt", snapshot)
        self.assertNotIn("api_key", snapshot)

    def test_missing_queue_is_zero_depth(self):
        self.assertEqual(queue_depth(None), 0)

    def test_unreadable_queue_depth_is_nonfatal(self):
        class BrokenQueue:
            def qsize(self):
                raise RuntimeError("unavailable")
        self.assertIsNone(queue_depth(BrokenQueue()))


if __name__ == "__main__":
    unittest.main()
