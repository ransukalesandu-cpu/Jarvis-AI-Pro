"""
JarvisAI/core/dispatcher.py — Dual-Tier Action Dispatcher.

Categorizes actions into:
  - TIER_1_BASIC: Weather queries, general LLM Q&A, public web search, unit conversions, local time/timers, volume adjustments.
  - TIER_2_PRIVILEGED: OS execution, PowerShell/CMD commands, opening/writing files, reading private data/emails, camera access, IoT/3D-printer control.

Enforces execution policy based on Auth State (RESTRICTED_MODE vs FULL_ACCESS_MODE).
"""

from __future__ import annotations

from security.auth_manager import RESTRICTED_MODE, FULL_ACCESS_MODE, CHALLENGE_MODE, PRIVACY_LOCK

TIER_1_BASIC = "TIER_1_BASIC"
TIER_2_PRIVILEGED = "TIER_2_PRIVILEGED"

# Explicit categorization mapping
_TIER_1_ACTIONS = {
    "weather_report",
    "web_search",
    "deep_reasoning",
    "unit_converter",
    "local_time",
    "timer",
    "volume_adjust",
    "volume_control",
    "general_llm_qa",
    "earth_globe",
    "battery_status",
    "system_status",
    "system_monitor",
    "recall_memory",
    "memory_health",
    "quiz",
    "manage_monitor",
    "close_camera",
    "proactive_feedback",
    "ui_interaction",
    "undo",
}

_TIER_2_ACTIONS = {
    "code_helper",
    "file_controller",
    "computer_control",
    "computer_settings",
    "open_app",
    "send_message",
    "email_gmail",
    "instagram_account",
    "phone_call",
    "printer_control",
    "home_automation",
    "holo_gestures",
    "dev_agent",
    "game_updater",
    "shutdown_jarvis",
    "screen_process",
    "desktop",
    "desktop_control",
    "file_processor",
    "self_heal",
    "self_update",
    "purge_memory",
    "memory_export",
    "memory_import",
    "spotify_control",
    "youtube_video",
    "browser_control",
    "calendar_google",
    "flight_finder",
    "reminder",
    "save_memory",
    "remember_intention",
}


class ActionDispatcher:
    """Dispatches tool calls according to auth state and tier privileges."""

    @staticmethod
    def get_action_tier(action_name: str) -> str:
        """Categorize action into TIER_1_BASIC or TIER_2_PRIVILEGED."""
        name = str(action_name).strip().lower()
        if name in _TIER_1_ACTIONS:
            return TIER_1_BASIC
        return TIER_2_PRIVILEGED

    @classmethod
    def can_dispatch(cls, action_name: str, auth_state: str) -> tuple[bool, str]:
        """
        Check if an action can be executed in the current auth_state.
        Returns: (allowed: bool, prompt_or_reason: str)
        """
        tier = cls.get_action_tier(action_name)

        if auth_state == FULL_ACCESS_MODE:
            return True, "Allowed"

        if auth_state == PRIVACY_LOCK:
            return False, "System locked in PRIVACY_LOCK mode."

        if tier == TIER_1_BASIC:
            return True, "Allowed"

        # TIER_2_PRIVILEGED in RESTRICTED_MODE or CHALLENGE_MODE -> Intercept & prompt for PIN
        return False, "Voice identity unconfirmed. Please enter or speak your PIN."
