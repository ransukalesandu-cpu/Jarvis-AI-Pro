"""
JarvisAI Security — Auth Manager

Manages PIN vault, credential attempts, and system auth state transitions
(NORMAL, RESTRICTED_MODE, PRIVACY_LOCK).
"""

import threading
from typing import Optional, Callable

STATE_NORMAL = "NORMAL"
STATE_RESTRICTED_MODE = "RESTRICTED_MODE"
STATE_PRIVACY_LOCK = "PRIVACY_LOCK"


class AuthManager:
    """Manages PIN verification and authentication state."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.failed_pin_attempts: int = 0
        self.state: str = STATE_NORMAL
        self._stored_pin: Optional[str] = None
        self._lockdown_callback: Optional[Callable[[], None]] = None
        self._state_lock = threading.RLock()

    def set_pin(self, pin: str) -> None:
        """Store the configured PIN."""
        with self._state_lock:
            self._stored_pin = str(pin).strip()

    def set_lockdown_callback(self, callback: Callable[[], None]) -> None:
        """Register callback to execute when PRIVACY_LOCK is triggered."""
        with self._state_lock:
            self._lockdown_callback = callback

    def verify_pin(self, entered_pin: str) -> bool:
        """Verify entered PIN and update failed_pin_attempts counter."""
        with self._state_lock:
            if self.state == STATE_PRIVACY_LOCK:
                return False

            if self._stored_pin and entered_pin == self._stored_pin:
                self.failed_pin_attempts = 0
                return True

            # Record failed attempt
            self.failed_pin_attempts += 1
            if self.failed_pin_attempts >= 3:
                self._transition_to_privacy_lock_locked()
            return False

    def record_failed_attempt(self) -> int:
        """Record an explicit failed PIN or authorization attempt."""
        with self._state_lock:
            if self.state == STATE_PRIVACY_LOCK:
                return self.failed_pin_attempts

            self.failed_pin_attempts += 1
            if self.failed_pin_attempts >= 3:
                self._transition_to_privacy_lock_locked()
            return self.failed_pin_attempts

    def record_successful_attempt(self) -> None:
        """Reset failed attempt counter upon successful authentication."""
        with self._state_lock:
            self.failed_pin_attempts = 0

    def _transition_to_privacy_lock_locked(self) -> None:
        """Internal helper to set PRIVACY_LOCK state and invoke callback."""
        self.state = STATE_PRIVACY_LOCK
        cb = self._lockdown_callback
        if cb:
            # Trigger lockdown outside lock if needed or spawn task
            try:
                cb()
            except Exception as e:
                print(f"[AuthManager] Lockdown callback error: {e}")

    def set_state(self, new_state: str) -> None:
        """Set current authentication state."""
        with self._state_lock:
            self.state = new_state

    def get_state(self) -> str:
        """Get current authentication state."""
        with self._state_lock:
            return self.state

    def is_locked(self) -> bool:
        """Check if system is currently in PRIVACY_LOCK state."""
        with self._state_lock:
            return self.state == STATE_PRIVACY_LOCK

    def reset_attempts(self) -> None:
        """Reset failed attempts counter to 0."""
        with self._state_lock:
            self.failed_pin_attempts = 0


_default_auth_manager = AuthManager()


def get_auth_manager() -> AuthManager:
    return _default_auth_manager
