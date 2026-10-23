"""Open a YouTube search for music requested by the user.

This action opens search results rather than automatically playing a video, so
the user can choose the correct song and avoid unexpected audio.
"""
from __future__ import annotations

from urllib.parse import quote_plus
import webbrowser

TOOL = {
    "name": "play_music",
    "description": (
        "Find music requested by the user by opening YouTube search results. "
        "Use when the user asks to play, find, or listen to a song, artist, or genre. "
        "This opens results for the user to choose; it does not auto-play or download audio."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Song title, artist, or music style to search for."
            }
        },
        "required": ["query"]
    },
    "handler": None,
}


def play_music(parameters: dict, **_context) -> str:
    """Open YouTube search results for a non-empty music query."""
    query = str((parameters or {}).get("query", "")).strip()
    if not query:
        return "Tell me the song title, artist, or music style you want to find."
    if len(query) > 200:
        query = query[:200]
    url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
    opened = webbrowser.open(url, new=2)
    if opened:
        return f"Opened YouTube search results for: {query}. Choose a result to play."
    return "I couldn't open your browser. Please check your default browser settings."


TOOL["handler"] = play_music
