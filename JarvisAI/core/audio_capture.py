"""Microphone stream construction and device fallback policy.

The Live session still owns the application-specific callback and privacy/wake
logic. This module owns only opening a sounddevice input stream safely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class InputStreamOpenResult:
    """Stream returned by the preferred input device or the system default."""

    stream: Any
    used_default: bool = False
    selected_device_error: Exception | None = None


def open_input_stream_with_fallback(
    *,
    audio_backend: Any,
    selected_device: Any,
    sample_rate: int,
    channels: int,
    blocksize: int,
    callback: Callable[..., None],
) -> InputStreamOpenResult:
    """Open the selected microphone, falling back to the OS default if needed.

    A missing backend or a failure to open the default device is propagated to
    the caller. Only an explicitly selected device receives one default-device
    retry, matching JARVIS's existing startup behavior.
    """
    def _open(device: Any) -> Any:
        if audio_backend is None:
            raise RuntimeError("sounddevice is unavailable (PortAudio missing)")
        return audio_backend.InputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            blocksize=blocksize,
            device=device,
            callback=callback,
        )

    try:
        return InputStreamOpenResult(stream=_open(selected_device))
    except Exception as selected_error:
        if selected_device is None:
            raise
        stream = _open(None)
        return InputStreamOpenResult(
            stream=stream,
            used_default=True,
            selected_device_error=selected_error,
        )


def resample_input_audio(indata: Any, source_rate: int, target_rate: int) -> Any:
    """Resample a sounddevice int16 input block while preserving its shape.

    This mirrors the Live microphone callback's linear interpolation and
    clipping behavior. If conversion is unnecessary or the input is too short,
    the original block is returned unchanged.
    """
    import numpy as np

    if source_rate == target_rate or source_rate <= 0 or target_rate <= 0:
        return indata
    if getattr(indata, "size", 0) <= 0:
        return indata
    raw_mono = indata[:, 0] if indata.ndim > 1 else indata
    n_samples = int(round(len(raw_mono) * target_rate / source_rate))
    if n_samples <= 0 or len(raw_mono) <= 1:
        return indata
    old_x = np.linspace(0, 1, len(raw_mono))
    new_x = np.linspace(0, 1, n_samples)
    resampled_float = np.interp(new_x, old_x, raw_mono.astype(np.float32))
    resampled = np.clip(resampled_float, -32768, 32767).astype(np.int16)
    return resampled.reshape(-1, 1) if indata.ndim > 1 else resampled


def take_fixed_pcm_frames(buffer: bytearray, frame_bytes: int) -> list[bytes]:
    """Remove and return all complete fixed-size PCM frames from a buffer."""
    if frame_bytes <= 0:
        raise ValueError("frame_bytes must be positive")
    frames = []
    while len(buffer) >= frame_bytes:
        frames.append(bytes(buffer[:frame_bytes]))
        del buffer[:frame_bytes]
    return frames
