"""Measure JARVIS's real memory use while it runs (no app changes required).

Built on the profiler proposed in PR #143, with the sampling core split out so it
can be unit-tested and so several stress labels can be recorded into one file.

Why a separate tool instead of in-app telemetry: the laptop this targets has
4 GB of RAM, and "is it better now?" has to be answered on the real machine, not
from a code review. This samples the process tree (JARVIS plus Qt WebEngine
helpers and any browser/Steam children) and writes CSV you can diff.

Windows example::

    python tools/profile_ram.py --pid 1234 --duration 120 --label idle
    python tools/profile_ram.py --pid 1234 --duration 60  --label voice
    python tools/profile_ram.py --pid 1234 --duration 60  --label screen --append

Find the PID in Task Manager → Details → python.exe (or `jarvis.exe`).
It reads only process metadata: no screen contents, no configuration, no secrets.

Reading the summary
-------------------
* ``rss_mb``  — resident size summed over the tree. Over-counts genuinely shared
  pages, but it is what Task Manager shows and what the machine runs out of.
* ``uss_mb``  — unique set size: the memory that would actually be freed if the
  process exited. This is the honest "cost of JARVIS" number. Empty on systems
  where psutil cannot provide it (some Windows configurations).
* ``system_available_mb`` — what is left for everything else. If this drops under
  ~500 MB during a session, the 4 GB machine is about to start swapping.
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

__all__ = ["process_tree", "memory_sample", "summarise", "write_csv", "main"]

_DEAD = (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess)
#: USS is not available on every platform/build; that is normal, not a failure.
_USS_UNAVAILABLE = (AttributeError, NotImplementedError) + _DEAD


def process_tree(pid: int) -> list:
    """The root process and its currently running descendants, deduplicated."""
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess as exc:
        raise ValueError(f"No process exists with PID {pid}.") from exc

    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except _DEAD:
        # A child that exited between listing and reading is not an error: the
        # sample is still valid for everything that is alive.
        pass

    unique: dict[int, object] = {}
    for process in processes:
        unique[process.pid] = process
    return list(unique.values())


def memory_sample(pid: int) -> dict[str, object]:
    """One sample of the process tree plus system-wide available memory."""
    processes = process_tree(pid)
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
                uss_bytes += int(getattr(process.memory_full_info(), "uss"))
            except _USS_UNAVAILABLE:
                uss_available = False
            try:
                cpu_percent += process.cpu_percent(interval=None)
            except _DEAD:
                continue
        except _DEAD:
            continue

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "process_count": alive,
        "rss_mb": round(rss_bytes / (1024 * 1024), 2),
        "uss_mb": round(uss_bytes / (1024 * 1024), 2) if uss_available else "",
        "cpu_percent_sum": round(cpu_percent, 2),
        "system_available_mb": round(psutil.virtual_memory().available / (1024 * 1024), 2),
    }


def summarise(samples: list[dict]) -> dict[str, float]:
    """Min / average / peak RSS, peak USS and the low-water mark for RAM left."""
    if not samples:
        return {}
    rss = [float(row["rss_mb"]) for row in samples]
    available = [float(row["system_available_mb"]) for row in samples]
    uss = [float(row["uss_mb"]) for row in samples if row.get("uss_mb") not in ("", None)]
    return {
        "samples": len(samples),
        "rss_min_mb": min(rss),
        "rss_avg_mb": sum(rss) / len(rss),
        "rss_peak_mb": max(rss),
        "uss_peak_mb": max(uss) if uss else 0.0,
        "system_available_min_mb": min(available),
    }


def write_csv(path: Path, samples: list[dict], *, append: bool = False) -> None:
    """Append or create the CSV, keeping the header exactly once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and append and path.stat().st_size > 0
    with path.open("a" if exists else "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(samples[0]))
        if not exists:
            writer.writeheader()
        writer.writerows(samples)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pid", type=int, required=True, help="PID of the running JARVIS Python process")
    parser.add_argument("--duration", type=float, default=60.0, help="Sampling duration in seconds (default: 60)")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between samples (default: 1)")
    parser.add_argument("--output", type=Path, default=Path("jarvis_ram_profile.csv"), help="CSV output path")
    parser.add_argument("--label", default="", help="What the user was doing (idle, voice, screen, hologram)")
    parser.add_argument("--append", action="store_true", help="Add these samples to an existing CSV")
    args = parser.parse_args(argv)

    if args.pid < 1:
        parser.error("--pid must be a positive integer")
    if not 1.0 <= args.duration <= 3600.0:
        parser.error("--duration must be between 1 and 3600 seconds")
    if not 0.2 <= args.interval <= 60.0:
        parser.error("--interval must be between 0.2 and 60 seconds")

    try:
        process_tree(args.pid)
    except ValueError as exc:
        parser.error(str(exc))

    samples: list[dict] = []
    deadline = time.monotonic() + args.duration
    label = args.label.strip() or "unspecified"
    print(f"Sampling PID {args.pid} and its children for {args.duration:g}s ({label}).")
    print("Use JARVIS normally during the sample: talk to it, open the dashboard, take a screenshot.")

    while True:
        try:
            sample = memory_sample(args.pid)
        except ValueError:
            print("Target process exited; stopping the sample.")
            break
        sample["label"] = label
        samples.append(sample)
        print(
            f"[{label}] RSS {sample['rss_mb']:>8} MB | USS "
            f"{(sample['uss_mb'] if sample['uss_mb'] != '' else 'n/a'):>8} MB | "
            f"processes {sample['process_count']:>2} | system available "
            f"{sample['system_available_mb']} MB"
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(args.interval, remaining))

    if not samples:
        print("No samples collected.", file=sys.stderr)
        return 2

    # ``label`` is written last so the numeric columns keep their order.
    ordered = [{k: row[k] for k in row if k != "label"} | {"label": row["label"]} for row in samples]
    write_csv(args.output, ordered, append=args.append)

    stats = summarise(samples)
    print("\nSummary (root + currently visible children; RSS is not unique physical RAM):")
    print(f"  Samples:             {stats['samples']}")
    print(f"  RSS min/avg/peak:    {stats['rss_min_mb']:.2f} / {stats['rss_avg_mb']:.2f} / {stats['rss_peak_mb']:.2f} MB")
    if stats["uss_peak_mb"]:
        print(f"  USS peak:            {stats['uss_peak_mb']:.2f} MB")
    print(f"  System available min:{stats['system_available_min_mb']:>9.2f} MB")
    print(f"  CSV: {args.output.resolve()}")
    print("Record idle, voice-only, screen-analysis and hologram-active runs separately, then compare.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
