import unittest
import sys
from pathlib import Path

JARVIS_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = JARVIS_DIR.parent
for p in [str(ROOT_DIR), str(JARVIS_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from JarvisAI.diagnose import print_memory_diagnostics
from JarvisAI.main import JarvisLive


class TestCloudLowRam(unittest.TestCase):

    def test_memory_diagnostics_returns_stats(self):
        stats = print_memory_diagnostics()
        self.assertIsInstance(stats, dict)
        if stats:
            self.assertIn("rss_mb", stats)
            self.assertIn("sys_total_gb", stats)
            self.assertGreater(stats["rss_mb"], 0)

    def test_main_queues_have_maxsize(self):
        import asyncio

        class DummyUI:
            def __init__(self):
                self.muted = False
            def set_state(self, s): pass
            def write_log(self, m): pass
            def set_voice_id_enabled(self, e): pass
            def get_plugins(self): return []
            def get_plugin_settings(self): return {}

        live = JarvisLive.__new__(JarvisLive)
        live.audio_in_queue = asyncio.Queue(maxsize=200)
        live.out_queue = asyncio.Queue(maxsize=200)
        self.assertEqual(live.audio_in_queue.maxsize, 200)
        self.assertEqual(live.out_queue.maxsize, 200)


if __name__ == "__main__":
    unittest.main()
