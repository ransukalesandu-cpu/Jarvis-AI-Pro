"""Keep Windows from sleeping while the laptop agent runs.

Uses SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED): the display
may still turn off, but the machine stays awake so JARVIS can reach it. The
request ends when the agent exits (or ``release()`` is called). On other
systems this is a no-op; use the OS's own setting there.

If the laptop is off or asleep anyway, laptop tools are unavailable and JARVIS
says so ("The laptop is offline right now").
"""
from __future__ import annotations

import os

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class _Request:
    def __init__(self, active: bool):
        self.active = active

    def release(self) -> None:
        if self.active and os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        self.active = False


def keep_awake() -> _Request:
    if os.name != "nt":
        return _Request(False)
    import ctypes
    ok = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    if ok:
        print("[Agent] Keeping Windows awake while the agent runs.")
    return _Request(bool(ok))
