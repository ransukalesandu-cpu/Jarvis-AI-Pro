"""Pure helpers and constants for the Gemini Live audio pipeline.

This module deliberately avoids importing Qt, sounddevice, or the Gemini SDK so
PCM framing and Live-event/error handling can be tested independently.
"""

from __future__ import annotations

import base64

import numpy as np

from core import failsoft


CHANNELS = 1
RECEIVE_SAMPLE_RATE = 24000
_OUTPUT_BLOCKSIZE = 2048
_MIN_LIVE_AUDIO_FRAME_BYTES = (RECEIVE_SAMPLE_RATE // 100) * 2
_PLAYBACK_SLICE_BYTES = 2400
_MIN_PREBUFFER_BYTES = int(RECEIVE_SAMPLE_RATE * CHANNELS * 2 * 0.30)
_MIN_PREBUFFER_MS = 150
_MAX_PREBUFFER_MS = 600
_PREBUFFER_STEP_MS = 50
_STABLE_TURNS_TO_SHRINK = 3


def _next_prebuffer_ms(current_ms: int, *, underrun: bool = False, stable_turns: int = 0) -> int:
    """Adapt the Live playback jitter target within safe latency bounds.

    One underrun raises the target by 50 ms. Three complete turns without an
    underrun lower it by 25 ms, avoiding rapid oscillation on bursty networks.
    """
    try:
        current = int(current_ms)
        stable = max(0, int(stable_turns))
    except (TypeError, ValueError, OverflowError):
        current, stable = 300, 0
    current = min(_MAX_PREBUFFER_MS, max(_MIN_PREBUFFER_MS, current))
    if underrun:
        current += _PREBUFFER_STEP_MS
    elif stable >= _STABLE_TURNS_TO_SHRINK:
        current -= _PREBUFFER_STEP_MS // 2
    return min(_MAX_PREBUFFER_MS, max(_MIN_PREBUFFER_MS, current))


def _take_playback_pcm(buffer: bytearray, *, final: bool = False) -> bytes:
    """Take aligned PCM without producing tiny writes during streaming.

    During streaming only full 50 ms slices are returned. At turn completion,
    return a valid final tail of at least 10 ms so short replies are not lost.
    """
    processable_bytes = len(buffer) & ~1  # signed 16-bit samples
    if final:
        take_bytes = (
            processable_bytes
            if processable_bytes >= _MIN_LIVE_AUDIO_FRAME_BYTES
            else 0
        )
    else:
        take_bytes = (
            processable_bytes // _PLAYBACK_SLICE_BYTES
        ) * _PLAYBACK_SLICE_BYTES
    if take_bytes <= 0:
        return b""
    pcm = bytes(buffer[:take_bytes])
    del buffer[:take_bytes]
    return pcm


def _output_write_is_unpaced(audio_seconds: float, wall_seconds: float) -> bool:
    """True when output writes cannot plausibly be keeping pace with playback.

    A healthy blocking output stream may buffer ahead briefly, so do not judge
    it from the first write. The caller checks this only after at least one full
    second of PCM has been submitted.
    """
    try:
        audio_seconds = float(audio_seconds)
        wall_seconds = float(wall_seconds)
    except (TypeError, ValueError):
        return False
    return (
        audio_seconds >= 1.0
        and wall_seconds >= 0.0
        and wall_seconds < audio_seconds * 0.20
    )


# RMS below which 16-bit PCM is treated as room silence; above _LEVEL_FULL it
# reads as a full-height waveform. Tuned so ordinary speech lands mid-range and
# the bars still move for a quiet talker — language- and device-independent.
_LEVEL_FLOOR = 60.0
_LEVEL_FULL  = 2600.0


def _pcm_level(samples) -> float:
    """Map a block of int16 PCM samples to a 0.0–1.0 loudness level for the HUD
    waveform. Returns 0.0 on empty/invalid input so it can never raise."""
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(x * x)))
    except Exception:
        return 0.0
    if rms <= _LEVEL_FLOOR:
        return 0.0
    return min(1.0, (rms - _LEVEL_FLOOR) / (_LEVEL_FULL - _LEVEL_FLOOR))


def _live_audio_chunks(response) -> list[bytes]:
    """Extract every audio part from a Live event, with SDK data fallback.

    Newer Live models may include multiple content parts in one server event;
    `response.data` alone can expose only a convenience view of that event.
    """
    chunks: list[bytes] = []
    server_content = getattr(response, "server_content", None)
    model_turn = getattr(server_content, "model_turn", None)
    for part in getattr(model_turn, "parts", None) or ():
        blob = getattr(part, "inline_data", None)
        if blob is None:
            continue
        mime = str(getattr(blob, "mime_type", "") or "").lower()
        if mime and not mime.startswith("audio/"):
            continue
        data = getattr(blob, "data", None)
        if isinstance(data, str):
            try:
                data = base64.b64decode(data)
            except Exception:
                failsoft.suppress('core.live_audio:_live_audio_chunks')
                continue
        if isinstance(data, (bytes, bytearray)) and data:
            chunks.append(bytes(data))

    convenience_data = getattr(response, "data", None)
    if isinstance(convenience_data, str):
        try:
            convenience_data = base64.b64decode(convenience_data)
        except Exception:
            convenience_data = None
    if not chunks and isinstance(convenience_data, (bytes, bytearray)) and convenience_data:
        chunks.append(bytes(convenience_data))
    return chunks


def _error_text(error) -> str:
    """Flatten TaskGroup members and chained exceptions for error classification."""
    parts = []
    pending = [error]
    seen = set()

    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))

        try:
            message = str(current)
        except Exception:
            message = type(current).__name__
        parts.append(f"{type(current).__name__}: {message}")

        # asyncio.TaskGroup stores child failures in .exceptions.
        children = getattr(current, "exceptions", ())
        if isinstance(children, (tuple, list)):
            pending.extend(children)

        # The useful WebSocket close code/reason can live in a cause/context,
        # several levels below the APIError raised by the Gemini SDK.
        pending.append(getattr(current, "__cause__", None))
        pending.append(getattr(current, "__context__", None))

    return " | ".join(part for part in parts if part)


def _is_quota_error(error) -> bool:
    text = _error_text(error).upper()
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    return (
        code == 429
        or "429" in text
        or "RESOURCE_EXHAUSTED" in text
        or "QUOTA" in text
        or "RATE LIMIT" in text
    )


def _is_transient_live_disconnect(error) -> bool:
    """Recognize transient Gemini Live/WebSocket failures, including close 1006
    and keepalive timeouts wrapped by the SDK or an asyncio.TaskGroup."""
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    if code in (1006, 1011, 500, 502, 503, 504):
        return True

    children = getattr(error, "exceptions", ()) or ()
    if any(_is_transient_live_disconnect(child) for child in children):
        return True

    text = _error_text(error).upper()
    return any(marker in text for marker in (
        "1006",
        "1011",
        "ABNORMAL CLOSURE",
        "KEEPALIVE PING TIMEOUT",
        "TIMED OUT WHILE CLOSING CONNECTION",
        "NO CLOSE FRAME RECEIVED",
        "INTERNAL ERROR ENCOUNTERED",
    ))


def _is_live_operation_aborted(error) -> bool:
    """Recognize Gemini Live's 1008 'operation was aborted' close response.

    Some Live sessions are aborted by the service without a useful JSON body.
    Treat this specific close as a model/session failure so the reconnect loop
    can cool down that model and try another configured Live model.
    """
    text = _error_text(error).upper()
    return (
        ("1008" in text or "POLICY VIOLATION" in text)
        and ("OPERATION WAS ABORTED" in text or "OPERATION ABORTED" in text)
    )
