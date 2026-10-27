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
