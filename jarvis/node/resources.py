"""Coarse resource summary of the node: enough to place jobs, nothing personal.

Only machine-wide numbers are reported (CPU %, available/total RAM, free disk in the
node's state folder, whether an NVIDIA GPU tool is present). No process list, user
name, hostname, path or network detail ever leaves the node.
"""
from __future__ import annotations

import shutil
from pathlib import Path


def snapshot(state_dir: Path) -> dict:
    try:
        import psutil
        cpu = float(psutil.cpu_percent(interval=None))
        vm = psutil.virtual_memory()
        avail, total = vm.available / 1e6, vm.total / 1e6
    except Exception:
        cpu, avail, total = 0.0, 0.0, 0.0
    try:
        free = shutil.disk_usage(str(state_dir)).free / 1e9
    except OSError:
        free = 0.0
    return {
        "cpu_percent": round(min(max(cpu, 0.0), 100.0), 0),
        "ram_available_mb": round(avail, -1),
        "ram_total_mb": round(total, -1),
        "disk_free_gb": round(free, 1),
        "gpu": shutil.which("nvidia-smi") is not None,
    }
