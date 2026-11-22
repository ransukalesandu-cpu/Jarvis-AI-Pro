"""Voice tool: offline dictation into any text box, and offline transcription of audio files."""
from __future__ import annotations

import threading
from pathlib import Path

from jarvis.voice import local_stt

_ACTIONS = ("dictate", "stop", "transcribe_file", "status")
_stop = threading.Event()


def dictation(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "status").strip().lower()
    if action not in _ACTIONS:
        return f"Unknown dictation action '{action}'. Use one of: {', '.join(_ACTIONS)}."
    if action == "status":
        if not local_stt.available():
            return "Offline speech-to-text is not installed. Run: pip install -r requirements-stt.txt"
        return f"Offline speech-to-text ready (model {local_stt.os.environ.get('JARVIS_STT_MODEL', local_stt.DEFAULT_MODEL)})."
    if action == "stop":
        _stop.set()
        return "Dictation stopped."
    try:
        if action == "transcribe_file":
            path = Path(str(p.get("path") or "").strip().strip('"')).expanduser()
            if not path.is_file():
                return f"File not found: {path}"
            r = local_stt.transcribe(path, language=str(p.get("language") or ""))
            out = path.with_suffix(".txt")
            if not out.exists():
                out.write_text(r["text"], encoding="utf-8")
                from jarvis import library
                library.register(out, "document", source="dictation", note=f"transcript of {path.name}")
            return f"Transcript ({r['language']}, {r['seconds']}s):\n{r['text'][:3000]}"
        if not local_stt.available():
            return "Offline speech-to-text is not installed. Run: pip install -r requirements-stt.txt"
        _stop.clear()
        if speak:
            speak("Dictating. Speak now; I'll stop when you pause.")
        audio = local_stt.record(float(p.get("seconds") or 0), stop=_stop)
        r = local_stt.transcribe(audio, language=str(p.get("language") or ""))
        text = r["text"]
        if not text:
            return "I didn't catch anything."
        if p.get("type_into_app", True):
            local_stt.type_text(text)
            return f"Typed: {text}"
        return text
    except RuntimeError as e:
        return f"Dictation: {e}"
    except OSError as e:
        return f"Dictation: audio problem ({e})."


TOOL = {
    "name": "dictation",
    "description": (
        "Offline speech-to-text (faster-whisper, runs on the PC). 'dictate' records the owner until they pause and "
        "types the words into the focused app (type_into_app=false just returns the text); 'stop'; "
        "'transcribe_file' turns an audio/video file into text (saved as .txt next to it); 'status'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(_ACTIONS)},
            "path": {"type": "STRING", "description": "Audio/video file (transcribe_file)."},
            "language": {"type": "STRING", "description": "Optional language code, e.g. 'si', 'en'."},
            "seconds": {"type": "NUMBER", "description": "Fixed recording length; default = until a pause."},
            "type_into_app": {"type": "BOOLEAN"},
        },
        "required": ["action"],
    },
    "handler": dictation,
    "risk": "write",
    "timeout": 300,
}
