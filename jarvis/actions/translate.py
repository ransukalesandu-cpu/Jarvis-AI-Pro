"""Voice tool: translate text, the clipboard or a whole document."""
from __future__ import annotations

from jarvis import translate as tr

_ACTIONS = ("text", "clipboard", "file", "history")


def translate(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "text").strip().lower()
    target = str(p.get("target_language") or "").strip()
    source = str(p.get("source_language") or "").strip()
    if action not in _ACTIONS:
        return f"Unknown translate action '{action}'. Use one of: {', '.join(_ACTIONS)}."
    try:
        if action == "history":
            items = tr.history(int(p.get("limit") or 5))
            if not items:
                return "No translations yet."
            return "Recent translations:\n" + "\n".join(f"- → {h['to']}: {h['out'][:120]}" for h in items)
        if action == "file":
            if speak:
                speak("Translating the document, this can take a minute.")
            out = tr.translate_file(str(p.get("path") or "").strip().strip('"'), target, source=source)
            return f"Translated document saved as: {out}"
        if action == "clipboard":
            import pyperclip
            text = pyperclip.paste() or ""
            result = tr.translate_text(text, target, source=source, tone=str(p.get("tone") or ""))
            if p.get("copy_result", True):
                pyperclip.copy(result)
            return f"Translation (also copied to the clipboard):\n{result}"
        result = tr.translate_text(str(p.get("text") or ""), target, source=source, tone=str(p.get("tone") or ""))
        return result
    except (ValueError, FileNotFoundError) as e:
        return f"Translate: {e}"
    except RuntimeError as e:
        return f"Translate: no AI provider could answer ({e})."
    except ImportError as e:
        return f"Translate: missing package ({e.name})."


TOOL = {
    "name": "translate",
    "description": (
        "Translate text, the clipboard, or a whole document (DOCX, PPTX, PDF, TXT/MD) into any language. "
        "Documents keep their layout where possible and are saved next to the original as '<name> (<language>)'. "
        "Use 'clipboard' when the owner says 'translate what I copied'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(_ACTIONS)},
            "text": {"type": "STRING", "description": "Text to translate (action=text)."},
            "path": {"type": "STRING", "description": "Document path (action=file)."},
            "target_language": {"type": "STRING", "description": "e.g. Sinhala, English, Japanese."},
            "source_language": {"type": "STRING", "description": "Optional; auto-detected when empty."},
            "tone": {"type": "STRING", "description": "Optional: formal, casual, ..."},
            "copy_result": {"type": "BOOLEAN", "description": "clipboard: copy the result back (default true)."},
            "limit": {"type": "INTEGER"},
        },
        "required": ["action"],
    },
    "handler": translate,
    "risk": "write",
    "timeout": 600,
}
