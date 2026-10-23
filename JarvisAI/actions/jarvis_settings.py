"""Voice-friendly control of JARVIS's allowlisted local preferences.

Only known, non-secret preferences are exposed. This action never accepts file
paths, shell commands, API keys, or arbitrary config keys. Voice/personality
changes are persisted and take effect when the Live session reconnects.
"""
from __future__ import annotations

from memory import config_manager as cfg
from memory.voice_personality import (
    MODE_DEFINITIONS,
    get_voice_personality,
    save_voice_personality,
)

_BOOL_VALUES = {
    "on": True, "enable": True, "enabled": True, "true": True, "yes": True,
    "off": False, "disable": False, "disabled": False, "false": False, "no": False,
}

# Friendly names map to the exact Gemini Live voice IDs accepted by config_manager.
_VOICE_ALIASES = {
    "charon": "Charon", "male": "Charon", "male voice": "Charon",
    "puck": "Puck", "kore": "Kore", "female": "Kore", "female voice": "Kore",
    "aoede": "Aoede", "soft female": "Aoede", "warm female": "Aoede",
    "fenrir": "Fenrir",
}
_BOOL_SETTINGS = {
    "startup_intro": (
        cfg.get_startup_video_enabled, cfg.save_startup_video_enabled,
        "Show the optional animated startup intro before the HUD.",
    ),
    "wake_word": (
        cfg.get_wake_word_enabled, cfg.save_wake_word_enabled,
        "Require the local Hey JARVIS wake word while idle.",
    ),
    "push_to_talk": (
        cfg.get_push_to_talk_enabled, cfg.save_push_to_talk_enabled,
        "Use push-to-talk instead of always-open microphone listening.",
    ),
    "thinking": (
        cfg.get_thinking_enabled, cfg.save_thinking_enabled,
        "Allow the Live model's optional thinking mode.",
    ),
    "proactive_audio": (
        cfg.get_proactive_audio_enabled, cfg.save_proactive_audio_enabled,
        "Allow the Live model to decide when speech is addressed to JARVIS.",
    ),
    "morning_brief": (
        cfg.get_brief_enabled, cfg.save_brief_enabled,
        "Enable the optional morning brief.",
    ),
    "memory_provider_access": (
        cfg.get_memory_provider_access_enabled, cfg.save_memory_provider_access_enabled,
        "Allow saved memory context to be included in AI-provider requests.",
    ),
}
_ENUM_SETTINGS = {
    "media_resolution": (
        cfg.get_media_resolution, cfg.save_media_resolution, cfg.MEDIA_RESOLUTIONS,
        "Screenshot/camera detail level: default, low, medium, or high.",
    ),
    "hud_style": (
        cfg.get_hud_style, cfg.save_hud_style, cfg.HUD_STYLES,
        "HUD centrepiece: neural, neural_orb, face, or core.",
    ),
}
_SETTINGS_HELP = {
    "voice": "JARVIS speaking voice. Choices: Charon, Puck, Kore, Fenrir, Aoede; 'female' maps to Kore and 'soft female' maps to Aoede.",
    "personality_mode": "Response style: " + ", ".join(MODE_DEFINITIONS) + ".",
    "neural_render_scale": "Neural visualization scale: 1.0, 0.75, or 0.6.",
    "assistant_name": "The assistant's displayed name.",
    "user_name": "The name JARVIS uses to address the user.",
}


def _current_settings() -> dict:
    profile = get_voice_personality()
    return {
        "voice": cfg.get_voice(),
        "personality_mode": profile["mode"],
        "startup_intro": cfg.get_startup_video_enabled(),
        "wake_word": cfg.get_wake_word_enabled(),
        "push_to_talk": cfg.get_push_to_talk_enabled(),
        "thinking": cfg.get_thinking_enabled(),
        "proactive_audio": cfg.get_proactive_audio_enabled(),
        "morning_brief": cfg.get_brief_enabled(),
        "memory_provider_access": cfg.get_memory_provider_access_enabled(),
        "media_resolution": cfg.get_media_resolution(),
        "hud_style": cfg.get_hud_style(),
        "neural_render_scale": cfg.get_neural_render_scale(),
        "assistant_name": cfg.get_assistant_name(),
        "user_name": cfg.get_user_name(),
    }


def _parse_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    return _BOOL_VALUES.get(str(value or "").strip().lower())


def _set_setting(setting: str, raw_value) -> str:
    value = str(raw_value if raw_value is not None else "").strip()
    lowered = value.lower()

    if setting == "voice":
        voice = _VOICE_ALIASES.get(lowered)
        if voice is None:
            voice = next((v for v in cfg.AVAILABLE_VOICES if v.lower() == lowered), None)
        if voice is None:
            return "Unknown voice. Choose Charon, Puck, Kore, Fenrir, or Aoede."
        cfg.save_voice(voice)
        return f"Saved JARVIS voice as {voice}. It takes effect after the Live session reconnects."

    if setting in _BOOL_SETTINGS:
        parsed = _parse_bool(raw_value)
        if parsed is None:
            return f"Please say on/off for {setting}. No setting was changed."
        getter, setter, _description = _BOOL_SETTINGS[setting]
        if getter() == parsed:
            return f"{setting} is already {'on' if parsed else 'off'}."
        setter(parsed)
        if setting == "memory_provider_access":
            return ("Saved memory-provider access as " + ("on" if parsed else "off")
                    + ". This changes whether stored memory may be included in provider requests.")
        return f"Turned {setting.replace('_', ' ')} {'on' if parsed else 'off'}."

    if setting in _ENUM_SETTINGS:
        getter, setter, choices, _description = _ENUM_SETTINGS[setting]
        choice = lowered
        if choice not in choices:
            return f"Invalid {setting}. Choose one of: {', '.join(choices)}."
        if getter() == choice:
            return f"{setting.replace('_', ' ')} is already {choice}."
        setter(choice)
        return f"Saved {setting.replace('_', ' ')} as {choice}."

    if setting == "neural_render_scale":
        try:
            scale = float(value)
        except (TypeError, ValueError):
            return "Say 1.0, 0.75, or 0.6 for neural render scale."
        if scale not in cfg.NEURAL_RENDER_SCALES:
            return "Neural render scale must be exactly 1.0, 0.75, or 0.6."
        cfg.save_neural_render_scale(scale)
        return f"Saved neural render scale as {scale}."

    if setting == "personality_mode":
        mode = lowered.replace(" ", "_")
        if mode not in MODE_DEFINITIONS:
            return "Unknown personality mode. Choose: " + ", ".join(MODE_DEFINITIONS) + "."
        profile = get_voice_personality()
        profile["mode"] = mode
        save_voice_personality(profile)
        return f"Saved response personality as {mode}. It takes effect after the Live session reconnects."

    if setting in ("assistant_name", "user_name"):
        if not value or len(value) > 40 or any(ord(c) < 32 for c in value):
            return "Please give a name of 1–40 normal characters. No change was made."
        assistant_name = value if setting == "assistant_name" else cfg.get_assistant_name()
        user_name = value if setting == "user_name" else cfg.get_user_name()
        cfg.save_assistant_config(assistant_name, user_name)
        return f"Saved {setting.replace('_', ' ')} as {value}."

    return "That setting is not on JARVIS's voice-control allowlist. No changes were made."


def jarvis_settings(parameters: dict, **_kwargs) -> str:
    """Read current preferences or change exactly one allowlisted setting."""
    operation = str(parameters.get("operation", "get")).strip().lower()
    if operation == "get":
        current = _current_settings()
        requested = str(parameters.get("setting", "")).strip().lower()
        if requested:
            if requested not in current:
                return "Unknown setting. Available settings: " + ", ".join(current) + "."
            return f"{requested.replace('_', ' ')} is currently {current[requested]!s}."
        return "Current JARVIS settings:\n" + "\n".join(
            f"- {key.replace('_', ' ')}: {value}" for key, value in current.items()
        )
    if operation == "set":
        setting = str(parameters.get("setting", "")).strip().lower()
        if setting not in _current_settings():
            return "Choose one setting: " + ", ".join(_current_settings()) + "."
        if "value" not in parameters:
            return "Tell me the value to set. No setting was changed."
        return _set_setting(setting, parameters.get("value"))
    return "Choose operation 'get' or 'set'."


TOOL = {
    "name": "jarvis_settings",
    "description": (
        "Understand natural spoken requests to inspect or change JARVIS's own allowlisted "
        "preferences. Use operation=get to read all settings or one named setting. Use "
        "operation=set to change exactly one setting using its setting name and value. "
        "Examples: set voice to 'female' (Kore), startup_intro to 'off', wake_word to "
        "'on', media_resolution to 'high', personality_mode to 'concise'. Never invent "
        "unsupported settings or values. Ask the user to clarify if the requested setting "
        "or value is ambiguous. Never change API keys, security controls, files, or OS settings. "
        "Voice/personality changes are persisted and apply after the Live session reconnects."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {
                "type": "STRING", "enum": ["get", "set"],
                "description": "Read current settings or change one allowlisted preference.",
            },
            "setting": {
                "type": "STRING",
                "enum": [
                    "voice", "personality_mode", "startup_intro", "wake_word",
                    "push_to_talk", "thinking", "proactive_audio", "morning_brief",
                    "memory_provider_access", "media_resolution", "hud_style",
                    "neural_render_scale", "assistant_name", "user_name",
                ],
                "description": "Exact setting to read or change.",
            },
            "value": {
                "type": "STRING",
                "description": "New setting value, such as female, off, high, concise, or 0.75.",
            },
        },
        "required": ["operation"],
    },
    "handler": jarvis_settings,
}
