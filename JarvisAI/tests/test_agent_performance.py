"""Tests for bounded, privacy-preserving task performance telemetry."""

import unittest

from agent.performance import PerformanceMonitor


class PerformanceMonitorTests(unittest.TestCase):
    def test_snapshot_reports_bounded_aggregate_metrics(self):
        monitor = PerformanceMonitor(history=8)
        monitor.record(duration_s=1.25, state="completed")
        monitor.record(duration_s=2.75, state="failed")
        monitor.record(duration_s=0.5, state="cancelled")

        result = monitor.snapshot()

        self.assertEqual(result["samples"], 3)
        self.assertEqual(result["last_duration_s"], 0.5)
        self.assertEqual(result["average_duration_s"], 1.5)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["cancelled"], 1)
        self.assertAlmostEqual(result["success_rate"], 1 / 3, places=4)

    def test_history_is_bounded_and_does_not_store_objectives(self):
        monitor = PerformanceMonitor(history=8)
        for index in range(20):
            monitor.record(duration_s=index, state="completed")

        result = monitor.snapshot()

        self.assertEqual(result["samples"], 8)
        self.assertEqual(result["last_duration_s"], 19.0)
        self.assertNotIn("objective", result)
        self.assertNotIn("output", result)

    def test_invalid_extreme_duration_is_clamped(self):
        monitor = PerformanceMonitor()
        monitor.record(duration_s=-5, state="completed")
        monitor.record(duration_s=999999, state="completed")

        result = monitor.snapshot()

        self.assertEqual(result["last_duration_s"], 86400.0)
        self.assertEqual(result["samples"], 2)


if __name__ == "__main__":
    unittest.main()
