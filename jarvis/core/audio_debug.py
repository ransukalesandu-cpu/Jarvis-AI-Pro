"""Opt-in diagnostics for the Gemini Live speech path ("stops mid-sentence").

Off by default. Turn on with the environment variable ``JARVIS_AUDIO_DEBUG=1``
or ``"audio_debug": true`` in config/api_keys.json, run JARVIS, reproduce the
problem, then read ``jarvis/logs/audio_debug.log`` (also printed to the
console). Each line is one event with a timestamp relative to start-up, so the
order of barge-in, interruption, turn completion, playback end and session
renewal around a cut-off sentence shows which cause is real on this machine.

Only event names and numbers are logged: never audio, transcripts or keys.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

ENV = "JARVIS_AUDIO_DEBUG"
_BASE = Path(__file__).resolve().parent.parent
_LOG = _BASE / "logs" / "audio_debug.log"
_CONFIG = _BASE / "config" / "api_keys.json"
_T0 = time.monotonic()
_lock = threading.Lock()
_enabled: bool | None = None


def _read_flag() -> bool:
    env = os.environ.get(ENV, "").strip().lower()
    if env:
        return env not in {"0", "false", "no", "off"}
    try:
        return bool(json.loads(_CONFIG.read_text(encoding="utf-8")).get("audio_debug", False))
    except (OSError, ValueError, AttributeError):
        return False


def enabled() -> bool:
    global _enabled
    if _enabled is None:
        _enabled = _read_flag()
    return _enabled


def set_enabled(value: bool | None) -> None:
    """Force on/off (None re-reads the env/config). For tests and the console."""
    global _enabled
    _enabled = None if value is None else bool(value)


def log(event: str, **fields) -> None:
    """One diagnostic line, only when enabled. Never raises."""
    if not enabled():
        return
    try:
        detail = " ".join(f"{k}={v}" for k, v in fields.items())
        line = f"[AudioDebug +{time.monotonic() - _T0:9.3f}s] {event} {detail}".rstrip()
        print(line)
        with _lock:
            _LOG.parent.mkdir(parents=True, exist_ok=True)
            with _LOG.open("a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except Exception:          # diagnostics must never disturb the audio path
        return
