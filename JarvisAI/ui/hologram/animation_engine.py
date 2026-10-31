"""Frame-rate-independent helpers shared by the procedural holograms."""
from __future__ import annotations

import math


def smooth_damp(current: float, target: float, delta_seconds: float, response: float = 8.0) -> float:
    """Move current smoothly toward target using exponential damping."""
    try:
        current = float(current)
        target = float(target)
        delta = max(0.0, min(0.25, float(delta_seconds)))
        rate = max(0.1, min(30.0, float(response)))
    except (TypeError, ValueError):
        return 0.0
    if not all(math.isfinite(value) for value in (current, target, delta, rate)):
        return current if math.isfinite(current) else 0.0
    blend = 1.0 - math.exp(-rate * delta)
    return current + (target - current) * blend


def pulse(elapsed: float, frequency: float, reduced_motion: bool = False) -> float:
    """Return a stable 0..1 pulse, or a neutral value for reduced motion."""
    if reduced_motion:
        return 0.5
    try:
        t = float(elapsed)
        hz = max(0.0, min(20.0, float(frequency)))
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(t) or not math.isfinite(hz):
        return 0.5
    return 0.5 + 0.5 * math.sin(t * hz * math.tau)
