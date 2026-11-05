"""Phase 0 resource baseline (RAM / CPU / latency), measured, never estimated.

Run on the owner's PC (Windows 10/11, 16 GB) and in CI::

    python -m jarvis.computer_control.bench baseline            # table
    python -m jarvis.computer_control.bench baseline --json out.json

Each import measurement runs in a fresh interpreter so the RSS numbers are not
polluted by earlier steps. The numbers go to docs/computer-control/PERFORMANCE_REPORT.md.
"""
from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time

_PROBE = r"""
import json, os, sys, time
import psutil
proc = psutil.Process(os.getpid())
base = proc.memory_info().rss
t0 = time.perf_counter()
for name in {modules!r}:
    __import__(name)
elapsed = time.perf_counter() - t0
after = proc.memory_info().rss
proc.cpu_percent(None)
time.sleep({idle})
idle_cpu = proc.cpu_percent(None)
print(json.dumps({{"rss_before_mb": round(base/1048576, 1), "rss_after_mb": round(after/1048576, 1),
                  "import_s": round(elapsed, 3), "idle_cpu_percent": idle_cpu,
                  "threads": proc.num_threads()}}))
"""

SCENARIOS = {
    "python_bare": [],
    "jarvis_app_modules": ["jarvis.main"],
    "jarvis_app_plus_engine": ["jarvis.main", "jarvis.computer_control.runner",
                               "jarvis.computer_control.tools", "jarvis.actions.computer_control_engine"],
    "engine_only": ["jarvis.computer_control.runner", "jarvis.computer_control.tools"],
}


def _probe(modules: list[str], idle: float = 1.0) -> dict:
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    code = _PROBE.format(modules=modules, idle=idle)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=300, env=env)
    if out.returncode != 0:
        return {"error": (out.stderr or out.stdout).strip().splitlines()[-1:]}
    return json.loads(out.stdout.strip().splitlines()[-1])


def _runner_overhead(n: int = 500) -> dict:
    from jarvis.computer_control import flags
    from jarvis.computer_control.monitoring import ResourceMonitor
    from jarvis.computer_control.policy import ActionPolicy, AuthSnapshot
    from jarvis.computer_control.runner import ActionRunner

    run = ActionRunner(ActionPolicy(auth=lambda: AuthSnapshot(False, True)))
    times = []
    with flags.override(enabled=True, dry_run=False):
        monitor = ResourceMonitor(interval=0.1).start()
        for _ in range(n):
            t0 = time.perf_counter()
            run.run_action("window.list", {}, lambda ctx: "ok")
            times.append((time.perf_counter() - t0) * 1000)
        summary = monitor.stop()
    times.sort()
    return {"actions": n, "p50_ms": round(statistics.median(times), 3),
            "p95_ms": round(times[int(n * 0.95) - 1], 3), "max_ms": round(times[-1], 3),
            "cpu_avg_percent": summary.cpu_avg_percent, "rss_peak_mb": summary.rss_peak_mb}


def _stop_latency(trials: int = 20) -> dict:
    """Time from estop.trigger() to the runner returning 'cancelled'.

    The trigger is only sent once the action is really running (its handler
    signals), and a trial only counts when the result is 'cancelled'.
    """
    from jarvis.computer_control import estop, flags
    from jarvis.computer_control.policy import ActionPolicy, AuthSnapshot
    from jarvis.computer_control.runner import ActionRunner

    run = ActionRunner(ActionPolicy(auth=lambda: AuthSnapshot(False, True)))
    latencies: list[float] = []
    failed = 0

    with flags.override(enabled=True, dry_run=False):
        for _ in range(trials):
            started, done = threading.Event(), threading.Event()
            stamp: dict = {}

            def busy(ctx, started=started):
                started.set()
                while True:
                    ctx.wait(1.0)

            def go(stamp=stamp, done=done, busy=busy):
                stamp["result"] = run.run_action("window.wait", {}, busy, timeout=30)
                stamp["end"] = time.perf_counter()
                done.set()

            threading.Thread(target=go, daemon=True).start()
            if not started.wait(5):
                failed += 1
                continue
            t0 = time.perf_counter()
            estop.trigger("benchmark")
            if not done.wait(5) or stamp["result"].status != "cancelled":
                failed += 1
                continue
            latencies.append((stamp["end"] - t0) * 1000)
    if not latencies:
        return {"trials": trials, "failed": failed, "p50_ms": None, "p95_ms": None, "max_ms": None}
    latencies.sort()
    n = len(latencies)
    return {"trials": trials, "failed": failed, "p50_ms": round(statistics.median(latencies), 2),
            "p95_ms": round(latencies[max(0, int(n * 0.95) - 1)], 2), "max_ms": round(latencies[-1], 2)}


def sample_process(pid: int, seconds: float = 30.0, interval: float = 0.5) -> dict:
    """RSS/CPU of an already running JARVIS process (the owner's real app)."""
    import psutil
    proc = psutil.Process(int(pid))
    proc.cpu_percent(None)
    rss, cpu = [], []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(interval)
        with proc.oneshot():
            rss.append(proc.memory_info().rss / 1048576)
            cpu.append(proc.cpu_percent(None))
    children = proc.children(recursive=True)
    child_rss = sum(c.memory_info().rss for c in children) / 1048576 if children else 0.0
    return {"pid": pid, "seconds": seconds, "rss_avg_mb": round(sum(rss) / len(rss), 1),
            "rss_peak_mb": round(max(rss), 1), "cpu_avg_percent": round(sum(cpu) / len(cpu), 1),
            "cpu_peak_percent": round(max(cpu), 1), "children": len(children),
            "children_rss_mb": round(child_rss, 1)}


def collect() -> dict:
    report = {
        "host": {"platform": platform.platform(), "python": platform.python_version(),
                 "cpu_count": os.cpu_count()},
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "imports": {name: _probe(mods) for name, mods in SCENARIOS.items()},
        "runner_overhead": _runner_overhead(),
        "stop_latency": _stop_latency(),
    }
    try:
        import psutil
        report["host"]["ram_total_gb"] = round(psutil.virtual_memory().total / 1073741824, 1)
    except Exception:
        report["host"]["ram_total_gb"] = None
    return report


def to_markdown(report: dict) -> str:
    lines = [f"Host: {report['host']}  ", f"Measured: {report['measured_at']}", "",
             "| scenario | RSS before (MB) | RSS after (MB) | import (s) | idle CPU % | threads |",
             "|---|---|---|---|---|---|"]
    for name, row in report["imports"].items():
        if "error" in row:
            lines.append(f"| {name} | error: {row['error']} | | | | |")
            continue
        lines.append(f"| {name} | {row['rss_before_mb']} | {row['rss_after_mb']} | {row['import_s']} "
                     f"| {row['idle_cpu_percent']} | {row['threads']} |")
    ro, sl = report["runner_overhead"], report["stop_latency"]
    lines += ["", f"Runner overhead ({ro['actions']} no-op LOW actions): p50 {ro['p50_ms']} ms, "
                  f"p95 {ro['p95_ms']} ms, max {ro['max_ms']} ms, CPU avg {ro['cpu_avg_percent']} %, "
                  f"RSS peak {ro['rss_peak_mb']} MB",
              f"Emergency-stop latency ({sl['trials']} trials, {sl['failed']} failed): p50 {sl['p50_ms']} ms, "
              f"p95 {sl['p95_ms']} ms, max {sl['max_ms']} ms"]
    return "\n".join(lines)
