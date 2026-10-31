"""Open YouTube Music search inside JARVIS's native HUD workspace.

This action deliberately does not launch an external browser or desktop player.
The ActionRegistry supplies the active HUD as the `player` context; its
`show_webpage` method displays YouTube Music in the existing in-app web tab.
"""
from __future__ import annotations

from urllib.parse import quote_plus


TOOL = {
    "name": "play_music",
    "description": (
        "Search for and open a song, artist, or genre in YouTube Music inside "
        "the JARVIS HUD. Does not launch an external browser."
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


def play_music(parameters: dict, player=None, **_context) -> str:
    """Open YouTube Music search in the active JARVIS HUD."""
    query = str((parameters or {}).get("query", "")).strip()
    if not query:
        return "Tell me the song title, artist, or music style you want to find."
    query = query[:200]

    if player is None or not callable(getattr(player, "show_webpage", None)):
        return "YouTube Music cannot open because the JARVIS in-app workspace is unavailable."

    url = "https://music.youtube.com/search?q=" + quote_plus(query)
    try:
        player.show_webpage(url, "YOUTUBE MUSIC")
    except Exception as exc:
        return f"Could not open YouTube Music inside JARVIS: {type(exc).__name__}."

    return f"Opened YouTube Music inside JARVIS for: {query}. Select a result to play."


TOOL["handler"] = play_music
