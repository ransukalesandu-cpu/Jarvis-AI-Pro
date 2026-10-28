"""Tests for battery, health, adaptive-performance and notification logic.

``core/system_status.py`` is Qt-free on purpose: every rule that decides what the
HUD is allowed to claim (low battery, degraded visuals, "microphone failed") is
verifiable here without a GUI, and the tests use fake readers/probes so nothing
depends on the machine running them.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import unittest

from unittest.mock import patch

from core.subsystem_probes import (
    ProbeResult,
    SubsystemProber,
    default_probes,
    probe_network,
    probe_provider,
)
from core.system_status import (
    AdaptivePerformance,
    BatteryMonitor,
    BatteryReading,
    BatteryThresholds,
    HealthMonitor,
    HealthState,
    Notification,
    NotificationCenter,
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    SubsystemStatus,
)


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestBatteryThresholds(unittest.TestCase):
    def test_validation_keeps_the_bands_ordered(self):
        bad = BatteryThresholds(fifty=20, low=80, critical=90, full=10).validated()
        self.assertGreaterEqual(bad.fifty, 30)
        self.assertLess(bad.low, bad.fifty)
        self.assertLess(bad.critical, bad.low)
        self.assertGreater(bad.full, bad.fifty)
        self.assertLessEqual(bad.full, 100)
        # Junk values must not produce a "full" band below the normal range.
        self.assertGreaterEqual(bad.full, 80)

    def test_level_names(self):
        thresholds = BatteryThresholds()
        self.assertEqual(thresholds.level_name(100), "full")
        self.assertEqual(thresholds.level_name(70), "normal")
        self.assertEqual(thresholds.level_name(45), "fifty")
        self.assertEqual(thresholds.level_name(25), "low")
        self.assertEqual(thresholds.level_name(10), "critical")


class TestBatteryMonitor(unittest.TestCase):
    def _monitor(self, readings):
        queue = list(readings)

        def reader():
            return queue.pop(0) if queue else BatteryReading(available=False)

        return BatteryMonitor(reader=reader)

    def test_no_battery_sensor_reports_nothing(self):
        monitor = self._monitor([BatteryReading(available=False)] * 3)
        self.assertEqual(monitor.poll(), [])
        self.assertFalse(monitor.reading.available)
        self.assertEqual(monitor.band(), "unavailable")
        # Crucially, unavailable is not 0 %: no fabricated threshold event.
        self.assertIsNone(monitor.reading.percent)

    def test_unplug_and_replug_are_edge_triggered(self):
        monitor = self._monitor([
            BatteryReading(True, 80, True),
            BatteryReading(True, 80, True),
            BatteryReading(True, 79, False),
            BatteryReading(True, 78, False),
            BatteryReading(True, 78, True),
        ])
        kinds = []
        for _ in range(5):
            kinds.append([event.kind for event in monitor.poll()])
        self.assertEqual(kinds[0], [])          # first sample: no edge event
        self.assertEqual(kinds[1], [])          # steady state stays silent
        self.assertEqual(kinds[2], ["unplugged"])
        self.assertEqual(kinds[3], [])          # still unplugged, still silent
        self.assertEqual(kinds[4], ["charging"])

    def test_thresholds_fire_once_each_downward(self):
        monitor = self._monitor([
            BatteryReading(True, 60, False),
            BatteryReading(True, 45, False),
            BatteryReading(True, 44, False),
            BatteryReading(True, 20, False),
            BatteryReading(True, 9, False),
            BatteryReading(True, 8, False),
        ])
        events = [event for _ in range(6) for event in monitor.poll()]
        levels = [(event.kind, event.level) for event in events]
        self.assertIn(("threshold", "fifty"), levels)
        self.assertIn(("threshold", "low"), levels)
        self.assertIn(("threshold", "critical"), levels)
        # 44 %, 8 % must not re-announce the band they are already inside.
        self.assertEqual(levels.count(("threshold", "fifty")), 1)
        self.assertEqual(levels.count(("threshold", "low")), 1)
        self.assertEqual(levels.count(("threshold", "critical")), 1)
        critical = [e for e in events if e.level == "critical"]
        self.assertEqual(critical[0].priority, PRIORITY_CRITICAL)

    def test_full_event_only_when_charged(self):
        monitor = self._monitor([
            BatteryReading(True, 95, True),
            BatteryReading(True, 100, True),
        ])
        monitor.poll()
        kinds = [event.kind for event in monitor.poll()]
        self.assertIn("full", kinds)

    def test_custom_thresholds_are_used(self):
        monitor = BatteryMonitor(
            reader=lambda: BatteryReading(True, 55, False),
            thresholds=BatteryThresholds(fifty=60, low=30, critical=15, full=100),
        )
        events = monitor.poll()
        self.assertEqual([(e.kind, e.level) for e in events], [("threshold", "fifty")])


class TestHealthMonitor(unittest.TestCase):
    def test_exception_probe_is_unavailable_not_a_crash(self):
        def boom():
            raise RuntimeError("boom")

        monitor = HealthMonitor({"microphone": boom})
        state, notes = monitor.poll()
        self.assertEqual(state.microphone.state, "unavailable")
        self.assertFalse(state.microphone.available)
        self.assertIn("RuntimeError", state.microphone.detail)
        self.assertEqual(notes, [])

    def test_failure_then_recovery_notifications(self):
        status = {"value": (True, False, "no input device")}
        monitor = HealthMonitor({"microphone": lambda: status["value"]})
        state, notes = monitor.poll()
        self.assertEqual(state.microphone.state, "error")
        self.assertEqual([note.priority for note in notes], [PRIORITY_HIGH])
        self.assertIn("microphone", notes[0].key)

        state, notes = monitor.poll()
        self.assertEqual(notes, [], "unchanged failure must not re-alert")

        status["value"] = (True, True, "1 input device")
        state, notes = monitor.poll()
        self.assertEqual(state.microphone.state, "ok")
        self.assertEqual(len(notes), 1)
        self.assertIn("restored", notes[0].title.lower())

    def test_all_ok_ignores_unavailable_subsystems(self):
        def unavailable():
            return (False, False, "not applicable")

        def good():
            return (True, True, "fine")

        monitor = HealthMonitor({"microphone": unavailable, "speaker": good})
        state = monitor.snapshot() if hasattr(monitor, "snapshot") else monitor.poll()[0]
        self.assertIsInstance(state, HealthState)
        self.assertTrue(state.all_ok)
        self.assertEqual(state.problems(), [])

    def test_problems_lists_real_failures(self):
        monitor = HealthMonitor({"network": lambda: (True, False, "unreachable")})
        state, _ = monitor.poll()
        problems = state.problems()
        self.assertEqual([p.name for p in problems], ["network"])
        self.assertFalse(state.all_ok)


class TestAdaptivePerformance(unittest.TestCase):
    def test_tiers_by_battery(self):
        perf = AdaptivePerformance()
        self.assertEqual(perf.decide(BatteryReading(True, 90, False)).tier, "full")
        self.assertEqual(perf.decide(BatteryReading(True, 40, False)).tier, "balanced")
        self.assertEqual(perf.decide(BatteryReading(True, 12, False)).tier, "saver")

    def test_charging_disables_degradation(self):
        perf = AdaptivePerformance()
        budget = perf.decide(BatteryReading(True, 8, True))
        self.assertEqual(budget.tier, "full")

    def test_no_battery_means_no_degradation(self):
        perf = AdaptivePerformance()
        self.assertEqual(perf.decide(BatteryReading(available=False)).tier, "full")

    def test_battery_saver_toggle_is_respected(self):
        perf = AdaptivePerformance()
        budget = perf.decide(BatteryReading(True, 5, False), battery_saver_enabled=False)
        self.assertEqual(budget.tier, "full")

    def test_reduced_motion_forces_saver(self):
        perf = AdaptivePerformance()
        budget = perf.decide(BatteryReading(True, 100, False), reduced_motion=True)
        self.assertEqual(budget.tier, "saver")
        self.assertEqual(budget.reason, "reduced motion")

    def test_hysteresis_prevents_thrashing(self):
        perf = AdaptivePerformance(saver_percent=25, balanced_percent=50, hysteresis=5)
        self.assertEqual(perf.decide(BatteryReading(True, 24, False)).tier, "saver")
        # 27 % is above the entry threshold but inside the hysteresis band.
        self.assertEqual(perf.decide(BatteryReading(True, 27, False)).tier, "saver")
        self.assertEqual(perf.decide(BatteryReading(True, 34, False)).tier, "balanced")

    def test_cpu_load_degrades_one_step(self):
        perf = AdaptivePerformance(cpu_probe=lambda: 0.95)
        self.assertEqual(perf.decide(BatteryReading(True, 90, False)).tier, "balanced")

    def test_budget_values_are_bounded(self):
        for tier in ("full", "balanced", "saver"):
            budget = AdaptivePerformance.budget_for(tier)
            self.assertGreater(budget.frame_interval_ms, 0)
            self.assertGreaterEqual(budget.particle_scale, 0.0)
            self.assertLessEqual(budget.particle_scale, 1.0)
            self.assertGreaterEqual(budget.glow_scale, 0.0)
            self.assertLessEqual(budget.glow_scale, 1.0)
        self.assertEqual(AdaptivePerformance.budget_for("full").particle_count(100), 100)
        self.assertLess(AdaptivePerformance.budget_for("saver").particle_count(100), 100)


class TestNotificationCenter(unittest.TestCase):
    def test_identical_text_is_deduplicated(self):
        clock = FakeClock()
        center = NotificationCenter(clock=clock)
        first = center.push(Notification("mic", "Microphone failed", "no device"))
        self.assertEqual(len(first), 1)
        second = center.push(Notification("mic", "Microphone failed", "no device"))
        self.assertEqual(second, [])
        clock.advance(5.0)
        third = center.push(Notification("mic", "Microphone failed", "no device"))
        self.assertEqual(third, [], "cooldown covers repeats inside the window")

    def test_same_key_is_muted_for_its_cooldown(self):
        clock = FakeClock()
        center = NotificationCenter(clock=clock)
        center.push(Notification("mic", "Microphone failed", "no device"))
        # Different wording, same key, still inside the cooldown: suppressed.
        self.assertEqual(center.push(Notification("mic", "Microphone failed", "device busy")), [])
        clock.advance(30.0)
        delivered = center.push(Notification("mic", "Microphone failed", "device busy"))
        self.assertEqual(len(delivered), 1, "new text after the cooldown is real news")
        clock.advance(30.0)
        self.assertEqual(
            center.push(Notification("mic", "Microphone failed", "device busy")), [],
            "identical text never repeats, even after the cooldown",
        )

    def test_queue_is_bounded_and_ordered_by_priority(self):
        center = NotificationCenter(max_items=4, clock=FakeClock())
        center.push(Notification("a", "A", "", PRIORITY_NORMAL))
        center.push(Notification("b", "B", "", PRIORITY_CRITICAL))
        center.push(Notification("c", "C", "", PRIORITY_HIGH))
        center.push(Notification("d", "D", "", PRIORITY_NORMAL))
        center.push(Notification("e", "E", "", PRIORITY_LOW))
        pending = center.pending()
        self.assertEqual(len(pending), 4)
        self.assertEqual(pending[0].key, "b")

    def test_pop_peek_and_forget(self):
        clock = FakeClock()
        center = NotificationCenter(clock=clock)
        center.push(Notification("x", "X"))
        self.assertEqual(center.peek().key, "x")
        self.assertEqual(center.pop().key, "x")
        self.assertIsNone(center.pop())
        center.push(Notification("y", "Y"))
        center.forget("y")
        clock.advance(60.0)
        self.assertEqual(len(center.push(Notification("y", "Y"))), 1)

    def test_critical_priority_flag(self):
        self.assertTrue(Notification("k", "t", "", PRIORITY_CRITICAL).is_critical)
        self.assertFalse(Notification("k", "t", "", PRIORITY_NORMAL).is_critical)
        self.assertEqual(SubsystemStatus("mic", True, True).state, "ok")


class TestSubsystemProbes(unittest.TestCase):
    def test_prober_reports_each_probe_and_isolates_failures(self):
        def boom():
            raise RuntimeError("probe exploded")

        prober = SubsystemProber({
            "microphone": lambda: (True, True, "1 input device"),
            "network": boom,
        })
        result = prober.run_once()
        self.assertIsInstance(result, ProbeResult)
        self.assertEqual(prober.get("microphone"), (True, True, "1 input device"))
        # A broken probe is a broken subsystem, never a crash and never "ok".
        self.assertEqual(prober.get("network")[0], False)
        self.assertIn("RuntimeError", prober.get("network")[2])
        self.assertGreater(prober.finished_at, 0.0)

    def test_unknown_subsystem_is_unavailable(self):
        prober = SubsystemProber({"microphone": lambda: (True, True, "ok")})
        self.assertEqual(prober.get("speaker")[0], False)

    def test_prober_never_blocks_the_caller(self):
        prober = SubsystemProber({})
        self.assertEqual(prober.snapshot(), {})

    def test_start_can_be_disabled_by_environment(self):
        prober = SubsystemProber({"microphone": lambda: (True, True, "ok")})
        with patch.dict("os.environ", {"JARVIS_DISABLE_SUBSYSTEM_PROBES": "1"}):
            prober.start()
        self.assertIsNone(prober._thread, "no thread may be started when disabled")

    def test_start_and_stop_are_idempotent(self):
        calls = []

        def probe():
            calls.append(1)
            return (True, True, "ok")

        prober = SubsystemProber({"microphone": probe}, interval=60.0)
        with patch.dict("os.environ", {"JARVIS_DISABLE_SUBSYSTEM_PROBES": "0"}):
            prober.start()
            first = prober._thread
            prober.start()
            self.assertIs(prober._thread, first)
            prober.stop()
        self.assertIsNone(prober._thread)

    def test_default_probe_set_matches_health_subsystems(self):
        probes = default_probes()
        for name in ("microphone", "speaker", "network", "provider", "audio_stream"):
            self.assertIn(name, probes)
            self.assertTrue(callable(probes[name]))

    def test_provider_probe_requires_a_real_key(self):
        with patch("memory.config_manager.load_api_keys", return_value={"gemini_api_key": ""}):
            available, ok, detail = probe_provider()
        self.assertTrue(available)
        self.assertFalse(ok)
        self.assertIn("no Gemini API key", detail)

        with patch("memory.config_manager.load_api_keys",
                   return_value={"gemini_api_key": "AIza" + "x" * 30}):
            self.assertEqual(probe_provider()[1], True)

    def test_provider_probe_survives_unreadable_config(self):
        with patch("memory.config_manager.load_api_keys", side_effect=OSError("denied")):
            available, ok, detail = probe_provider()
        self.assertTrue(available)
        self.assertFalse(ok)
        self.assertIn("OSError", detail)

    def test_network_probe_reports_unreachable_hosts(self):
        import socket as socket_module

        with patch("core.subsystem_probes.socket.create_connection",
                   side_effect=socket_module.timeout("timed out")):
            available, ok, detail = probe_network(timeout=0.01)
        self.assertTrue(available)
        self.assertFalse(ok)
        self.assertIn("unreachable", detail)


if __name__ == "__main__":
    unittest.main()
