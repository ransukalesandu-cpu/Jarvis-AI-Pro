"""
Lockdown and audio stack hardening module for JARVIS AI Pro.
Handles Windows LockWorkStation return code verification, clean audio stream teardown,
and Privacy Lock execution.
"""
from __future__ import annotations

import ctypes
import sys
import logging
from typing import Any, Sequence

logger = logging.getLogger("Jarvis.Lockdown")


def clamp_lockdown_duration(duration: int | float) -> int:
    """Strictly enforce lockdown duration clamping between 60 and 300 seconds (1–5 minutes)."""
    try:
        val = int(duration)
    except (TypeError, ValueError):
        val = 60
    return max(60, min(val, 300))


def lock_workstation() -> tuple[bool, int]:
    """
    Lock the Windows workstation and verify return code.
    Returns (success: bool, error_code: int).
    On non-Windows systems, returns (False, 0).
    """
    if sys.platform != "win32":
        return False, 0
    try:
        res = ctypes.windll.user32.LockWorkStation()
        if res != 0:
            return True, 0
        err = ctypes.GetLastError()
        logger.error(f"[Lockdown] LockWorkStation failed with Windows error code: {err}")
        return False, err
    except Exception as exc:
        logger.error(f"[Lockdown] Exception during LockWorkStation call: {exc}")
        return False, -1


def teardown_audio_stream(stream: Any, instance: Any = None) -> bool:
    """
    Defensively terminate an audio stream and optional PyAudio/WASAPI/sounddevice instance.
    Calls stream.stop_stream() (or stream.stop()), followed by stream.close(), then instance termination.
    Catches and suppresses PortAudioError (-9988), device busy, or related exceptions.
    """
    if stream is None:
        return True

    # 1. Stop stream
    try:
        if hasattr(stream, "stop_stream") and callable(stream.stop_stream):
            stream.stop_stream()
        elif hasattr(stream, "stop") and callable(stream.stop):
            stream.stop()
        elif hasattr(stream, "abort") and callable(stream.abort):
            stream.abort()
    except Exception as exc:
        err_msg = str(exc)
        if "-9988" in err_msg or "PortAudioError" in type(exc).__name__:
            logger.warning(f"[AudioTeardown] Cleanly suppressed PortAudioError during stop: {exc}")
        else:
            logger.debug(f"[AudioTeardown] Error stopping audio stream: {exc}")

    # 2. Close stream
    try:
        if hasattr(stream, "close") and callable(stream.close):
            stream.close()
    except Exception as exc:
        err_msg = str(exc)
        if "-9988" in err_msg or "PortAudioError" in type(exc).__name__:
            logger.warning(f"[AudioTeardown] Cleanly suppressed PortAudioError during close: {exc}")
        else:
            logger.debug(f"[AudioTeardown] Error closing audio stream: {exc}")

    # 3. Terminate host instance if provided
    if instance is not None:
        try:
            if hasattr(instance, "terminate") and callable(instance.terminate):
                instance.terminate()
        except Exception as exc:
            logger.debug(f"[AudioTeardown] Error terminating audio instance: {exc}")

    return True


def execute_privacy_lockdown(
    streams: Sequence[Any] | None = None,
    instances: Sequence[Any] | None = None,
    duration: int = 60,
) -> dict[str, Any]:
    """
    Execute full Privacy Lock sequence:
    1. Lock Windows workstation and verify return code.
    2. Clamp lock duration (60-300s).
    3. Defensively tear down and mute audio streams.
    4. Return status report for emergency alerts and memory zeroization steps.
    """
    clamped_duration = clamp_lockdown_duration(duration)
    locked, win_err = lock_workstation()

    if streams:
        for idx, stream in enumerate(streams):
            inst = instances[idx] if instances and idx < len(instances) else None
            teardown_audio_stream(stream, inst)

    return {
        "workstation_locked": locked,
        "windows_error_code": win_err,
        "duration_seconds": clamped_duration,
        "fallback_security_active": not locked if sys.platform == "win32" else False,
    }
