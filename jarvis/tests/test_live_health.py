"""Live-session telemetry and the read-only self_check tool."""
from __future__ import annotations

import unittest

from jarvis.actions import self_check
from jarvis.core import live_health, security


class LiveHealthTests(unittest.TestCase):
    def setUp(self):
        live_health.reset_for_tests()
        self.addCleanup(live_health.reset_for_tests)

    def test_counts_and_window(self):
        live_health.record("connected")
        live_health.record("unexpected_drop", "ConnectionClosed")
        live_health.record("voluntary_reconnect", "voice change")
        live_health.record("nonsense")                      # ignored
        snap = live_health.snapshot()
        self.assertEqual(snap["totals"]["connected"], 1)
        self.assertEqual(snap["totals"]["unexpected_drop"], 1)
        self.assertEqual(snap["last_detail"]["unexpected_drop"], "ConnectionClosed")
        later = live_health.snapshot(window_s=60, now=snap["uptime_s"] + 10**10)
        self.assertEqual(later["last_window"]["unexpected_drop"], 0)
        self.assertEqual(later["totals"]["unexpected_drop"], 1)

    def test_describe_warns_on_instability(self):
        for _ in range(3):
            live_health.record("unexpected_drop")
        self.assertIn("looks unstable", live_health.describe())
        live_health.reset_for_tests()
        live_health.record("connected")
        self.assertNotIn("unstable", live_health.describe())

    def test_self_check_tool_is_safe_and_reports(self):
        live_health.record("connected")
        text = self_check.self_check({})
        self.assertIn("1 connects", text)
        self.assertIn("Handled internal errors", text)
        self.assertEqual(security.tier_for("self_check", {}), security.TIER_SAFE)
        self.assertEqual(self_check.TOOL["name"], "self_check")


if __name__ == "__main__":
    unittest.main()
