"""Regression tests for the optional JARVIS RAM profiler."""

import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil

from tools import profile_ram


class TestRamProfiler(unittest.TestCase):
    def test_cpu_counter_is_primed_once_and_process_handle_is_reused(self):
        process = Mock()
        process.pid = 42
        process.create_time.return_value = 123.0
        process.memory_info.return_value = SimpleNamespace(rss=2048)
        process.memory_full_info.return_value = SimpleNamespace(uss=1024)
        process.cpu_percent.side_effect = [0.0, 17.5]
        cache = {}
        primed = set()

        with (
            patch.object(profile_ram, "_process_tree", side_effect=[[process], [Mock(pid=42, create_time=Mock(return_value=123.0))]]),
            patch.object(profile_ram.psutil, "virtual_memory", return_value=SimpleNamespace(available=4096)),
        ):
            first = profile_ram._memory_sample(42, cache, primed)
            second = profile_ram._memory_sample(42, cache, primed)

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
            patch.object(profile_ram, "_process_tree", return_value=[process]),
            patch.object(profile_ram.psutil, "virtual_memory", return_value=SimpleNamespace(available=4096)),
        ):
            sample = profile_ram._memory_sample(7, {}, set())

        self.assertRegex(sample["timestamp_utc"], re.compile(r"\\.\\d{3}\\+00:00$"))

    def test_unreadable_process_does_not_create_a_zero_ram_sample(self):
        process = Mock()
        process.pid = 9
        process.create_time.return_value = 2.0
        process.memory_info.side_effect = psutil.AccessDenied(pid=9)

        with (
            patch.object(profile_ram, "_process_tree", return_value=[process]),
            patch.object(profile_ram.psutil, "virtual_memory", return_value=SimpleNamespace(available=4096)),
        ):
            sample = profile_ram._memory_sample(9, {}, set())

        self.assertEqual(sample["process_count"], 0)
        self.assertEqual(sample["rss_mb"], 0.0)


if __name__ == "__main__":
    unittest.main()
