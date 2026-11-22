"""Voice tool: explain / summarize / translate / fix the text the owner selected or copied."""
from __future__ import annotations

from jarvis import quick

_SOURCES = ("selection", "clipboard", "text")


def quick_action(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "explain").strip().lower()
    source = str(p.get("source") or "selection").strip().lower()
    if action not in quick.ACTIONS:
        return f"Unknown quick action '{action}'. Use one of: {', '.join(quick.ACTIONS)}."
    if source not in _SOURCES:
        return f"Unknown source '{source}'. Use selection, clipboard or text."
    try:
        if source == "text":
            text = str(p.get("text") or "")
        elif source == "clipboard":
            text = quick.Clipboard().paste()
        else:
            text = quick.read_selection()
        result = quick.run_action(action, text, language=str(p.get("language") or ""),
                                  question=str(p.get("question") or ""))
    except ValueError as e:
        return f"Quick Assistant: {e}."
    except RuntimeError as e:
        return f"Quick Assistant: no AI provider could answer ({e})."
    except ImportError as e:
        return f"Quick Assistant: missing package ({e.name})."
    if p.get("replace") and action in quick.REPLACEABLE and source == "selection":
        try:
            quick.replace_selection(result)
            return f"Replaced the selection with:\n{result}"
        except Exception as e:
            return f"Result (could not paste it back: {type(e).__name__}):\n{result}"
    if p.get("copy_result"):
        try:
            quick.Clipboard().copy(result)
        except Exception:
            return result
        return f"Copied to the clipboard:\n{result}"
    return result


TOOL = {
    "name": "quick_action",
    "description": (
        "Quick Assistant for text in any app: explain, summarize, translate, fix_grammar, simplify, professional, "
        "reply or ask about the SELECTED text (source=selection), the clipboard, or given text. replace=true pastes "
        "the result over the selection (e.g. 'fix the grammar of what I selected and replace it')."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(quick.ACTIONS)},
            "source": {"type": "STRING", "enum": list(_SOURCES)},
            "text": {"type": "STRING", "description": "The text when source=text."},
            "language": {"type": "STRING", "description": "Target language for translate."},
            "question": {"type": "STRING", "description": "The question for action=ask."},
            "replace": {"type": "BOOLEAN", "description": "Paste the result over the selection."},
            "copy_result": {"type": "BOOLEAN", "description": "Copy the result to the clipboard."},
        },
        "required": ["action"],
    },
    "handler": quick_action,
    "risk": "write",
    "timeout": 120,
}
