"""Measured cost of the web UI: what the page reports about its own rendering, plus the CPU and RAM
of the QtWebEngine processes that draw it (psutil). No Qt here; nothing is estimated.
"""
from __future__ import annotations

import os
import time
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover - psutil is a hard requirement of the app
    psutil = None  # type: ignore[assignment]

WEB_PROCESS = "qtwebengineprocess"
MIN_INTERVAL_S = 1.0       # the page reports every 2 s while the overlay is open; never sample faster than this


class RenderPerf:
    """Keeps the latest page report and samples the web engine's helper processes on request."""

    def __init__(self, root_pid: int | None = None, clock=time.monotonic):
        self._root = root_pid or os.getpid()
        self._clock = clock
        self._procs: dict[int, Any] = {}
        self._at = -MIN_INTERVAL_S
        self.page: dict | None = None
        self.host: dict | None = None

    def on_page(self, perf: dict) -> dict | None:
        """Store the page's numbers; return a fresh host sample, or None when throttled or unmeasurable."""
        self.page = {k: perf[k] for k in ("fps", "frameMs", "drawCalls", "triangles", "heapMb", "dpr") if k in perf}
        now = self._clock()
        if now - self._at < MIN_INTERVAL_S:
            return None
        self._at = now
        self.host = self.sample()
        return self.host

    def sample(self) -> dict | None:
        """CPU (% of the whole machine, like Task Manager) and resident RAM of QtWebEngineProcess children."""
        if psutil is None:
            return None
        try:
            kids = psutil.Process(self._root).children(recursive=True)
        except Exception:
            return None
        live: dict[int, Any] = {}
        cpu = 0.0
        ram = 0
        for p in kids:
            try:
                if not p.name().lower().startswith(WEB_PROCESS):
                    continue
                known = self._procs.get(p.pid)
                if known is None:
                    p.cpu_percent(None)        # first call primes the counter (reads 0); real value next time
                    known = p
                else:
                    cpu += known.cpu_percent(None)
                ram += known.memory_info().rss
                live[p.pid] = known
            except Exception:  # noqa: S112 - a helper process can exit between listing and reading
                continue
        self._procs = live
        cores = psutil.cpu_count() or 1
        return {"cpu": round(min(100.0, cpu / cores), 1), "ramMb": round(ram / 1048576, 1), "processes": min(64, len(live))}
