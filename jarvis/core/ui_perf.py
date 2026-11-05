"""Performance tiers for the HUD: how much animation the machine can afford.

Three tiers, from the full show to a light one for a 4 GB laptop:

* ``full``     60 fps cap, five energy wires with pulses, bloom, glass sheen
* ``balanced`` 30 fps cap, five wires with pulses, no glass sheen
* ``lite``     20 fps cap, three plain wires, no bloom, lighter glass

"auto" picks one from the hardware; a :class:`FrameGovernor` then steps down a
tier when frames keep running over budget, and back up (never above the auto
choice) once there is room again. The owner can pin a tier in the settings.

No Qt.
"""
from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass

ORDER = ("lite", "balanced", "full")
CHOICES = ("auto",) + ORDER


@dataclass(frozen=True)
class Tier:
    name: str
    fps: int
    wires: int
    pulses: bool
    bloom: bool
    glass_sheen: bool

    @property
    def interval_ms(self) -> int:
        return max(8, round(1000 / self.fps))

    @property
    def budget_ms(self) -> float:
        """Paint time that leaves headroom inside one frame."""
        return 1000.0 / self.fps * 0.6


TIERS = {
    "full": Tier("full", 60, 5, True, True, True),
    "balanced": Tier("balanced", 30, 5, True, True, False),
    "lite": Tier("lite", 20, 3, False, False, False),
}


def auto_tier(cpu_count: int | None = None, ram_gb: float | None = None) -> str:
    """A starting tier from the hardware."""
    cpus = cpu_count if cpu_count is not None else (os.cpu_count() or 2)
    if ram_gb is None:
        try:
            import psutil
            ram_gb = psutil.virtual_memory().total / 2 ** 30
        except Exception:
            ram_gb = 8.0
    if ram_gb < 6 or cpus <= 2:
        return "lite"
    if ram_gb < 12 or cpus <= 4:
        return "balanced"
    return "full"


def resolve(choice: str, **hw) -> str:
    choice = str(choice or "auto").strip().lower()
    return choice if choice in TIERS else auto_tier(**hw)


class FrameGovernor:
    """Steps the tier down when frames run long, back up when they don't.

    Down: the average of the last ``window`` frames is over budget.
    Up: a long stretch (``window * 8`` frames) well under the next tier's
    budget, and never above ``ceiling`` (the auto choice).
    A pinned tier is never changed.
    """

    def __init__(self, tier: str, *, ceiling: str | None = None, pinned: bool = False,
                 window: int = 90):
        self.tier = tier if tier in TIERS else "balanced"
        self.ceiling = ceiling if ceiling in TIERS else self.tier
        self.pinned = pinned
        self.window = max(10, int(window))
        self._samples: deque[float] = deque(maxlen=self.window * 8)

    def record(self, paint_ms: float) -> str | None:
        """Add one frame's paint time; returns the new tier name on a change."""
        if self.pinned:
            return None
        self._samples.append(float(paint_ms))
        if len(self._samples) < self.window:
            return None
        recent = list(self._samples)[-self.window:]
        avg = sum(recent) / len(recent)
        i = ORDER.index(self.tier)
        if avg > TIERS[self.tier].budget_ms and i > 0:
            return self._switch(ORDER[i - 1])
        if (len(self._samples) == self._samples.maxlen and i < ORDER.index(self.ceiling)
                and sum(self._samples) / len(self._samples) < TIERS[ORDER[i + 1]].budget_ms * 0.5):
            return self._switch(ORDER[i + 1])
        return None

    def _switch(self, tier: str) -> str:
        self.tier = tier
        self._samples.clear()
        return tier
