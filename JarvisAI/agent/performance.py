"""Small, bounded performance telemetry for the autonomous task runner."""

from __future__ import annotations

import threading
from collections import deque
from typing import Any


class PerformanceMonitor:
    """Keep aggregate timing counters only; never retain task prompts or outputs."""

    def __init__(self, *, history: int = 64):
        self._durations: deque[float] = deque(maxlen=max(8, min(int(history), 128)))
        self._completed = 0
        self._failed = 0
        self._cancelled = 0
        self._lock = threading.Lock()

    def record(self, *, duration_s: float, state: str) -> None:
        duration = max(0.0, min(float(duration_s), 86400.0))
        with self._lock:
            self._durations.append(duration)
            if state == "completed":
                self._completed += 1
            elif state == "failed":
                self._failed += 1
            elif state == "cancelled":
                self._cancelled += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            durations = list(self._durations)
            completed = self._completed
            failed = self._failed
            cancelled = self._cancelled
        total = completed + failed + cancelled
        ordered = sorted(durations)
        p95_index = max(0, int((len(ordered) - 1) * 0.95)) if ordered else 0
        return {
            "samples": len(durations),
            "last_duration_s": round(durations[-1], 3) if durations else 0.0,
            "average_duration_s": round(sum(durations) / len(durations), 3)
            if durations else 0.0,
            "p95_duration_s": round(ordered[p95_index], 3) if ordered else 0.0,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "success_rate": round(completed / total, 4) if total else 0.0,
        }
