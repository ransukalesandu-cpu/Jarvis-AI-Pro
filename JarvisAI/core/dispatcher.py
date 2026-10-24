"""
JarvisAI Core — Action Dispatcher

Dual-tier action access control integrated with security AuthManager state.
"""

from typing import Any, Callable, Optional
from security.auth_manager import get_auth_manager, STATE_PRIVACY_LOCK, STATE_RESTRICTED_MODE, STATE_NORMAL


class ActionDispatcher:
    """Dispatches tool/action execution checking current security state."""

    def __init__(self, action_registry=None):
        self.action_registry = action_registry
        self.auth_manager = get_auth_manager()

    def can_execute(self, action_name: str, user_role: str = "owner") -> tuple[bool, str]:
        """Check if action execution is allowed under current state."""
        state = self.auth_manager.get_state()
        if state == STATE_PRIVACY_LOCK:
            return False, "System is in PRIVACY_LOCK state. All commands are blocked."

        if state == STATE_RESTRICTED_MODE:
            # Restricted mode limits access to high-tier/sensitive actions unless owner
            if user_role != "owner":
                return False, f"Action '{action_name}' rejected in RESTRICTED_MODE for role '{user_role}'."

        return True, ""

    def dispatch(self, action_name: str, params: dict, run_func: Callable[[], Any], user_role: str = "owner") -> Any:
        """Dispatch action execution if authorized."""
        allowed, reason = self.can_execute(action_name, user_role)
        if not allowed:
            raise PermissionError(reason)
        return run_func()
