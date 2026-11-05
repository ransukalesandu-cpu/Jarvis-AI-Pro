"""Workstream E: performance tiers and the frame governor."""
import unittest

from jarvis.core import ui_perf


class TierTests(unittest.TestCase):
    def test_auto_tier_from_hardware(self):
        self.assertEqual(ui_perf.auto_tier(cpu_count=2, ram_gb=16), "lite")
        self.assertEqual(ui_perf.auto_tier(cpu_count=8, ram_gb=4), "lite")
        self.assertEqual(ui_perf.auto_tier(cpu_count=4, ram_gb=8), "balanced")
        self.assertEqual(ui_perf.auto_tier(cpu_count=12, ram_gb=32), "full")
        self.assertEqual(ui_perf.resolve("lite"), "lite")
        self.assertIn(ui_perf.resolve("nonsense"), ui_perf.TIERS)

    def test_tiers_get_lighter(self):
        full, bal, lite = (ui_perf.TIERS[k] for k in ("full", "balanced", "lite"))
        self.assertGreater(full.fps, bal.fps)
        self.assertGreater(bal.fps, lite.fps)
        self.assertLess(lite.wires, full.wires)
        self.assertFalse(lite.pulses or lite.bloom)
        self.assertEqual(lite.interval_ms, 50)


class GovernorTests(unittest.TestCase):
    def test_steps_down_when_frames_run_long(self):
        gov = ui_perf.FrameGovernor("full", window=20)
        changes = [gov.record(30.0) for _ in range(20)]
        self.assertEqual(changes[-1], "balanced")
        self.assertEqual(gov.tier, "balanced")

    def test_steps_back_up_but_not_past_the_ceiling(self):
        gov = ui_perf.FrameGovernor("lite", ceiling="balanced", window=10)
        new = None
        for _ in range(200):
            new = gov.record(1.0) or new
        self.assertEqual(gov.tier, "balanced")
        for _ in range(500):
            gov.record(1.0)
        self.assertEqual(gov.tier, "balanced")      # auto chose balanced: stay there

    def test_pinned_tier_never_moves(self):
        gov = ui_perf.FrameGovernor("full", pinned=True, window=10)
        for _ in range(100):
            self.assertIsNone(gov.record(500.0))
        self.assertEqual(gov.tier, "full")


if __name__ == "__main__":
    unittest.main()
