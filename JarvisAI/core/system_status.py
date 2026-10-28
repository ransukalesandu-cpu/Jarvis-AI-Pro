"""Truthful system state: battery, subsystem health, performance budget, alerts.

Everything the HUD shows about "how is JARVIS doing" comes from here, and
everything here comes from a real source or is reported as unavailable. There
are no fabricated percentages, no optimistic green dots, and no animation that
claims an event that did not happen.

Contents
--------
``BatteryMonitor``
    Reads the OS battery via ``psutil.sensors_battery``. Emits *edge* events
    only: charger plugged/unplugged, each threshold crossed once, full once.
    A desktop with no battery reports ``available=False`` and never fires.

``HealthMonitor``
    Mic / speaker / network / AI-provider / audio-stream states, fed by probe
    callables the app already owns. A probe that raises marks the subsystem
    unavailable — never healthy.

``AdaptivePerformance``
    Turns battery level, charging state and (optionally) CPU load into a render
    budget: frame interval, particle count, glow scale. Hysteresis prevents the
    budget flapping at a threshold boundary.

``NotificationCenter``
    Priority queue with de-duplication and per-key cooldown, so "microphone
    disconnected" cannot fire forty times a minute and a battery warning cannot
    repeat while the level stays under the threshold.

This module has no Qt dependency: the HUD polls it from a QTimer and forwards
the returned events, which keeps the logic unit-testable and keeps UI updates
on the UI thread.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

__all__ = [
    "BatteryReading",
    "BatteryMonitor",
    "BatteryThresholds",
    "HealthState",
    "HealthMonitor",
    "SubsystemStatus",
    "AdaptivePerformance",
    "PerformanceBudget",
    "Notification",
    "NotificationCenter",
    "PRIORITY_CRITICAL",
    "PRIORITY_HIGH",
    "PRIORITY_NORMAL",
    "PRIORITY_LOW",
]

PRIORITY_CRITICAL = 0
PRIORITY_HIGH = 1
PRIORITY_NORMAL = 2
PRIORITY_LOW = 3


# ────────────────────────────── battery ─────────────────────────────────────


@dataclass(frozen=True)
class BatteryThresholds:
    """Warning levels, highest first. All are lower bounds for *crossing*."""

    fifty: int = 50
    low: int = 25
    critical: int = 10
    full: int = 100

    def validated(self) -> "BatteryThresholds":
        """Force a strictly ordered, usable set of bands (each one below the last)."""
        fifty = max(30, min(90, int(self.fifty)))
        low = max(5, min(fifty - 1, int(self.low)))
        critical = max(1, min(low - 1, int(self.critical)))
        # "Full" is a charged level, not a warning: clamp it to a sane band.
        full = max(fifty + 1, min(100, max(80, int(self.full))))
        return BatteryThresholds(fifty=fifty, low=low, critical=critical, full=full)

    def level_name(self, percent: float) -> str:
        """Which band a charge level belongs to (``"full"`` … ``"critical"``)."""
        if percent >= self.full:
            return "full"
        if percent <= self.critical:
            return "critical"
        if percent <= self.low:
            return "low"
        if percent <= self.fifty:
            return "fifty"
        return "normal"


@dataclass(frozen=True)
class BatteryReading:
    """A real battery sample, or an explicit "this machine has none"."""

    available: bool
    percent: float | None = None
    plugged: bool | None = None
    seconds_left: float | None = None

    @property
    def level_name(self) -> str:
        return "unavailable" if not self.available else "ok"


def _read_battery_from_psutil() -> BatteryReading:
    try:
        import psutil
    except ImportError:
        return BatteryReading(available=False)
    try:
        sample = psutil.sensors_battery()
    except Exception:
        return BatteryReading(available=False)
    if sample is None:
        # Desktop / server: genuinely no battery. Not an error, not 0 %.
        return BatteryReading(available=False)
    try:
        percent = float(sample.percent)
        plugged = bool(sample.power_plugged)
    except Exception:
        return BatteryReading(available=False)
    seconds = getattr(sample, "secsleft", None)
    try:
        seconds_left = float(seconds) if seconds is not None and seconds >= 0 else None
    except (TypeError, ValueError):
        seconds_left = None
    return BatteryReading(
        available=True, percent=max(0.0, min(100.0, percent)), plugged=plugged,
        seconds_left=seconds_left,
    )


@dataclass(frozen=True)
class BatteryEvent:
    """Something the user should be told about the battery."""

    kind: str          # "charging" | "unplugged" | "threshold" | "full"
    level: str         # band name: "fifty", "low", "critical", "full"
    percent: float
    detail: str = ""
    priority: int = PRIORITY_NORMAL


class BatteryMonitor:
    """Edge-triggered battery state machine.

    ``poll()`` returns the events that happened since the previous call. It is
    deliberately silent while nothing changes: repeated ``poll()`` calls at 90 %
    on battery produce nothing at all.
    """

    def __init__(
        self,
        reader: Callable[[], BatteryReading] | None = None,
        thresholds: BatteryThresholds | None = None,
    ):
        self._reader = reader or _read_battery_from_psutil
        self._thresholds = (thresholds or BatteryThresholds()).validated()
        self.reading = BatteryReading(available=False)
        self._last_band: str | None = None
        self._last_plugged: bool | None = None
        self._announced: set[str] = set()

    @property
    def thresholds(self) -> BatteryThresholds:
        return self._thresholds

    def set_thresholds(self, thresholds: BatteryThresholds) -> None:
        self._thresholds = thresholds.validated()
        self._announced.clear()

    def band(self) -> str:
        if not self.reading.available or self.reading.percent is None:
            return "unavailable"
        return self._thresholds.level_name(self.reading.percent)

    def poll(self) -> list[BatteryEvent]:
        try:
            reading = self._reader()
        except Exception:
            reading = BatteryReading(available=False)

        events: list[BatteryEvent] = []
        if not reading.available or reading.percent is None:
            self.reading = reading
            self._last_band = "unavailable"
            self._last_plugged = None
            self._announced.clear()
            return events

        previous_band = self._last_band
        previous_plugged = self._last_plugged
        self.reading = reading
        band = self._thresholds.level_name(reading.percent)
        self._last_band = band
        self._last_plugged = reading.plugged

        if reading.plugged and previous_plugged is False:
            events.append(
                BatteryEvent("charging", band, reading.percent,
                             "Charger connected — charging.", PRIORITY_NORMAL)
            )
        elif reading.plugged is False and previous_plugged is True:
            events.append(
                BatteryEvent("unplugged", band, reading.percent,
                             "Running on battery.", PRIORITY_NORMAL)
            )

        # Thresholds fire once per crossing. Going back *up* past a band clears
        # its announcement so the next descent warns again; staying down does
        # not re-warn.
        order = ["critical", "low", "fifty", "normal"]
        if band in order:
            index = order.index(band)
            for deeper in order[index + 1:]:
                self._announced.discard(deeper)
            self._announced.discard(band)

        if band in ("fifty", "low", "critical") and band not in self._announced:
            if previous_band != band:
                self._announced.add(band)
                percent = int(round(reading.percent))
                if band == "critical":
                    message, priority = (
                        f"Battery critical at {percent}% — plug in now.", PRIORITY_CRITICAL
                    )
                elif band == "low":
                    message, priority = (
                        f"Battery low at {percent}% — visual battery saver is on.",
                        PRIORITY_HIGH,
                    )
                else:
                    message, priority = (
                        f"Battery at {percent}% — consider charging.", PRIORITY_NORMAL
                    )
                events.append(BatteryEvent("threshold", band, reading.percent, message, priority))

        if band == "full" and "full" not in self._announced:
            self._announced.add("full")
            events.append(
                BatteryEvent("full", band, reading.percent,
                             "Battery fully charged.", PRIORITY_LOW)
            )
        elif band != "full":
            self._announced.discard("full")

        return events


# ────────────────────────────── health ──────────────────────────────────────


@dataclass(frozen=True)
class SubsystemStatus:
    """State of one subsystem. ``available`` is *capability*, ``ok`` is health."""

    name: str
    available: bool
    ok: bool
    detail: str = ""
    changed_at: float = field(default_factory=time.time)

    @property
    def state(self) -> str:
        if not self.available:
            return "unavailable"
        return "ok" if self.ok else "error"


@dataclass(frozen=True)
class HealthState:
    """A full snapshot; ``all_ok`` is False if any available subsystem fails."""

    microphone: SubsystemStatus
    speaker: SubsystemStatus
    network: SubsystemStatus
    provider: SubsystemStatus
    audio_stream: SubsystemStatus

    def statuses(self) -> tuple[SubsystemStatus, ...]:
        return (self.microphone, self.speaker, self.network, self.provider, self.audio_stream)

    @property
    def all_ok(self) -> bool:
        return all(not status.available or status.ok for status in self.statuses())

    def problems(self) -> list[SubsystemStatus]:
        return [s for s in self.statuses() if s.available and not s.ok]


class HealthMonitor:
    """Polls probe callables and turns transitions into notifications.

    A probe returns ``(available: bool, ok: bool, detail: str)``. Anything else
    — an exception, a missing probe, ``None`` — is treated as *unavailable*,
    never as healthy.
    """

    SUBSYSTEMS = ("microphone", "speaker", "network", "provider", "audio_stream")

    LABELS = {
        "microphone": "Microphone",
        "speaker": "Speaker",
        "network": "Network",
        "provider": "AI session",
        "audio_stream": "Audio stream",
    }
    PRIORITIES = {
        "microphone": PRIORITY_HIGH,
        "speaker": PRIORITY_HIGH,
        "network": PRIORITY_NORMAL,
        "provider": PRIORITY_HIGH,
        "audio_stream": PRIORITY_NORMAL,
    }

    def __init__(self, probes: Mapping[str, Callable[[], Any]] | None = None):
        self._probes = dict(probes or {})
        self._previous: dict[str, str] = {}

    def set_probe(self, name: str, probe: Callable[[], Any] | None) -> None:
        if probe is None:
            self._probes.pop(name, None)
        else:
            self._probes[name] = probe

    def _probe(self, name: str) -> SubsystemStatus:
        probe = self._probes.get(name)
        if probe is None:
            return SubsystemStatus(name, available=False, ok=False, detail="not monitored")
        try:
            available, ok, detail = probe()
        except Exception as exc:
            return SubsystemStatus(
                name, available=False, ok=False,
                detail=f"{type(exc).__name__}: {exc}"[:120],
            )
        return SubsystemStatus(
            name, available=bool(available), ok=bool(ok), detail=str(detail or "")[:120]
        )

    def snapshot(self) -> HealthState:
        statuses = {name: self._probe(name) for name in self.SUBSYSTEMS}
        return HealthState(
            microphone=statuses["microphone"],
            speaker=statuses["speaker"],
            network=statuses["network"],
            provider=statuses["provider"],
            audio_stream=statuses["audio_stream"],
        )

    def poll(self) -> tuple[HealthState, list["Notification"]]:
        state = self.snapshot()
        notifications: list[Notification] = []
        for status in state.statuses():
            previous = self._previous.get(status.name)
            current = status.state
            self._previous[status.name] = current
            if previous == current:
                continue
            # A subsystem that is already broken on the first observation is
            # reported too; "unavailable" (no capability) never alerts.
            if previous is None and current != "error":
                continue
            if current == "error":
                notifications.append(
                    Notification(
                        key=f"health:{status.name}",
                        title=f"{self.LABELS.get(status.name, status.name)} unavailable",
                        body=status.detail or "The subsystem stopped responding.",
                        priority=self.PRIORITIES.get(status.name, PRIORITY_NORMAL),
                        source="health",
                        cooldown=30.0,
                    )
                )
            elif current == "ok" and previous == "error":
                notifications.append(
                    Notification(
                        key=f"health:{status.name}:recovered",
                        title=f"{self.LABELS.get(status.name, status.name)} restored",
                        body="JARVIS can use it again.",
                        priority=PRIORITY_LOW,
                        source="health",
                        cooldown=30.0,
                    )
                )
        return state, notifications


# ────────────────────────── adaptive performance ─────────────────────────────


@dataclass(frozen=True)
class PerformanceBudget:
    """What the renderers are allowed to spend this frame."""

    tier: str                 # "full" | "balanced" | "saver"
    frame_interval_ms: int
    particle_scale: float     # 0.0-1.0 multiplier on particle counts
    glow_scale: float         # 0.2-1.0 multiplier on bloom
    reason: str = ""

    def particle_count(self, base: int) -> int:
        return max(0, int(round(base * self.particle_scale)))


class AdaptivePerformance:
    """Picks a render budget from battery + optional CPU load.

    Hysteresis: leaving a saver tier needs a margin above the entry threshold,
    so a battery hovering at exactly 25 % does not thrash the renderer between
    budgets on consecutive polls.
    """

    def __init__(
        self,
        *,
        saver_percent: int = 25,
        balanced_percent: int = 50,
        hysteresis: int = 5,
        cpu_probe: Callable[[], float] | None = None,
        cpu_limit: float = 0.85,
    ):
        self.saver_percent = int(saver_percent)
        self.balanced_percent = max(self.saver_percent + 1, int(balanced_percent))
        self.hysteresis = max(0, int(hysteresis))
        self._cpu_probe = cpu_probe
        self._cpu_limit = float(cpu_limit)
        self._tier = "full"

    @staticmethod
    def budget_for(tier: str, reason: str = "") -> PerformanceBudget:
        if tier == "saver":
            return PerformanceBudget("saver", 66, 0.25, 0.45, reason)
        if tier == "balanced":
            return PerformanceBudget("balanced", 33, 0.6, 0.75, reason)
        return PerformanceBudget("full", 16, 1.0, 1.0, reason)

    def decide(
        self,
        reading: BatteryReading,
        *,
        reduced_motion: bool = False,
        battery_saver_enabled: bool = True,
    ) -> PerformanceBudget:
        percent = reading.percent if reading.available else None
        plugged = bool(reading.plugged)

        reason = "no battery data"
        tier = "full"
        if percent is not None:
            # While charging, a low battery is expected to recover; do not
            # degrade the visuals for it.
            if battery_saver_enabled and not plugged and percent <= self.saver_percent:
                tier, reason = "saver", f"battery {percent:.0f}%"
            elif battery_saver_enabled and not plugged and percent <= self.balanced_percent:
                tier, reason = "balanced", f"battery {percent:.0f}%"
        if reduced_motion:
            tier, reason = "saver", "reduced motion"

        load = None
        if self._cpu_probe is not None:
            try:
                load = float(self._cpu_probe())
            except Exception:
                load = None
        if load is not None and load >= self._cpu_limit and tier != "saver":
            tier, reason = ("balanced" if tier == "full" else tier), f"cpu {load:.0%}"

        # Hysteresis on the way back up.
        if self._tier == "saver" and tier != "saver" and percent is not None:
            if battery_saver_enabled and not plugged and percent <= self.saver_percent + self.hysteresis:
                tier, reason = "saver", f"battery {percent:.0f}% (hysteresis)"
        elif self._tier == "balanced" and tier == "full" and percent is not None:
            if battery_saver_enabled and not plugged and percent <= self.balanced_percent + self.hysteresis:
                tier, reason = "balanced", f"battery {percent:.0f}% (hysteresis)"

        self._tier = tier
        return self.budget_for(tier, reason)

    @property
    def tier(self) -> str:
        return self._tier

    def reset(self) -> None:
        self._tier = "full"


# ──────────────────────────── notifications ─────────────────────────────────


@dataclass(frozen=True)
class Notification:
    """One user-facing alert. ``key`` is the de-duplication identity."""

    key: str
    title: str
    body: str = ""
    priority: int = PRIORITY_NORMAL
    source: str = "system"
    cooldown: float = 20.0
    created_at: float = field(default_factory=time.time)

    @property
    def is_critical(self) -> bool:
        return self.priority <= PRIORITY_HIGH


class NotificationCenter:
    """Bounded, de-duplicating queue with per-key cooldowns.

    Rules that matter in practice:

    * the same ``key`` inside its cooldown is dropped (a flapping microphone
      connection cannot spam the island);
    * the same ``key`` with the same text *after* the cooldown is dropped too
      unless ``repeat=True`` — "battery low" should not re-appear every minute;
    * queue is bounded and evicts the lowest priority oldest entry first.
    """

    def __init__(self, max_items: int = 24, clock: Callable[[], float] = time.time):
        self.max_items = max(4, int(max_items))
        self._clock = clock
        self._items: list[Notification] = []
        self._last_seen: dict[str, float] = {}
        self._last_text: dict[str, str] = {}
        self.history: list[Notification] = []

    def push(self, note: Notification | Iterable[Notification]) -> list[Notification]:
        """Add notifications; returns the ones that were actually accepted."""
        incoming = [note] if isinstance(note, Notification) else list(note)
        accepted: list[Notification] = []
        for item in sorted(incoming, key=lambda n: n.priority):
            now = self._clock()
            last = self._last_seen.get(item.key)
            if last is not None and now - last < item.cooldown:
                continue
            if last is not None and self._last_text.get(item.key) == item.title + item.body:
                continue
            self._last_seen[item.key] = now
            self._last_text[item.key] = item.title + item.body
            self._items.append(item)
            self.history.append(item)
            del self.history[:-200]
            accepted.append(item)

        # Evict the least important entry, not the most important one: highest
        # numeric priority first, and the oldest within that group.
        while len(self._items) > self.max_items:
            worst = max(self._items, key=lambda n: (n.priority, -n.created_at))
            self._items.remove(worst)
        self._items.sort(key=lambda n: (n.priority, n.created_at))
        return accepted

    def peek(self) -> Notification | None:
        return self._items[0] if self._items else None

    def pop(self) -> Notification | None:
        return self._items.pop(0) if self._items else None

    def pending(self) -> list[Notification]:
        return list(self._items)

    def clear(self) -> None:
        self._items.clear()

    def forget(self, key: str) -> None:
        """Allow the same alert to fire again (used when a condition recovers)."""
        self._last_seen.pop(key, None)
        self._last_text.pop(key, None)
