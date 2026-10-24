"""
JarvisAI Security — Lockdown Engine

Executes the emergency Privacy Lock defense protocol when 3 consecutive
incorrect PIN/credential attempts occur.
"""

import ctypes
import os
import sys
import threading
import time
from typing import Callable, Optional

from security.auth_manager import get_auth_manager, STATE_PRIVACY_LOCK, STATE_RESTRICTED_MODE, STATE_NORMAL
from memory.config_manager import get_privacy_lock_duration_seconds


# Global callbacks for process silencing and memory zeroing
_tts_stop_cb: Optional[Callable[[], None]] = None
_mic_suspend_cb: Optional[Callable[[], None]] = None
_mic_restore_cb: Optional[Callable[[], None]] = None
_clear_memory_cb: Optional[Callable[[], None]] = None
_clear_tokens_cb: Optional[Callable[[], None]] = None
_lock_win_mock: Optional[Callable[[], None]] = None  # Hook for unit testing

_lock_thread: Optional[threading.Thread] = None
_lock_start_monotonic: float = 0.0
_effective_duration: int = 180
_lockdown_mutex = threading.Lock()


def register_silencing_hooks(
    tts_stop: Optional[Callable[[], None]] = None,
    mic_suspend: Optional[Callable[[], None]] = None,
    mic_restore: Optional[Callable[[], None]] = None,
    clear_memory: Optional[Callable[[], None]] = None,
    clear_tokens: Optional[Callable[[], None]] = None,
) -> None:
    """Register system callbacks for audio silencing and data protection."""
    global _tts_stop_cb, _mic_suspend_cb, _mic_restore_cb, _clear_memory_cb, _clear_tokens_cb
    _tts_stop_cb = tts_stop
    _mic_suspend_cb = mic_suspend
    _mic_restore_cb = mic_restore
    _clear_memory_cb = clear_memory
    _clear_tokens_cb = clear_tokens


def set_lock_workstation_mock(mock_func: Optional[Callable[[], None]]) -> None:
    """Set mock function for LockWorkStation testing."""
    global _lock_win_mock
    _lock_win_mock = mock_func


def clamp_duration(configured_duration: int) -> int:
    """Strictly clamp Privacy Lock duration to between 60s (1 min) and 300s (5 min)."""
    return max(60, min(int(configured_duration), 300))


def _secure_zero_memory() -> None:
    """Zero out sensitive conversation memory buffers and clear tokens/handles."""
    if _clear_memory_cb:
        try:
            _clear_memory_cb()
        except Exception as e:
            print(f"[Lockdown] Error clearing conversation memory: {e}")

    if _clear_tokens_cb:
        try:
            _clear_tokens_cb()
        except Exception as e:
            print(f"[Lockdown] Error clearing session tokens: {e}")


def _execute_windows_os_lock() -> bool:
    """Call native Windows OS lock API via ctypes.windll.user32.LockWorkStation()."""
    if _lock_win_mock is not None:
        try:
            _lock_win_mock()
            return True
        except Exception as e:
            print(f"[Lockdown] Mock LockWorkStation failed: {e}")
            return False

    if os.name == "nt" or sys.platform == "win32":
        try:
            ctypes.windll.user32.LockWorkStation()
            return True
        except Exception as e:
            print(f"[Lockdown] LockWorkStation failed: {e}")
            return False
    return False


def trigger_privacy_lock(configured_duration: Optional[int] = None) -> int:
    """Trigger the complete emergency Privacy Lock sequence.

    Returns the effective_duration in seconds.
    """
    global _lock_thread, _lock_start_monotonic, _effective_duration

    with _lockdown_mutex:
        auth_mgr = get_auth_manager()

        if configured_duration is None:
            configured_duration = get_privacy_lock_duration_seconds()

        _effective_duration = clamp_duration(configured_duration)
        _lock_start_monotonic = time.monotonic()

        # Transition state
        auth_mgr.set_state(STATE_PRIVACY_LOCK)

        # 1. Windows OS Lock
        _execute_windows_os_lock()

        # 2. Process Silencing
        if _tts_stop_cb:
            try:
                _tts_stop_cb()
            except Exception as e:
                print(f"[Lockdown] Error stopping TTS playback: {e}")

        if _mic_suspend_cb:
            try:
                _mic_suspend_cb()
            except Exception as e:
                print(f"[Lockdown] Error suspending mic input: {e}")

        # 3. Block Private Information
        _secure_zero_memory()

        # 4. Dispatch emergency alerts
        try:
            from notifications.alert_service import dispatch_privacy_lock_alert
            dispatch_privacy_lock_alert(_effective_duration)
        except Exception as e:
            print(f"[Lockdown] Alert dispatch error: {e}")

        # 5. Start Monotonic Timer Countdown Thread
        if _lock_thread is None or not _lock_thread.is_alive():
            _lock_thread = threading.Thread(
                target=_lockdown_timer_worker,
                args=(_effective_duration,),
                daemon=True,
                name="PrivacyLockTimer",
            )
            _lock_thread.start()

        return _effective_duration


def _lockdown_timer_worker(duration: int) -> None:
    """Worker thread tracking monotonic countdown."""
    start_time = time.monotonic()
    while True:
        elapsed = time.monotonic() - start_time
        if elapsed >= duration:
            break
        time.sleep(min(1.0, duration - elapsed))

    clear_privacy_lock()


def clear_privacy_lock() -> None:
    """Clear Privacy Lock state upon monotonic countdown expiration."""
    with _lockdown_mutex:
        auth_mgr = get_auth_manager()

        # Reset failed pin attempts
        auth_mgr.reset_attempts()

        # Restore mic listening in RESTRICTED_MODE
        auth_mgr.set_state(STATE_RESTRICTED_MODE)

        if _mic_restore_cb:
            try:
                _mic_restore_cb()
            except Exception as e:
                print(f"[Lockdown] Error restoring mic input: {e}")

        print("[Lockdown] Privacy Lock cleared. System returned to RESTRICTED_MODE standby.")


def is_privacy_locked() -> bool:
    """Check if Privacy Lock is currently active."""
    return get_auth_manager().is_locked()


# Wire auth_manager lockdown callback to trigger_privacy_lock
get_auth_manager().set_lockdown_callback(trigger_privacy_lock)
