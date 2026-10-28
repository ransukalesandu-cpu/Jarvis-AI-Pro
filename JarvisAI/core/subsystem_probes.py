"""Real subsystem probes for the HUD's live health indicators.

Every probe returns ``(available, ok, detail)``:

* ``available`` — does this machine *have* the capability at all? A laptop with
  no microphone is not "broken", so its indicator renders as unavailable rather
  than red.
* ``ok`` — is the available capability currently working?
* ``detail`` — a short, real explanation shown in the tooltip.

The probes only report what they can actually measure. Nothing here predicts,
estimates or fakes a green light: a failed import is *unavailable*, a failed
call is *error*, and the detail string carries the exception type.

Because :func:`probe_network` can block on DNS/TCP for a few seconds, the HUD
never calls probes on the Qt thread. :class:`SubsystemProber` runs them in one
daemon thread and publishes an immutable snapshot; the UI just reads it.
"""

from __future__ import annotations

import os
import socket
import threading
import time

__all__ = [
    "ProbeResult",
    "probe_microphone",
    "probe_speaker",
    "probe_network",
    "probe_provider",
    "probe_audio_stream",
    "default_probes",
    "SubsystemProber",
]

GEMINI_HOST = "generativelanguage.googleapis.com"
GEMINI_PORT = 443


# ───────────────────────────── individual probes ────────────────────────────


def _query_audio_devices() -> list[dict]:
    import sounddevice as sd

    devices = sd.query_devices()
    # sounddevice returns a DeviceList of dict-like entries.
    return [dict(device) for device in devices]


def probe_microphone() -> tuple[bool, bool, str]:
    """Microphone capability: sounddevice importable and an input device exists."""
    try:
        devices = _query_audio_devices()
    except ImportError:
        return False, False, "sounddevice not installed"
    except Exception as exc:  # PortAudio can fail at import or query time
        return True, False, f"device query failed ({type(exc).__name__})"
    inputs = [d for d in devices if int(d.get("max_input_channels") or 0) > 0]
    if not inputs:
        return True, False, "no input device detected"
    return True, True, f"{len(inputs)} input device(s)"


def probe_speaker() -> tuple[bool, bool, str]:
    """Speaker capability: sounddevice importable and an output device exists."""
    try:
        devices = _query_audio_devices()
    except ImportError:
        return False, False, "sounddevice not installed"
    except Exception as exc:
        return True, False, f"device query failed ({type(exc).__name__})"
    outputs = [d for d in devices if int(d.get("max_output_channels") or 0) > 0]
    if not outputs:
        return True, False, "no output device detected"
    return True, True, f"{len(outputs)} output device(s)"


def probe_network(timeout: float = 4.0) -> tuple[bool, bool, str]:
    """Reach the Gemini endpoint over TCP. Blocking — run this off the UI thread."""
    try:
        with socket.create_connection((GEMINI_HOST, GEMINI_PORT), timeout=timeout):
            return True, True, f"{GEMINI_HOST} reachable"
    except OSError as exc:
        return True, False, f"unreachable ({type(exc).__name__})"


def probe_provider() -> tuple[bool, bool, str]:
    """Is a Gemini API key actually configured? Reads the same file the live loop reads."""
    try:
        from memory.config_manager import load_api_keys
    except ImportError:
        return False, False, "config manager unavailable"
    try:
        key = str(load_api_keys().get("gemini_api_key", "") or "").strip()
    except Exception as exc:
        return True, False, f"config unreadable ({type(exc).__name__})"
    if len(key) <= 15:
        return True, False, "no Gemini API key configured"
    return True, True, "API key configured"


def probe_audio_stream() -> tuple[bool, bool, str]:
    """Is audio actually flowing (mic capture or playback) right now?

    Used only for notifications: "silent stream" is only reported while the HUD
    believes it should be hearing something.
    """
    try:
        from audio.visualizer_bridge import get_visualizer_bridge
    except ImportError:
        return False, False, "visualizer bridge unavailable"
    try:
        bridge = get_visualizer_bridge()
        state = str(bridge.current_state or "IDLE").upper()
    except Exception as exc:
        return True, False, f"bridge error ({type(exc).__name__})"
    if state in ("LISTENING", "SPEAKING"):
        return True, True, f"stream active ({state.lower()})"
    return True, True, f"idle ({state.lower()})"


def default_probes() -> dict:
    """The probe set wired into the HUD, keyed by :class:`HealthMonitor` name."""
    return {
        "microphone": probe_microphone,
        "speaker": probe_speaker,
        "network": probe_network,
        "provider": probe_provider,
        "audio_stream": probe_audio_stream,
    }


# ───────────────────────────── background runner ────────────────────────────


class ProbeResult:
    """Immutable snapshot of one probe run."""

    __slots__ = ("results", "started_at", "finished_at")

    def __init__(self, results: dict, started_at: float, finished_at: float):
        self.results = dict(results)
        self.started_at = started_at
        self.finished_at = finished_at

    def get(self, name: str, default=(False, False, "not probed")) -> tuple:
        return self.results.get(name, default)


class SubsystemProber:
    """Runs probes in one daemon thread and publishes the latest snapshot.

    ``get(name)`` is what the HUD hands to :class:`HealthMonitor` as its probe:
    it never blocks, so the 5-second health poll stays instant even when the
    network check takes four seconds inside the worker.
    """

    def __init__(self, probes: dict | None = None, interval: float = 8.0):
        self._probes = dict(probes if probes is not None else default_probes())
        self._interval = max(2.0, float(interval))
        self._lock = threading.Lock()
        self._latest = {name: (False, False, "awaiting first probe") for name in self._probes}
        self._finished_at = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def run_once(self) -> ProbeResult:
        """Synchronously probe everything. Tests call this; the thread calls it too."""
        started = time.time()
        results: dict[str, tuple] = {}
        for name, probe in self._probes.items():
            try:
                result = probe()
                available, ok, detail = result
                results[name] = (bool(available), bool(ok), str(detail))
            except Exception as exc:  # a broken probe is a broken subsystem
                results[name] = (False, False, f"probe error ({type(exc).__name__})")
        finished = time.time()
        with self._lock:
            self._latest = results
            self._finished_at = finished
        return ProbeResult(results, started, finished)

    def start(self) -> None:
        """Start the polling thread (idempotent).

        ``JARVIS_DISABLE_SUBSYSTEM_PROBES=1`` keeps the thread from starting,
        which tests and headless tools use to stay off the network. The probes
        then simply report "awaiting first probe" (unavailable), never a
        fabricated green light.
        """
        if str(os.environ.get("JARVIS_DISABLE_SUBSYSTEM_PROBES", "")).strip() in {"1", "true", "yes"}:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="JarvisSubsystemProber", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 0.5) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def _loop(self) -> None:
        # Probe once immediately so the strip is truthful within a second.
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self._interval)

    # -- read side (UI thread) ---------------------------------------------
    def get(self, name: str) -> tuple[bool, bool, str]:
        with self._lock:
            return self._latest.get(name, (False, False, "not probed"))

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._latest)

    @property
    def finished_at(self) -> float:
        with self._lock:
            return self._finished_at
