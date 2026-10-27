"""Persist a voice-delivery tone requested through the Live conversation."""
from memory.voice_personality import get_voice_personality, save_voice_personality


_STYLE_PRESETS = {
    "natural": {"tone": "natural", "profile": "natural"},
    "normal": {"tone": "natural", "profile": "natural"},
    "soft": {"tone": "soft", "profile": "natural", "pause_naturalness": 60},
    "gentle": {"tone": "soft", "profile": "natural", "pause_naturalness": 60},
    "calm": {"tone": "soft", "profile": "natural", "pause_naturalness": 65},
    "confident": {"tone": "confident", "profile": "professional"},
    "powerful": {"tone": "confident", "profile": "professional", "expressiveness": 45},
    "energetic": {"tone": "energetic", "profile": "expressive", "expressiveness": 70},
    "excited": {"tone": "energetic", "profile": "expressive", "expressiveness": 75},
    "dramatic": {"tone": "dramatic", "profile": "expressive", "expressiveness": 80, "pause_naturalness": 70},
    "cinematic": {"tone": "dramatic", "profile": "expressive", "expressiveness": 80, "pause_naturalness": 70},
    "robotic": {"tone": "robotic", "profile": "minimal", "expressiveness": 10, "pause_naturalness": 20},
    "professional": {"tone": "confident", "profile": "professional"},
}


def change_voice_style(parameters: dict, apply_personality=None, **context) -> str:
    """Update persistent delivery guidance and reconnect the current Live session."""
    requested = str(parameters.get("style", "")).strip().casefold()
    preset = _STYLE_PRESETS.get(requested)
    if preset is None:
        return (
            "I couldn't identify that voice style. Choose natural, soft, calm, "
            "confident, energetic, dramatic, robotic, or professional."
        )

    current = get_voice_personality()
    vocal = dict(current.get("vocal", {}))
    vocal.update(preset)
    updated = save_voice_personality({
        "mode": current.get("mode", "auto"),
        "custom_name": current.get("custom_name", "My profile"),
        "custom_instructions": current.get("custom_instructions", ""),
        "tuning": current.get("tuning", {}),
        "vocal": vocal,
    })

    if callable(apply_personality):
        try:
            apply_personality()
        except Exception:
            return (
                f"Saved the {requested} voice delivery style. The Live session "
                "could not reconnect automatically; restart JARVIS to apply it."
            )

    return (
        f"Voice delivery style set to {requested}. It changes the model's speaking "
        "guidance and takes effect after the Live session reconnects. The provider "
        "may not reproduce exact pitch or timbre controls."
    )


TOOL = {
    "name": "change_voice_style",
    "description": (
        "Change JARVIS's vocal delivery tone when the user explicitly asks to sound "
        "soft/gentle, calm, confident, powerful, energetic/excited, dramatic/cinematic, "
        "robotic, professional, or natural/normal. This adjusts saved speech-delivery "
        "guidance and reconnects the Live session. It does not change the actual voice "
        "preset; call change_voice for requests such as switching to a female voice."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "style": {
                "type": "STRING",
                "description": (
                    "Delivery style: natural, soft, calm, confident, powerful, "
                    "energetic, excited, dramatic, cinematic, robotic, professional."
                ),
                "enum": [
                    "natural", "soft", "calm", "confident", "powerful",
                    "energetic", "excited", "dramatic", "cinematic", "robotic",
                    "professional",
                ],
            }
        },
        "required": ["style"],
    },
    "handler": change_voice_style,
}
