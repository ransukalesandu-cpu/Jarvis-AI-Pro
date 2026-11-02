"""Tests for bounded, ordered, cancellation-aware parallel agent execution."""

import threading
import time
import unittest

from agent.parallel_engine import ParallelStepEngine


class ParallelStepEngineTests(unittest.TestCase):
    def test_worker_count_never_exceeds_configured_bound(self):
        lock = threading.Lock()
        active = 0
        maximum = 0

        def worker(item):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return item * 2

        engine = ParallelStepEngine(max_workers=2)
        results = engine.run(range(8), worker)

        self.assertEqual(maximum, 2)
        self.assertEqual(results, [(item, item * 2) for item in range(8)])

    def test_results_keep_input_order_when_workers_finish_out_of_order(self):
        def worker(item):
            time.sleep((3 - item) * 0.01)
            return str(item)

        results = ParallelStepEngine(max_workers=3).run([0, 1, 2], worker)

        self.assertEqual(results, [(0, "0"), (1, "1"), (2, "2")])

    def test_worker_exception_is_isolated_by_error_handler(self):
        def worker(item):
            if item == "bad":
                raise ValueError("expected")
            return item

        results = ParallelStepEngine(max_workers=2).run(
            ["ok", "bad", "later"],
            worker,
            on_error=lambda item, exc: f"{item}:{type(exc).__name__}",
        )

        self.assertEqual(results, [
            ("ok", "ok"),
            ("bad", "bad:ValueError"),
            ("later", "later"),
        ])

    def test_cancellation_stops_dispatching_queued_items(self):
        cancel = threading.Event()
        started = []

        def worker(item):
            started.append(item)
            cancel.set()
            return item

        results = ParallelStepEngine(max_workers=1).run(
            [1, 2, 3],
            worker,
            cancel_event=cancel,
            on_cancel=lambda item: f"cancelled:{item}",
        )

        self.assertEqual(started, [1])
        self.assertEqual(results, [
            (1, 1),
            (2, "cancelled:2"),
            (3, "cancelled:3"),
        ])

    def test_worker_limit_is_clamped_to_safe_maximum(self):
        self.assertEqual(ParallelStepEngine(max_workers=99).max_workers, 4)
        self.assertEqual(ParallelStepEngine(max_workers=0).max_workers, 1)


if __name__ == "__main__":
    unittest.main()
