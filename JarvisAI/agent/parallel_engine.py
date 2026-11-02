"""Bounded, dependency-agnostic worker pool for safe parallel agent steps.

The caller is responsible for selecting steps that are genuinely independent
and safe to run together. This engine only supplies bounded concurrency,
cancellation-aware dispatch, exception isolation, and deterministic result order.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from threading import Event
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


class ParallelStepEngine:
    """Execute a batch with a hard worker cap and stable result ordering."""

    MAX_WORKERS = 4

    def __init__(self, *, max_workers: int = 3):
        self.max_workers = max(1, min(int(max_workers), self.MAX_WORKERS))

    def run(
        self,
        items: Iterable[T],
        worker: Callable[[T], R],
        *,
        cancel_event: Event | None = None,
        on_error: Callable[[T, Exception], R] | None = None,
        on_cancel: Callable[[T], R] | None = None,
    ) -> list[tuple[T, R]]:
        """Run at most max_workers items at once and return input-order results.

        Once cancellation is observed no new work is submitted. Already-running
        workers are allowed to observe the shared cancellation event and finish.
        Unsubmitted items are represented through on_cancel when supplied.
        """
        batch = list(items)
        if not batch:
            return []

        results: list[R | None] = [None] * len(batch)
        completed: set[int] = set()
        active: dict[Future[R], int] = {}
        next_index = 0
        worker_count = min(self.max_workers, len(batch))

        def submit_available(pool: ThreadPoolExecutor) -> None:
            nonlocal next_index
            while next_index < len(batch) and len(active) < worker_count:
                if cancel_event is not None and cancel_event.is_set():
                    return
                index = next_index
                next_index += 1
                active[pool.submit(worker, batch[index])] = index

        with ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="jarvis-agent-step"
        ) as pool:
            submit_available(pool)
            while active:
                done, _ = wait(tuple(active), return_when=FIRST_COMPLETED)
                for future in sorted(done, key=lambda item: active[item]):
                    index = active.pop(future)
                    try:
                        results[index] = future.result()
                    except Exception as exc:
                        if on_error is None:
                            raise
                        results[index] = on_error(batch[index], exc)
                    completed.add(index)
                submit_available(pool)

        if next_index < len(batch) and on_cancel is not None:
            for index in range(next_index, len(batch)):
                results[index] = on_cancel(batch[index])
                completed.add(index)

        if len(completed) != len(batch):
            missing = [index for index in range(len(batch)) if index not in completed]
            raise RuntimeError(f"Parallel step engine lost results for indexes: {missing}")
        return [(item, results[index]) for index, item in enumerate(batch)]  # type: ignore[misc]
