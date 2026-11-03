"""
Ask Claude — hand a hard task to Claude (Anthropic API) and speak the answer.

Gemini Live stays the voice; this tool is the "brain" it calls for work that
needs deep reasoning: code, debugging, plans, long writing, multi-step analysis.
Gemini reads the returned text aloud, so the answer comes back short and
speakable; when Claude's full answer is long, it is saved as a Markdown file in
the owner's Documents folder (the same place file_controller writes) and the
spoken answer says where.

The tool is hidden from Gemini until an Anthropic API key is configured
(AI PROVIDER / KEYS). The Anthropic API is pay-per-use, separate from a Claude
Pro subscription; every call is counted and logged by core/claude_usage.py.
Errors come back as one honest sentence and never raise into the Live session.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from core.provider_settings import claude_model, get_provider_api_key

QUICK, DEEP = "quick", "deep"
# Long enough for real work, bounded so a runaway answer cannot run up a bill.
_MAX_TOKENS = {QUICK: 2048, DEEP: 12000}
_TIMEOUT_S = {QUICK: 45.0, DEEP: 110.0}
_EFFORT = {QUICK: "low", DEEP: "high"}
# A spoken answer longer than this is cut and the full text saved to a file.
_SPOKEN_LIMIT = 700

_SYSTEM = (
    "You are the reasoning engine behind JARVIS, a voice assistant. Your answer is "
    "read aloud by another model, so structure it in two parts:\n"
    "SPOKEN: two to four plain sentences a person can listen to: the answer or the "
    "key result, no Markdown, no code, no lists.\n"
    "DETAILS: the complete answer (code, steps, full text) in Markdown. Leave this "
    "part empty when the spoken part already says everything.\n"
    "Be correct and direct. If you are not sure, say so."
)


def _available() -> bool:
    return bool(get_provider_api_key("anthropic"))


def _client(timeout: float):
    import anthropic
    return anthropic.Anthropic(api_key=get_provider_api_key("anthropic"),
                               timeout=timeout, max_retries=1)


def _split(text: str) -> tuple[str, str]:
    """(spoken, details) from Claude's two-part answer; tolerant of drift."""
    text = (text or "").strip()
    m = re.search(r"SPOKEN:\s*(.*?)(?:\n\s*DETAILS:\s*(.*))?\Z", text, flags=re.S | re.I)
    if not m:
        return text, ""
    spoken = m.group(1).strip()
    details = (m.group(2) or "").strip()
    return spoken, details


def _documents_dir() -> Path:
    try:
        from actions.file_controller import _get_documents
        return _get_documents()
    except Exception:
        return Path.home() / "Documents"


def _save_full_answer(task: str, text: str) -> str:
    """Save the long answer; returns the path, or "" if it could not be saved."""
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower()).strip("-")[:40] or "answer"
    path = _documents_dir() / "JARVIS" / "Claude" / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.md"
    try:
        from core import path_guard
        path_guard.check(path, write=True)
    except PermissionError:
        return ""
    except Exception as exc:       # the guard could not decide: do not write
        print(f"[ask_claude] path guard failed ({type(exc).__name__}); not saving.")
        return ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {task.strip()[:200]}\n\n{text.strip()}\n", encoding="utf-8")
        return str(path)
    except OSError:
        return ""


def _text_of(response) -> str:
    return "".join(getattr(b, "text", "") for b in getattr(response, "content", []) or []
                   if getattr(b, "type", "") == "text").strip()


def ask_claude(parameters: dict, client_factory=None) -> str:
    task = str((parameters or {}).get("task") or "").strip()
    depth = str((parameters or {}).get("depth") or QUICK).strip().lower()
    depth = depth if depth in (QUICK, DEEP) else QUICK
    if not task:
        return "Tell me what you'd like Claude to work on, sir."
    if not _available():
        return "Claude isn't set up yet, sir. Add an Anthropic API key in AI provider keys."

    model = claude_model("fast" if depth == QUICK else "strong")
    request = {
        "model": model,
        "max_tokens": _MAX_TOKENS[depth],
        "system": _SYSTEM,
        "output_config": {"effort": _EFFORT[depth]},
        "messages": [{"role": "user", "content": task[:20000]}],
    }
    try:
        import anthropic
        client = (client_factory or _client)(_TIMEOUT_S[depth])
        if depth == DEEP:
            # On a policy decline the API re-runs the request on a fallback
            # model inside the same call, rather than returning nothing.
            response = client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request)
        else:
            response = client.messages.create(**request)
    except anthropic.AuthenticationError:
        return "Claude rejected the API key, sir. Please check it in AI provider keys."
    except anthropic.RateLimitError:
        return "Claude is rate-limited right now, sir. Try again in a minute."
    except (anthropic.APITimeoutError, anthropic.APIConnectionError):
        return "I couldn't reach Claude just now, sir. Check the connection and try again."
    except Exception as exc:     # never raise into the Live session
        print(f"[ask_claude] request failed: {type(exc).__name__}")
        return "Claude is unavailable right now, sir."

    from core.claude_usage import record_call
    record_call(getattr(response, "model", None) or model, getattr(response, "usage", None),
                source=f"ask_claude/{depth}")

    stop = getattr(response, "stop_reason", "")
    if stop == "refusal":
        return "Claude declined that request, sir."
    spoken, details = _split(_text_of(response))
    if not spoken and not details:
        return "Claude returned an empty answer, sir."
    full = details or spoken
    note = ""
    if details or len(spoken) > _SPOKEN_LIMIT or stop == "max_tokens":
        saved = _save_full_answer(task, f"{spoken}\n\n{details}".strip())
        if saved:
            note = f" The full answer is saved in {saved}."
        elif details:
            note = " I couldn't save the full answer to a file."
    if len(spoken) > _SPOKEN_LIMIT:
        spoken = spoken[:_SPOKEN_LIMIT].rsplit(" ", 1)[0] + "…"
    if stop == "max_tokens":
        note += " The answer was cut off at the length limit."
    return (spoken or full[:_SPOKEN_LIMIT]) + note


TOOL = {
    "name": "ask_claude",
    "description": (
        "Hands a hard task to Claude, a stronger reasoning model, and returns a short "
        "answer to read aloud (long results are saved to a file). Use it for coding and "
        "debugging, complex planning, long reasoning, drafting long text (emails, "
        "documents, essays), and multi-step analysis. Do NOT use it for simple commands "
        "(opening apps, the time, settings), small talk, or anything that needs the live "
        "camera or screen; answer those yourself or use the matching tool. Use depth "
        "'deep' for hard or long tasks and 'quick' otherwise."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "task": {"type": "STRING",
                     "description": "The full task for Claude, with all the context it needs."},
            "depth": {"type": "STRING", "enum": [QUICK, DEEP],
                      "description": "quick = fast model; deep = strongest model for hard work. "
                                     "Default quick."},
        },
        "required": ["task"],
    },
    "handler": ask_claude,
    "risk": "read",
    "timeout": 120,
    "available": _available,
}
