"""Switch JARVIS's Gemini Live voice preset from a spoken command."""
from memory.config_manager import (
    AVAILABLE_VOICES,
    BIHANSA_FEMALE_VOICES,
    get_assistant_mode,
    save_bihansa_voice,
    save_voice,
)


_ALIASES = {
    "female": "Aoede",
    "female voice": "Aoede",
    "woman": "Aoede",
    "soft female": "Kore",
    "female soft": "Kore",
    "warm female": "Aoede",
    "default": "Charon",
    "normal": "Charon",
    "jarvis": "Charon",
}


def change_voice(parameters: dict, apply_voice_change=None, **context) -> str:
    """Persist a supported Live voice and reconnect so the next reply uses it."""
    requested = str(parameters.get("voice", "")).strip()
    if not requested:
        return "Tell me which voice preset to use: female, Kore, Aoede, Charon, Puck, or Fenrir."

    voice = _ALIASES.get(requested.casefold(), requested)
    lookup = {name.casefold(): name for name in AVAILABLE_VOICES}
    voice = lookup.get(str(voice).casefold(), "")
    if not voice:
        return (
            "That voice preset is not available. Choose one of: "
            + ", ".join(AVAILABLE_VOICES)
            + "."
        )

    mode = get_assistant_mode()
    if mode == "bihansa":
        # Bihansa only exposes its two configured female Live presets.
        selected = voice if voice in BIHANSA_FEMALE_VOICES else "Aoede"
        save_bihansa_voice(selected)
    else:
        selected = voice
        save_voice(selected)

    if callable(apply_voice_change):
        try:
            apply_voice_change()
        except Exception:
            return (
                f"Saved the {selected} voice preset. The active session could not "
                "reconnect automatically, so restart JARVIS to apply it."
            )

    return (
        f"Voice preset changed to {selected}. The new voice applies after the "
        "Live session reconnects. The provider's preset controls voice character; "
        "it does not guarantee an exact real-person voice."
    )


TOOL = {
    "name": "change_voice",
    "description": (
        "Change JARVIS's actual Gemini Live voice preset when explicitly requested. "
        "Accept natural requests such as 'switch to a female voice', 'use a softer "
        "female voice', 'change back to the default Jarvis voice', or a named preset. "
        "Map female/woman/warm female to Aoede, soft female to Kore, default/normal/Jarvis "
        "to Charon. Other supported presets are Puck, Fenrir, Kore, Aoede, and Charon. "
        "This changes the provider voice preset, not just the wording or personality. "
        "Do not call this for tone-only requests; use change_voice_style for tone."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "voice": {
                "type": "STRING",
                "description": (
                    "Preset or alias: female, soft female, warm female, default, "
                    "Charon, Puck, Kore, Fenrir, or Aoede."
                ),
                "enum": [
                    "female", "soft female", "warm female", "default",
                    "Charon", "Puck", "Kore", "Fenrir", "Aoede",
                ],
            }
        },
        "required": ["voice"],
    },
    "handler": change_voice,
}
