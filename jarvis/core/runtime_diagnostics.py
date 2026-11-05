"""Privacy-safe runtime diagnostics for hybrid AI routing.

Never accepts or records prompts, responses, credentials, or private memory.
The helpers are intentionally best-effort so diagnostics cannot break the app.
"""
from __future__ import annotations

import os
from typing import Any


def process_rss_mb() -> float | None:
    """Return current process resident memory in MiB, or None if unavailable."""
    try:
        import psutil
        return round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)
    except Exception:
        return None


def queue_depth(queue: Any) -> int | None:
    """Return queue depth without consuming items or blocking the audio loop."""
    if queue is None:
        return 0
    try:
        return max(0, int(queue.qsize()))
    except Exception:
        return None


def hybrid_runtime_snapshot(
    *,
    provider: str,
    latency_ms: float,
    audio_queue: Any = None,
    is_speaking: bool = False,
) -> dict[str, Any]:
    """Build a safe, small snapshot suitable for a single diagnostic log line."""
    try:
        latency = round(max(0.0, float(latency_ms)), 2)
    except (TypeError, ValueError):
        latency = 0.0
    rss = process_rss_mb()
    return {
        "rss_mb": rss if rss is not None else "unavailable",
        "audio_queue_depth": queue_depth(audio_queue),
        "provider": str(provider or "unknown")[:32],
        "latency_ms": latency,
        "playback_state": "speaking" if is_speaking else "idle",
    }
