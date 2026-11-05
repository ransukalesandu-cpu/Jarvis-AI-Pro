"""Real system telemetry for the web UI (psutil). No Qt, no invented values."""
from __future__ import annotations

import time
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover - psutil is a hard requirement of the app
    psutil = None  # type: ignore[assignment]


class Telemetry:
    """Samples CPU, RAM, disk, battery and network throughput. Cheap, non-blocking, one call per second."""

    def __init__(self, disk_every: float = 15.0):
        self._disk_every = disk_every
        self._disk_at = 0.0
        self._disk: float | None = None
        self._net_prev: tuple[float, int, int] | None = None
        if psutil is not None:
            psutil.cpu_percent(None)  # prime the interval counter so the first real read is meaningful

    def snapshot(self) -> dict[str, Any] | None:
        if psutil is None:
            return None
        now = time.monotonic()
        cpu = float(psutil.cpu_percent(None))
        ram = float(psutil.virtual_memory().percent)
        if now - self._disk_at >= self._disk_every:
            self._disk_at = now
            try:
                import os
                self._disk = float(psutil.disk_usage(os.path.abspath(os.sep)).percent)
            except Exception:
                self._disk = None
        battery = None
        try:
            b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
            if b is not None:
                battery = {"percent": max(0.0, min(100.0, float(b.percent))), "charging": bool(b.power_plugged)}
        except Exception:
            battery = None
        net = None
        try:
            c = psutil.net_io_counters()
            if c is not None:
                if self._net_prev is not None:
                    t0, s0, r0 = self._net_prev
                    dt = max(1e-3, now - t0)
                    net = {"upKBps": max(0.0, (c.bytes_sent - s0) / 1024 / dt), "downKBps": max(0.0, (c.bytes_recv - r0) / 1024 / dt)}
                self._net_prev = (now, c.bytes_sent, c.bytes_recv)
        except Exception:
            net = None
        return {"cpu": max(0.0, min(100.0, cpu)), "ram": max(0.0, min(100.0, ram)), "disk": self._disk, "battery": battery, "net": net}
