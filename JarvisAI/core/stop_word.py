"""The stop word: "Jarvis, stop" ends whatever JARVIS is doing.

Matched locally on the owner's transcribed speech in the voice loop (never by
asking the model), so it works while a long tool call is running. The loop
then cancels running tool calls and background jobs, stops speech and goes
back to listening (JarvisLive._handle_stop_word).

The assistant's name is required ("Jarvis, stop", "stop Jarvis", "hey Jarvis
cancel"), so the word "stop" inside an ordinary request does not trigger it.
The current assistant name (if renamed) is accepted too.
"""
from __future__ import annotations

import re

_STOP_WORDS = r"(?:stop|cancel|halt|abort|enough|stop it|stop that|be quiet|quiet|shut up|nawattanna|nawaththanna|natara\s+karanna)"


def _pattern(names: tuple[str, ...]) -> re.Pattern:
    alt = "|".join(re.escape(n.casefold()) for n in names if n)
    return re.compile(
        rf"^(?:(?:hey|ok|okay)\s+)?(?:{alt})\s*(?:please\s+)?{_STOP_WORDS}\b"
        rf"|^{_STOP_WORDS}\s+(?:it\s+)?(?:{alt})\b"
    )


def is_stop_command(text: str, assistant_name: str = "") -> bool:
    phrase = re.sub(r"[^\w\s]", " ", str(text or "").casefold())
    phrase = " ".join(phrase.split())
    if not phrase or len(phrase) > 60:
        return False      # a long sentence is a request, not a stop
    names = ("jarvis", "jarvis ai", *( (assistant_name.strip(),) if assistant_name else ()))
    return bool(_pattern(names).search(phrase))
