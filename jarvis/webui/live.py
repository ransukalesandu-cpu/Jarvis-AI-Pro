"""Connects the web UI to the live assistant through the existing state bus.

Read-only: the bus is the same one the legacy HUD reads, so the new UI shows exactly what the old one
shows. Values the contract has no name for (e.g. the legacy MUTED label) are not forwarded and never
approximated. The page can only *ask* (typed requests); nothing here accepts commands from it.
"""
from __future__ import annotations

import time

from jarvis.core import ui_state

from . import provider_info
from .contract import ASSISTANT_STATES

AUDIO_MIN_INTERVAL = 0.05  # 20 Hz is plenty for a level meter and keeps the bridge quiet


def map_state(value) -> str | None:
    s = str(value or "").strip().lower()
    return s if s in ASSISTANT_STATES else None


class LiveLink:
    def __init__(self, host, bus=None, clock=time.monotonic):
        self._host = host
        self._bus = bus or ui_state.bus()
        self._clock = clock
        self._last_audio = -1e9
        self._unsub = [
            self._bus.subscribe(ui_state.ASSISTANT, self._on_bus),
            self._bus.subscribe(ui_state.AUDIO_LEVEL, self._on_bus),
            self._bus.subscribe(ui_state.PERSONA, self._on_bus),
            self._bus.subscribe(ui_state.PERF_TIER, self._on_bus),
            self._bus.subscribe(ui_state.NEWS, self._on_bus),
            self._bus.subscribe(ui_state.MUTED, self._on_bus),
            self._bus.subscribe(ui_state.PROVIDER, self._on_bus),
        ]
        host.ready.connect(self.push_snapshot)   # a (re)loaded page needs the current state again

    def push_snapshot(self) -> None:
        self._push_provider()
        for key in (ui_state.ASSISTANT, ui_state.PERSONA, ui_state.PERF_TIER, ui_state.NEWS, ui_state.MUTED):
            val = self._bus.get(key)
            if val is not None:
                self._forward(key, val, force=True)

    def _push_provider(self) -> None:
        info = provider_info.snapshot()
        if info:
            self._host.set_provider(**info)

    def _on_bus(self, key: str, value) -> None:
        self._forward(key, value)

    def _forward(self, key: str, value, force: bool = False) -> None:
        if key == ui_state.ASSISTANT:
            st = map_state(value)
            if st:
                self._host.set_state(st)
        elif key == ui_state.AUDIO_LEVEL:
            try:
                lvl = float(value or 0.0)
            except (TypeError, ValueError):
                return
            now = self._clock()
            if force or lvl == 0.0 or now - self._last_audio >= AUDIO_MIN_INTERVAL:
                self._last_audio = now
                self._host.set_level(lvl, "output")
        elif key == ui_state.MUTED:
            self._host.set_muted(bool(value))
        elif key == ui_state.PROVIDER:
            self._push_provider()
        elif key == ui_state.PERSONA:
            if str(value) in ("jarvis", "bihansa"):
                self._host.set_persona(str(value))
        elif key == ui_state.NEWS:
            if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], list):
                self._host.set_news(value[0], value[1])
        elif key == ui_state.PERF_TIER:
            if str(value) in ("full", "balanced", "lite"):
                self._host.set_perf_tier(str(value))

    def close(self) -> None:
        for fn in self._unsub:
            fn()
        self._unsub = []
