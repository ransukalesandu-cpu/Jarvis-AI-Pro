"""Voice tool: search everything JARVIS knows locally — past conversations, memory, knowledge, notes, files."""
from __future__ import annotations

from jarvis import search as gs
from jarvis.core import injection_guard

_SOURCES = ("conversations", "memory", "knowledge", "notes", "files")


def global_search(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "search").strip().lower()
    if action == "clear_history":
        n = gs.get_archive().clear()
        return f"Deleted {n} day(s) of conversation history."
    if action != "search":
        return "Unknown action. Use search or clear_history."
    query = str(p.get("query") or "").strip()
    if not query:
        return "What should I search for?"
    raw = p.get("sources") or ""
    chosen = {s.strip() for s in raw.split(",") if s.strip() in _SOURCES} if isinstance(raw, str) else set()
    results = gs.search_all(query, sources=chosen or None, limit=int(p.get("limit") or 5))
    text = gs.format_results(results)
    if not text:
        return "Nothing found in conversations, memory, knowledge bases, notes or files."
    return "Search results (owner's local data):\n" + injection_guard.wrap_untrusted(text, "global_search")


TOOL = {
    "name": "global_search",
    "description": (
        "Search ALL of the owner's local JARVIS data at once: past conversations, memory, knowledge bases, notes and "
        "the file library. Use for 'when did I talk about…', 'find where I mentioned…', 'search everything for…'. "
        "sources narrows it (comma-separated). clear_history deletes the stored conversation history."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": ["search", "clear_history"]},
            "query": {"type": "STRING"},
            "sources": {"type": "STRING", "description": "Optional: conversations,memory,knowledge,notes,files"},
            "limit": {"type": "INTEGER", "description": "Results per source (default 5)."},
        },
        "required": ["action"],
    },
    "handler": global_search,
    "risk": "read",
    "timeout": 60,
}
