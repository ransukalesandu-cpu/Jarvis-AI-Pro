"""Ask the Live audio model to perform a short, original song."""
from __future__ import annotations


_ALLOWED_MOODS = {
    "happy", "motivational", "calm", "funny", "romantic", "epic",
    "sad", "peaceful", "upbeat", "inspirational",
}
_ALLOWED_LANGUAGES = {"sinhala", "english", "singlish", "auto"}


def sing_song(parameters: dict, **context) -> str:
    """Return a clear singing instruction for the model's next audio response."""
    topic = " ".join(str(parameters.get("topic", "") or "").split())[:180]
    mood = str(parameters.get("mood", "happy") or "happy").strip().casefold()
    language = str(parameters.get("language", "auto") or "auto").strip().casefold()
    if mood not in _ALLOWED_MOODS:
        mood = "happy"
    if language not in _ALLOWED_LANGUAGES:
        language = "auto"

    topic_line = f"Topic: {topic}." if topic else "Topic: make it fun and memorable."
    language_line = {
        "sinhala": "Sing in Sinhala.",
        "english": "Sing in English.",
        "singlish": "Sing naturally in Sinhala-English Singlish.",
        "auto": "Use the language the user is currently speaking.",
    }[language]
    return (
        "SINGING REQUEST — perform a short original song in the upcoming audio reply; "
        "do not merely explain that you can sing and do not read the lyrics like normal prose. "
        "Create new lyrics and a simple, clearly melodic vocal performance, around 15–25 seconds. "
        f"{topic_line} Mood: {mood}. {language_line} "
        "Do not reproduce lyrics from a copyrighted song. If the user named an existing song, "
        "make a new song with a broad similar mood or theme instead of copying its lyrics. "
        "After singing, stop naturally without a long explanation."
    )


TOOL = {
    "name": "sing_song",
    "description": (
        "When the user asks JARVIS to sing a song, sing, hum a melody, or make a short "
        "motivational/funny/calm song, call this tool. It requests a short original 15–25 "
        "second melodic performance in the next audio reply, not spoken lyrics. Accept an "
        "optional topic, mood and language. Do not copy lyrics from a named copyrighted song; "
        "make an original song with a broad similar mood or theme instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "topic": {
                "type": "STRING",
                "description": "Optional subject, such as motivation, studying, or a funny day.",
            },
            "mood": {
                "type": "STRING",
                "description": "Song mood.",
                "enum": [
                    "happy", "motivational", "calm", "funny", "romantic",
                    "epic", "sad", "peaceful", "upbeat", "inspirational",
                ],
            },
            "language": {
                "type": "STRING",
                "description": "Language for the original song.",
                "enum": ["auto", "sinhala", "english", "singlish"],
            },
        },
        "required": [],
    },
    "handler": sing_song,
}
