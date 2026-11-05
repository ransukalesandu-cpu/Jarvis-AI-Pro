"""Resource monitoring: RAM / CPU / thread counts for this process (psutil).

Used for the Phase 0 baseline (docs/computer-control/PERFORMANCE_REPORT.md),
the before/after measurement of every integration, and the benchmark suite.
psutil is a declared dependency; when it is missing every number is ``None``
and the report says so instead of inventing a value.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Sample:
    t: float
    rss_mb: Optional[float]
    cpu_percent: Optional[float]
    threads: Optional[int]


@dataclass
class Summary:
    samples: int
    rss_start_mb: Optional[float]
    rss_end_mb: Optional[float]
    rss_peak_mb: Optional[float]
    cpu_avg_percent: Optional[float]
    cpu_peak_percent: Optional[float]
    threads_peak: Optional[int]
    duration_s: float
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _process():
    try:
        import psutil
        return psutil.Process(os.getpid())
    except Exception:
        return None


def snapshot() -> Sample:
    proc = _process()
    if proc is None:
        return Sample(time.monotonic(), None, None, None)
    try:
        with proc.oneshot():
            return Sample(time.monotonic(), round(proc.memory_info().rss / 1048576, 1),
                          proc.cpu_percent(None), proc.num_threads())
    except Exception:
        return Sample(time.monotonic(), None, None, None)


class ResourceMonitor:
    """Sample this process every ``interval`` seconds on a daemon thread."""

    def __init__(self, interval: float = 0.25, max_samples: int = 4000) -> None:
        self.interval = max(0.05, float(interval))
        self.max_samples = max_samples
        self._samples: list[Sample] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._proc = _process()
        self._started = 0.0

    def _sample(self) -> None:
        if self._proc is None:
            return
        try:
            with self._proc.oneshot():
                sample = Sample(time.monotonic(), round(self._proc.memory_info().rss / 1048576, 1),
                                self._proc.cpu_percent(None), self._proc.num_threads())
        except Exception:
            return
        if len(self._samples) < self.max_samples:
            self._samples.append(sample)

    def start(self) -> "ResourceMonitor":
        self._started = time.monotonic()
        if self._proc is not None:
            self._proc.cpu_percent(None)      # prime: the first reading is always 0.0
        self._sample()

        def loop() -> None:
            while not self._stop.wait(self.interval):
                self._sample()

        self._thread = threading.Thread(target=loop, name="cc-resource-monitor", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> Summary:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._sample()
        return self.summary()

    def __enter__(self) -> "ResourceMonitor":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def summary(self) -> Summary:
        rss = [s.rss_mb for s in self._samples if s.rss_mb is not None]
        # skip the priming sample for CPU
        cpu = [s.cpu_percent for s in self._samples[1:] if s.cpu_percent is not None]
        threads = [s.threads for s in self._samples if s.threads is not None]
        return Summary(
            samples=len(self._samples),
            rss_start_mb=rss[0] if rss else None,
            rss_end_mb=rss[-1] if rss else None,
            rss_peak_mb=max(rss) if rss else None,
            cpu_avg_percent=round(sum(cpu) / len(cpu), 1) if cpu else None,
            cpu_peak_percent=max(cpu) if cpu else None,
            threads_peak=max(threads) if threads else None,
            duration_s=round(time.monotonic() - self._started, 3) if self._started else 0.0,
        )
