"""Opt-in diagnostics for the "JARVIS stops speaking mid-sentence" investigation.

Set ``JARVIS_AUDIO_DEBUG=1`` before starting JARVIS. Each event prints one line
prefixed ``[AudioDebug]``, so the console output (or Run_Jarvis.bat redirected
to a file) shows which of the candidate causes actually happens on a machine:

* ``interrupt``           playback stopped (provisional = VAD/echo barge-in)
* ``barge_in_confirmed``  held answer dropped; ``by`` says which Gemini signal
                          confirmed it, ``echo_overlap`` how much of the
                          confirming transcript repeats JARVIS's own last words
                          (near 1.0 means JARVIS most likely interrupted itself)
* ``barge_in_released``   false alarm; the held answer resumed
* ``playback_discard``    PCM the playback worker dropped or held on interrupt
* ``output_underflow``    the speaker ran dry (PortAudio reported an underflow)
* ``slow_write``          one speaker write blocked far longer than its audio
* ``go_away``             Gemini announced it will close the session soon

Only counts, sizes, timings and ratios are printed, never transcript text,
audio, or credentials. With the flag off every call is a cheap no-op.
"""
from __future__ import annotations

import os
import re
import time

_ENV = "JARVIS_AUDIO_DEBUG"
_WORD = re.compile(r"[\w']+", re.UNICODE)


def audio_debug_enabled() -> bool:
    return os.environ.get(_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _format(value) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    text = str(value)
    return text if len(text) <= 80 else text[:77] + "..."


def audio_debug(event: str, **fields) -> None:
    """Print one diagnostic line when JARVIS_AUDIO_DEBUG is on. Never raises."""
    if not audio_debug_enabled():
        return
    try:
        details = " ".join(f"{key}={_format(value)}" for key, value in fields.items())
        print(f"[AudioDebug] t={time.monotonic():.3f} {event} {details}".rstrip())
    except Exception:
        return


def transcript_overlap(heard: str, spoken: str) -> float:
    """Share of the words in ``heard`` that also occur in ``spoken`` (0.0-1.0)."""
    heard_words = [word.casefold() for word in _WORD.findall(str(heard or ""))]
    if not heard_words:
        return 0.0
    spoken_words = {word.casefold() for word in _WORD.findall(str(spoken or ""))}
    return sum(1 for word in heard_words if word in spoken_words) / len(heard_words)
