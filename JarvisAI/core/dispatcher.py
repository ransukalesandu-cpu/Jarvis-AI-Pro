"""
Central restricted/basic versus owner-privileged action policy.
Unknown actions are privileged by default.
"""
from __future__ import annotations

from security.auth_manager import (
    FULL_ACCESS_MODE, PRIVACY_LOCK,
)

TIER_1_BASIC = "TIER_1_BASIC"
TIER_2_PRIVILEGED = "TIER_2_PRIVILEGED"

# Basic, non-private tasks only. Do not add filesystem, memory, system-control,
# account, messaging, camera, or unknown plugin tools to this allowlist.
_TIER_1_ACTIONS = {
    "weather_report",
    "weather",
    "web_search",
    "news_search",
    "deep_reasoning",
    "general_llm_qa",
    "unit_converter",
    "local_time",
    "current_time",
    "timer",
    "quiz",
    "earth_globe",
}


class ActionDispatcher:
    """Fail-closed permission classifier used before any tool handler is called."""

    @staticmethod
    def get_action_tier(action_name: str) -> str:
        name = str(action_name or "").strip().lower()
        return TIER_1_BASIC if name in _TIER_1_ACTIONS else TIER_2_PRIVILEGED

    @classmethod
    def can_dispatch(cls, action_name: str, auth_state: str) -> tuple[bool, str]:
        tier = cls.get_action_tier(action_name)
        if auth_state == PRIVACY_LOCK:
            return False, "Privacy Lock is active. Private actions are blocked."
        if auth_state == FULL_ACCESS_MODE:
            return True, "Allowed"
        if tier == TIER_1_BASIC:
            return True, "Allowed"
        return False, "Owner verification is required for this action."
