"""Small reproducible micro-benchmark for bounded agent step dispatch.

Run from the repository root:
    python -m benchmarks.benchmark_agent_engine --steps 12 --delay-ms 30

This measures scheduler overhead with synthetic independent I/O-like waits. It is
not a claim about real provider, disk, browser, or laptop performance.
"""

from __future__ import annotations

import argparse
import time

from jarvis.agent.parallel_engine import ParallelStepEngine


def run_benchmark(step_count: int, delay_ms: float, workers: int) -> dict[str, float]:
    delay = max(0.0, min(delay_ms / 1000.0, 2.0))
    count = max(1, min(int(step_count), 128))
    engine = ParallelStepEngine(max_workers=workers)

    started = time.perf_counter()
    for _ in range(count):
        time.sleep(delay)
    sequential_s = time.perf_counter() - started

    started = time.perf_counter()
    engine.run(
        range(count),
        lambda _item: time.sleep(delay) or True,
    )
    parallel_s = time.perf_counter() - started

    return {
        "steps": float(count),
        "workers": float(engine.max_workers),
        "sequential_s": round(sequential_s, 4),
        "parallel_s": round(parallel_s, 4),
        "speedup": round(sequential_s / max(parallel_s, 1e-9), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--delay-ms", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    result = run_benchmark(args.steps, args.delay_ms, args.workers)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
