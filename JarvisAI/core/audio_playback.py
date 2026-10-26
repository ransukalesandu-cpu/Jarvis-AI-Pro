"""Output-device stream setup and fallback helpers for JARVIS playback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OutputStreamOpenResult:
    """Stream selected by the user, or the OS default after a failed open."""

    stream: Any
    used_default: bool = False
    selected_device_error: Exception | None = None


def open_output_stream(
    audio_backend: Any,
    device: Any,
    sample_rate: int,
    channels: int,
    blocksize: int,
) -> Any:
    """Open and start a raw signed-16-bit PCM output stream."""
    if audio_backend is None:
        raise RuntimeError("sounddevice is unavailable (PortAudio missing)")
    stream = audio_backend.RawOutputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        blocksize=blocksize,
        device=device,
    )
    stream.start()
    return stream


def open_output_stream_with_fallback(
    *,
    audio_backend: Any,
    selected_device: Any,
    sample_rate: int,
    channels: int,
    blocksize: int,
) -> OutputStreamOpenResult:
    """Try the selected output, then the system default exactly once."""
    try:
        return OutputStreamOpenResult(
            stream=open_output_stream(
                audio_backend, selected_device, sample_rate, channels, blocksize
            )
        )
    except Exception as selected_error:
        if selected_device is None:
            raise
        stream = open_output_stream(audio_backend, None, sample_rate, channels, blocksize)
        return OutputStreamOpenResult(
            stream=stream,
            used_default=True,
            selected_device_error=selected_error,
        )


def describe_output_route(audio_backend: Any, device: Any) -> str:
    """Return a best-effort device/host-API label for diagnostics."""
    try:
        if audio_backend is None:
            return repr(device)
        info = audio_backend.query_devices(device, "output")
        hostapis = audio_backend.query_hostapis()
        host_index = int(info.get("hostapi", -1))
        api_name = (
            hostapis[host_index].get("name", "unknown host API")
            if 0 <= host_index < len(hostapis)
            else "unknown host API"
        )
        return f"{info.get('name', 'unknown device')} via {api_name}"
    except Exception:
        return repr(device)


def stream_device_index(active_stream: Any, requested_device: Any) -> Any:
    """Read a resolved output index from a stream, if the backend exposes it."""
    try:
        value = getattr(active_stream, "device", None)
        if isinstance(value, (tuple, list)):
            value = value[-1] if value else None
        if value is not None:
            return int(value)
    except (TypeError, ValueError, RuntimeError):
        pass
    return requested_device


async def open_verified_output_fallback(
    *,
    audio_backend: Any,
    device_service: Any,
    sample_rate: int,
    channels: int,
    blocksize: int,
    excluded_device: Any,
):
    """Find and open another output device after proving it accepts live output."""
    try:
        candidates = await asyncio.to_thread(device_service.list_devices, "output")
    except Exception as exc:
        print(f"[AudioTrace 4/OUTPUT] Could not enumerate fallback speakers: {exc}")
        return None

    for candidate_name in candidates:
        try:
            candidate_device = await asyncio.to_thread(
                device_service.resolve, candidate_name, "output"
            )
            if candidate_device is None or candidate_device == excluded_device:
                continue
            works = await asyncio.to_thread(
                device_service.probe_transport, candidate_device, "output"
            )
            if not works:
                continue
            candidate_stream = await asyncio.to_thread(
                open_output_stream,
                audio_backend,
                candidate_device,
                sample_rate,
                channels,
                blocksize,
            )
            return candidate_name, candidate_device, candidate_stream
        except Exception as exc:
            print(
                f"[AudioTrace 4/OUTPUT] Fallback speaker "
                f"{candidate_name!r} unavailable: {exc}"
            )
    return None
