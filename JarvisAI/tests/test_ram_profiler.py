"""Tests for the RAM profiler used to measure JARVIS on a 4 GB laptop.

The tool itself must be trustworthy before its numbers are used to justify
changes, so these tests run it against real processes (this interpreter and a
short-lived child) rather than mocks.
"""

import csv
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import unittest

from tools import profile_ram


class TestProcessTree(unittest.TestCase):
    def test_unknown_pid_is_a_clear_value_error(self):
        with self.assertRaises(ValueError) as caught:
            profile_ram.process_tree(999_999_999)
        self.assertIn("999999999", str(caught.exception))

    def test_the_current_process_is_its_own_tree(self):
        tree = profile_ram.process_tree(os.getpid())
        self.assertIn(os.getpid(), [p.pid for p in tree])

    def test_a_child_process_appears_in_the_tree(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        try:
            pids = [p.pid for p in profile_ram.process_tree(os.getpid())]
            self.assertIn(child.pid, pids)
        finally:
            child.terminate()
            child.wait(timeout=10)


class TestMemorySample(unittest.TestCase):
    def test_a_sample_reports_every_column(self):
        sample = profile_ram.memory_sample(os.getpid())
        self.assertEqual(
            set(sample),
            {"timestamp_utc", "process_count", "rss_mb", "uss_mb",
             "cpu_percent_sum", "system_available_mb"},
        )
        self.assertGreaterEqual(sample["process_count"], 1)
        self.assertGreater(sample["rss_mb"], 0.0)
        self.assertGreater(sample["system_available_mb"], 0.0)

    def test_a_dead_process_raises_so_the_caller_can_stop(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait(timeout=30)
        with self.assertRaises(ValueError):
            profile_ram.memory_sample(child.pid)


class TestSamplingAccuracy(unittest.TestCase):
    def test_cpu_counter_is_primed_once_and_process_handle_is_reused(self):
        process = Mock()
        process.pid = 42
        process.create_time.return_value = 123.0
        process.memory_info.return_value = SimpleNamespace(rss=2048)
        process.memory_full_info.return_value = SimpleNamespace(uss=1024)
        process.cpu_percent.side_effect = [0.0, 17.5]
        replacement = Mock()
        replacement.pid = 42
        replacement.create_time.return_value = 123.0
        cache = {}
        primed = set()

        with (
            patch.object(profile_ram, "process_tree", side_effect=[[process], [replacement]]),
            patch.object(
                profile_ram.psutil, "virtual_memory",
                return_value=SimpleNamespace(available=4096),
            ),
        ):
            first = profile_ram.memory_sample(42, cache, primed)
            second = profile_ram.memory_sample(42, cache, primed)

        self.assertEqual(first["cpu_percent_sum"], 0.0)
        self.assertEqual(second["cpu_percent_sum"], 17.5)
        self.assertIs(cache[42], process)
        self.assertEqual(process.cpu_percent.call_count, 2)

    def test_timestamp_preserves_millisecond_precision(self):
        process = Mock()
        process.pid = 7
        process.create_time.return_value = 1.0
        process.memory_info.return_value = SimpleNamespace(rss=1024)
        process.memory_full_info.return_value = SimpleNamespace(uss=512)
        process.cpu_percent.return_value = 0.0
        with (
            patch.object(profile_ram, "process_tree", return_value=[process]),
            patch.object(
                profile_ram.psutil, "virtual_memory",
                return_value=SimpleNamespace(available=4096),
            ),
        ):
            sample = profile_ram.memory_sample(7, {}, set())
        self.assertRegex(sample["timestamp_utc"], r"\.\d{3}\+00:00$")

    def test_process_with_unreadable_memory_is_not_counted(self):
        process = Mock()
        process.pid = 9
        process.create_time.return_value = 2.0
        process.memory_info.side_effect = profile_ram.psutil.AccessDenied(pid=9)
        with (
            patch.object(profile_ram, "process_tree", return_value=[process]),
            patch.object(
                profile_ram.psutil, "virtual_memory",
                return_value=SimpleNamespace(available=4096),
            ),
        ):
            sample = profile_ram.memory_sample(9, {}, set())
        self.assertEqual(sample["process_count"], 0)
        self.assertEqual(sample["rss_mb"], 0.0)

    def test_command_skips_empty_samples_and_returns_no_data(self):
        import tempfile

        empty_sample = {
            "timestamp_utc": "t", "process_count": 0, "rss_mb": 0.0,
            "uss_mb": "", "cpu_percent_sum": 0.0,
            "system_available_mb": 4096.0,
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(profile_ram, "process_tree", return_value=[Mock(pid=10)]),
            patch.object(profile_ram, "memory_sample", return_value=empty_sample),
            patch.object(profile_ram.time, "monotonic", side_effect=[0.0, 2.0]),
        ):
            output = Path(tmp) / "empty.csv"
            result = profile_ram.main([
                "--pid", "10", "--duration", "1", "--output", str(output),
            ])
        self.assertEqual(result, 2)
        self.assertFalse(output.exists())


class TestSummarise(unittest.TestCase):
    @staticmethod
    def _row(rss, uss, available):
        return {"rss_mb": rss, "uss_mb": uss, "system_available_mb": available}

    def test_empty_input_has_no_summary(self):
        self.assertEqual(profile_ram.summarise([]), {})

    def test_it_reports_min_average_peak_and_low_water_mark(self):
        stats = profile_ram.summarise([
            self._row(100.0, 90.0, 900.0),
            self._row(120.0, 110.0, 700.0),
            self._row(80.0, 70.0, 800.0),
        ])
        self.assertEqual(stats["samples"], 3)
        self.assertEqual(stats["rss_min_mb"], 80.0)
        self.assertEqual(stats["rss_peak_mb"], 120.0)
        self.assertAlmostEqual(stats["rss_avg_mb"], 100.0)
        self.assertEqual(stats["uss_peak_mb"], 110.0)
        self.assertEqual(stats["system_available_min_mb"], 700.0)

    def test_rows_without_uss_are_tolerated(self):
        stats = profile_ram.summarise([self._row(100.0, "", 900.0)])
        self.assertEqual(stats["uss_peak_mb"], 0.0)


class TestCsvOutput(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "nested" / "profile.csv"
        self.rows = [{"timestamp_utc": "t1", "rss_mb": 1.0, "label": "idle"}]

    def test_it_creates_parent_directories(self):
        profile_ram.write_csv(self.path, self.rows)
        self.assertTrue(self.path.is_file())

    def test_appending_keeps_one_header_and_adds_rows(self):
        profile_ram.write_csv(self.path, self.rows)
        profile_ram.write_csv(self.path, [{"timestamp_utc": "t2", "rss_mb": 2.0, "label": "voice"}],
                              append=True)
        with self.path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["label"] for row in rows], ["idle", "voice"])

    def test_writing_without_append_replaces_the_file(self):
        profile_ram.write_csv(self.path, self.rows)
        profile_ram.write_csv(self.path, [{"timestamp_utc": "t9", "rss_mb": 9.0, "label": "screen"}])
        with self.path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "screen")


class TestCommandLine(unittest.TestCase):
    def test_an_invalid_pid_is_rejected_by_the_parser(self):
        with self.assertRaises(SystemExit) as caught:
            profile_ram.main(["--pid", "0"])
        self.assertEqual(caught.exception.code, 2)

    def test_an_out_of_range_duration_is_rejected(self):
        with self.assertRaises(SystemExit):
            profile_ram.main(["--pid", str(os.getpid()), "--duration", "0.1"])

    def test_a_short_sample_against_this_process_writes_a_csv(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sample.csv"
            code = profile_ram.main([
                "--pid", str(os.getpid()),
                "--duration", "1", "--interval", "0.3",
                "--label", "unit-test", "--output", str(out),
            ])
            self.assertEqual(code, 0)
            with out.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "unit-test")
        self.assertIn("rss_mb", rows[0])


if __name__ == "__main__":
    unittest.main()
