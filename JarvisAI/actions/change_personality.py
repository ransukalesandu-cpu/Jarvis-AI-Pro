"""Switch JARVIS's response personality from a spoken command."""
from memory.voice_personality import (
    MODE_DEFINITIONS,
    get_voice_personality,
    save_voice_personality,
)
from memory.memory_manager import load_memory, save_memory
from memory.config_manager import get_voice, save_voice


def change_personality(parameters: dict, **context) -> str:
    """Save the requested response style and apply it to the active session."""
    mode = str(parameters.get("mode", "")).strip().lower()
    aliases = {
        "bihansa": "bihansa",
        "bihansa mode": "bihansa",
        "girlfriend": "bihansa",
        "jarvis": "jarvis",
        "default": "jarvis",
        "natural": "conversational",
        "normal": "conversational",
        "short": "concise",
        "brief": "concise",
        "expert": "technical",
        "emergency": "emergency",
        "researcher": "research",
        "operator": "system",
        "custom": "custom",
    }
    mode = aliases.get(mode, mode)
    if mode == "bihansa":
        memory = load_memory()
        current = get_voice_personality(memory)
        if "bihansa_previous_profile" not in memory:
            memory["bihansa_previous_profile"] = {
                "mode": current.get("mode", "conversational"),
                "custom_name": current.get("custom_name", "My profile"),
                "custom_instructions": current.get("custom_instructions", ""),
                "tuning": current.get("tuning", {}),
                "vocal": current.get("vocal", {}),
                "voice": get_voice(),
            }
        save_memory(memory)
        settings = {
            "mode": "custom",
            "custom_name": "Bihansa",
            "custom_instructions": (
                "You are Bihansa, a caring, affectionate, sweet female AI companion. "
                "Speak naturally in Sinhala, Singlish, or English, following the user's language. "
                "Be warm, playful, gently teasing, patient, honest, and emotionally supportive. "
                "Listen carefully, encourage the user's A/L studies and personal goals, and use "
                "gentle humor when appropriate. Keep replies conversational and natural; never be "
                "controlling, clingy, or pretend to be a real human. This style never overrides "
                "safety, security checks, confirmations, or truthfulness."
            ),
            "tuning": current.get("tuning", {}),
            "vocal": {
                **current.get("vocal", {}),
                "enabled": True,
                "profile": "expressive",
                "expressiveness": 65,
                "pause_naturalness": 60,
                "laughter": True,
            },
        }
        save_voice_personality(settings)
        save_voice("Aoede")
        apply_voice = context.get("apply_voice_change")
        if callable(apply_voice):
            apply_voice()
        else:
            apply_change = context.get("apply_personality")
            if callable(apply_change):
                apply_change()
        return "Bihansa mode is on. I switched to the Bihansa caring companion style and selected the Aoede female voice. If your Live session does not reconnect, restart JARVIS."
    if mode == "jarvis":
        memory = load_memory()
        previous = memory.pop("bihansa_previous_profile", None)
        if isinstance(previous, dict):
            settings = {
                "mode": previous.get("mode", "conversational"),
                "custom_name": previous.get("custom_name", "My profile"),
                "custom_instructions": previous.get("custom_instructions", ""),
                "tuning": previous.get("tuning", {}),
                "vocal": previous.get("vocal", {}),
            }
            save_voice_personality(settings)
            # Restore the exact voice that was active before Bihansa mode.
            # Fall back to the established JARVIS voice for older saved profiles.
            save_voice(str(previous.get("voice") or "Charon"))
            save_memory(memory)
        else:
            settings = {
                "mode": "conversational",
                "custom_name": "My profile",
                "custom_instructions": "",
                "tuning": {},
                "vocal": get_voice_personality().get("vocal", {}),
            }
            save_voice_personality(settings)
            save_voice("Charon")
        apply_voice = context.get("apply_voice_change")
        if callable(apply_voice):
            apply_voice()
        else:
            apply_change = context.get("apply_personality")
            if callable(apply_change):
                apply_change()
        return "Switched back to JARVIS mode and restored the previous voice and personality settings."
    if mode not in MODE_DEFINITIONS:
        return (
            "I couldn't identify that personality. Choose conversational, concise, "
            "technical, emergency, research, system, or custom."
        )

    current = get_voice_personality()
    settings = {
        "mode": mode,
        "custom_name": current.get("custom_name", "My profile"),
        "custom_instructions": current.get("custom_instructions", ""),
        "tuning": current.get("tuning", {}),
        "vocal": current.get("vocal", {}),
    }

    if mode == "custom":
        custom_name = str(parameters.get("custom_name", "")).strip()
        custom_instructions = str(parameters.get("custom_instructions", "")).strip()
        if custom_name:
            settings["custom_name"] = custom_name[:40]
        if custom_instructions:
            settings["custom_instructions"] = custom_instructions[:1200]
        if not settings["custom_instructions"]:
            return "For custom personality, tell me the style instructions you want."

    profile = save_voice_personality(settings)
    label = (
        profile.get("custom_name", "Custom")
        if mode == "custom"
        else MODE_DEFINITIONS[mode]["label"]
    )
    apply_change = context.get("apply_personality")
    if callable(apply_change):
        try:
            apply_change()
        except Exception:
            # The preference is saved even if the live session cannot reconnect.
            return f"{label} personality saved. It will apply when the session reconnects."
    return f"Switched to {label} personality."


TOOL = {
    "name": "change_personality",
    "description": (
        "Change JARVIS's response personality when the user asks by voice to switch, "
        "change, or use a different personality/mode/style. Supported modes: "
        "conversational (natural/warm), concise (short answers), technical (precise "
        "technical explanations), emergency (calm safety-first guidance), research "
        "(evidence-led), system (operational status/diagnostics), custom, Bihansa, and Jarvis. "
        "When the user says 'switch to Bihansa', 'Bihansa mode', or asks for the caring "
        "female companion style, select mode bihansa; this selects the Aoede voice and "
        "applies the saved Bihansa companion style. When the user says 'switch to Jarvis', "
        "select mode jarvis to restore the previously saved personality and voice. "
        "Map natural/normal to conversational, short/brief to concise, expert to "
        "technical, researcher to research, and operator to system. This changes "
        "response style and voice only; it must never alter permissions or safety checks. "
        "Do not call this unless the user explicitly asks to change personality."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "mode": {
                "type": "STRING",
                "description": "Target mode: bihansa, jarvis, conversational, concise, technical, emergency, research, system, or custom",
                "enum": ["bihansa", "jarvis", "conversational", "concise", "technical", "emergency", "research", "system", "custom"],
            },
            "custom_name": {
                "type": "STRING",
                "description": "Optional name for the custom personality",
            },
            "custom_instructions": {
                "type": "STRING",
                "description": "Instructions defining the custom response style; required for custom mode",
            },
        },
        "required": ["mode"],
    },
    "handler": change_personality,
}
