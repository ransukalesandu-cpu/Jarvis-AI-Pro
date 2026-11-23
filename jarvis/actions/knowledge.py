"""Voice tool for the knowledge base: add files, folders and web pages, then ask about them.

"add my Downloads/contract.pdf to my work knowledge" -> add
"what does my contract say about payment?"          -> ask (answers with [n] citations)
"""
from __future__ import annotations

from jarvis.core import injection_guard
from jarvis.knowledge import format_hits, get_store

_ACTIONS = ("create", "list", "sources", "add", "add_text", "ask", "search", "use",
            "refresh", "remove_source", "delete_base", "stats")


def _base(params: dict, store) -> str:
    name = str(params.get("base") or "").strip()
    return name or store.get_active() or "default"


def knowledge(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "").strip().lower()
    if action not in _ACTIONS:
        return f"Unknown knowledge action '{action}'. Use one of: {', '.join(_ACTIONS)}."
    store = get_store()
    try:
        if action == "create":
            name = store.create_base(p.get("base") or "", p.get("description") or "")
            return f"Knowledge base '{name}' created."
        if action == "list":
            bases = store.list_bases()
            if not bases:
                return "No knowledge bases yet. Say 'add <file or folder> to my <name> knowledge' to start one."
            active = store.get_active()
            lines = [f"- {b['name']}{' (active)' if b['name'] == active else ''}: {b['sources']} sources, "
                     f"{b['chunks']} chunks{(' — ' + b['description']) if b['description'] else ''}" for b in bases]
            return "Knowledge bases:\n" + "\n".join(lines)
        if action == "sources":
            name = _base(p, store)
            rows = store.list_sources(name)
            if not rows:
                return f"'{name}' has no sources yet."
            lines = [f"- #{r['id']} {r['kind']}: {r['title']} ({r['chunks']} chunks"
                     f"{', FAILED: ' + r['error'] if r['status'] != 'ok' else ''})" for r in rows[:40]]
            more = f"\n…and {len(rows) - 40} more" if len(rows) > 40 else ""
            return f"Sources in '{name}':\n" + "\n".join(lines) + more
        if action == "add":
            target = str(p.get("target") or "").strip()
            if not target:
                return "Tell me which file, folder or web page to add."
            name = _base(p, store)
            if speak:
                speak(f"Indexing that into {name}.")
            if target.lower().startswith(("http://", "https://")):
                res = store.add_url(name, target)
            else:
                res = store.add_path(name, target)
            failed = f" Could not read: {', '.join(res.failed[:5])}." if res.failed else ""
            return f"Knowledge base '{name}': {res.summary()}.{failed}"
        if action == "add_text":
            text = str(p.get("text") or "").strip()
            if not text:
                return "There is no text to add."
            name = _base(p, store)
            res = store.add_text(name, str(p.get("title") or "note"), text)
            return f"Saved to '{name}': {res.summary()}."
        if action in ("ask", "search"):
            query = str(p.get("query") or "").strip()
            if not query:
                return "What should I look up in the knowledge base?"
            base = str(p.get("base") or "").strip() or store.get_active()
            hits = store.search(query, base=base, limit=int(p.get("limit") or 6))
            if not hits:
                where = f"'{base}'" if base else "any knowledge base"
                return f"Nothing in {where} matches that."
            if action == "search":
                return "Matches:\n" + "\n".join(f"[{i}] {h.title} — {h.text[:160].strip()}…"
                                                 for i, h in enumerate(hits, 1))
            context = injection_guard.wrap_untrusted(format_hits(hits), "knowledge_base")
            return ("Answer the owner's question using ONLY these knowledge-base excerpts. Cite them as [1], [2]. "
                    "If they do not contain the answer, say so.\n\nQuestion: " + query + "\n\n" + context)
        if action == "use":
            name = store.set_active(str(p.get("base") or "").strip())
            return f"Active knowledge base: {name}." if name else "No knowledge base is active now."
        if action == "refresh":
            name = _base(p, store)
            return f"Refreshed '{name}': {store.refresh(name).summary()}."
        if action == "remove_source":
            name = _base(p, store)
            n = store.remove_source(name, str(p.get("target") or ""))
            return f"Removed {n} source(s) from '{name}'." if n else "No matching source found."
        if action == "delete_base":
            name = str(p.get("base") or "").strip()
            if not name:
                return "Which knowledge base should I delete?"
            store.delete_base(name)
            if store.get_active() == name:
                store.set_active("")
            return f"Knowledge base '{name}' deleted."
        s = store.stats()
        return f"{s['bases']} knowledge bases, {s['sources']} sources, {s['chunks']} chunks, {s['vectors']} embedded."
    except (ValueError, KeyError, FileNotFoundError) as e:
        return f"Knowledge base: {e.args[0] if e.args else e}"
    except OSError as e:
        return f"Knowledge base: could not read that ({e})."


TOOL = {
    "name": "knowledge",
    "description": (
        "Owner's local knowledge bases (documents, folders, web pages). Use 'ask' whenever the owner asks about "
        "their own documents, notes, contracts, course material or anything they added before; answer from the "
        "returned excerpts and cite [n]. 'add' indexes a file path, folder path or URL into a base; 'add_text' "
        "saves dictated text; 'use' sets the active base; 'list', 'sources', 'refresh', 'remove_source', "
        "'delete_base', 'create', 'search', 'stats'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(_ACTIONS)},
            "base": {"type": "STRING", "description": "Knowledge base name, e.g. 'work'. Empty = active base."},
            "target": {"type": "STRING", "description": "File path, folder path or http(s) URL (add / remove_source)."},
            "query": {"type": "STRING", "description": "Question or keywords (ask / search)."},
            "text": {"type": "STRING", "description": "Text to save (add_text)."},
            "title": {"type": "STRING", "description": "Title for add_text."},
            "description": {"type": "STRING", "description": "Description for create."},
            "limit": {"type": "INTEGER", "description": "Max excerpts, 1-20."},
        },
        "required": ["action"],
    },
    "handler": knowledge,
    "risk": "write",
    "timeout": 600,
}
