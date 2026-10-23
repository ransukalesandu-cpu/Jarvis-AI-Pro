"""Switch JARVIS's response personality from a spoken command."""
from memory.voice_personality import (
    MODE_DEFINITIONS,
    get_voice_personality,
    save_voice_personality,
)


def change_personality(parameters: dict, **context) -> str:
    """Save the requested response style and apply it to the active session."""
    mode = str(parameters.get("mode", "")).strip().lower()
    aliases = {
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
        "(evidence-led), system (operational status/diagnostics), and custom. "
        "Map natural/normal to conversational, short/brief to concise, expert to "
        "technical, researcher to research, and operator to system. This changes "
        "response style only; it must never alter permissions or safety checks. "
        "Do not call this unless the user explicitly asks to change personality."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "mode": {
                "type": "STRING",
                "description": "Target mode: conversational, concise, technical, emergency, research, system, or custom",
                "enum": ["conversational", "concise", "technical", "emergency", "research", "system", "custom"],
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
