"""Measure JARVIS process memory while it is running (no app changes required).

Windows example:
    python tools/profile_ram.py --pid 1234 --duration 120 --interval 1

Find the PID in Task Manager → Details → python.exe. The profiler samples the
target and its child processes (for example, Qt WebEngine helpers), writes a CSV,
and prints a summary. It does not read screen contents, configuration, or secrets.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ImportError as exc:  # pragma: no cover - depends on environment
    raise SystemExit(
        "psutil is required. Install the project's runtime requirements first."
    ) from exc


def _process_tree(pid: int):
    """Return the root process and currently running descendants, deduplicated."""
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess as exc:
        raise ValueError(f"No process exists with PID {pid}.") from exc
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    unique = {}
    for process in processes:
        unique[process.pid] = process
    return list(unique.values())


def _memory_sample(
    pid: int,
    process_cache: dict[int, object] | None = None,
    primed_cpu_pids: set[int] | None = None,
) -> dict[str, float | int | str]:
    """Collect one sample while retaining process handles between samples.

    psutil reports 0.0 for the first cpu_percent(interval=None) call on a
    Process instance. Retain handles and discard that priming reading so later
    samples contain useful CPU measurements.
    """
    process_cache = process_cache if process_cache is not None else {}
    primed_cpu_pids = primed_cpu_pids if primed_cpu_pids is not None else set()
    discovered = _process_tree(pid)
    processes = []
    for candidate in discovered:
        try:
            cached = process_cache.get(candidate.pid)
            if cached is None or cached.create_time() != candidate.create_time():
                process_cache[candidate.pid] = candidate
                primed_cpu_pids.discard(candidate.pid)
            processes.append(process_cache[candidate.pid])
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    rss_bytes = 0
    uss_bytes = 0
    uss_available = True
    cpu_percent = 0.0
    alive = 0
    for process in processes:
        try:
            rss_bytes += process.memory_info().rss
            alive += 1
            try:
                full = process.memory_full_info()
                uss_bytes += int(getattr(full, "uss"))
            except (AttributeError, NotImplementedError, psutil.AccessDenied, psutil.NoSuchProcess):
                uss_available = False
            try:
                reading = process.cpu_percent(interval=None)
                if process.pid in primed_cpu_pids:
                    cpu_percent += reading
                else:
                    # The first call only primes psutil's per-process counter.
                    primed_cpu_pids.add(process.pid)
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    available = psutil.virtual_memory().available
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "process_count": alive,
        "rss_mb": round(rss_bytes / (1024 * 1024), 2),
        "uss_mb": round(uss_bytes / (1024 * 1024), 2) if uss_available else "",
        "cpu_percent_sum": round(cpu_percent, 2),
        "system_available_mb": round(available / (1024 * 1024), 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="PID of the running JARVIS Python process")
    parser.add_argument("--duration", type=float, default=60.0, help="Sampling duration in seconds (default: 60)")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between samples (default: 1)")
    parser.add_argument("--output", type=Path, default=Path("jarvis_ram_profile.csv"), help="CSV output path")
    args = parser.parse_args(argv)

    if args.pid < 1:
        parser.error("--pid must be a positive integer")
    if not 1.0 <= args.duration <= 3600.0:
        parser.error("--duration must be between 1 and 3600 seconds")
    if not 0.2 <= args.interval <= 60.0:
        parser.error("--interval must be between 0.2 and 60 seconds")

    try:
        _process_tree(args.pid)
    except ValueError as exc:
        parser.error(str(exc))

    samples = []
    process_cache: dict[int, object] = {}
    primed_cpu_pids: set[int] = set()
    deadline = time.monotonic() + args.duration
    print(f"Sampling PID {args.pid} and child processes for {args.duration:g}s.")
    print("Use JARVIS normally during the sample, including voice and screen-control tasks.")
    while True:
        try:
            sample = _memory_sample(args.pid, process_cache, primed_cpu_pids)
        except ValueError:
            print("Target process exited; stopping the sample.")
            break
        if sample["process_count"] == 0:
            print("No readable process memory in this sample; skipping it.")
        else:
            samples.append(sample)
            print(
                f"RSS {sample['rss_mb']:>8} MB | "
                f"USS {sample['uss_mb'] if sample['uss_mb'] != '' else 'n/a':>8} MB | "
                f"children included: {sample['process_count']} | "
                f"system available: {sample['system_available_mb']} MB"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(args.interval, remaining))

    if not samples:
        print("No samples collected.", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(samples[0]))
        writer.writeheader()
        writer.writerows(samples)

    rss = [float(row["rss_mb"]) for row in samples]
    available = [float(row["system_available_mb"]) for row in samples]
    print("\nSummary (root + currently visible child processes; RSS is not unique physical RAM):")
    print(f"  Samples: {len(samples)}")
    print(f"  RSS min / average / peak: {min(rss):.2f} / {sum(rss) / len(rss):.2f} / {max(rss):.2f} MB")
    print(f"  System available RAM min: {min(available):.2f} MB")
    print(f"  CSV: {args.output.resolve()}")
    print("Compare idle, voice-only, screen-analysis, and hologram-active runs separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
