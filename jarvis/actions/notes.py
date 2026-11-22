"""Voice tool for Markdown notes: 'note that the client wants blue', 'read my logo note'."""
from __future__ import annotations

from jarvis import notes as nt

_ACTIONS = ("create", "append", "read", "search", "list", "delete", "set_folder", "folder", "to_knowledge")


def notes(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "").strip().lower()
    title = str(p.get("title") or "").strip()
    text = str(p.get("text") or "").strip()
    if action not in _ACTIONS:
        return f"Unknown notes action '{action}'. Use one of: {', '.join(_ACTIONS)}."
    try:
        if action == "create":
            if not title and not text:
                return "What should the note say?"
            path = nt.create(title or text[:40], text, p.get("tags"))
            return f"Note saved: {path.stem}"
        if action == "append":
            if not text:
                return "What should I add?"
            path = nt.append(title or "Inbox", text)
            return f"Added to note '{path.stem}'."
        if action == "read":
            n = nt.read(title)
            body = n.body.strip()
            more = "\n…(truncated)" if len(body) > 4000 else ""
            return f"{n.title}{' [' + ', '.join(n.tags) + ']' if n.tags else ''}\n{body[:4000]}{more}"
        if action == "search":
            hits = nt.search(str(p.get("query") or text or title), tag=str(p.get("tag") or ""))
            if not hits:
                return "No matching notes."
            return "Notes:\n" + "\n".join(f"- {n.title}: {s}" for n, s in hits)
        if action == "list":
            items = nt.all_notes()
            tag = str(p.get("tag") or "").strip().lower()
            if tag:
                items = [n for n in items if tag in n.tags]
            if not items:
                return "No notes yet."
            return f"{len(items)} notes (newest first):\n" + "\n".join(f"- {n.title}" for n in items[:30])
        if action == "delete":
            nt.delete(title)
            return f"Moved '{title}' to the notes trash."
        if action == "set_folder":
            folder = nt.set_notes_dir(str(p.get("folder") or text))
            return f"Notes folder is now {folder}."
        if action == "folder":
            return f"Notes are saved in {nt.notes_dir()}."
        n = nt.read(title)
        from jarvis.knowledge import get_store
        base = str(p.get("base") or "").strip() or get_store().get_active() or "notes"
        res = get_store().add_path(base, str(n.path))
        return f"Note '{n.title}' added to knowledge base '{base}' ({res.summary()})."
    except FileNotFoundError as e:
        return f"Notes: {e.args[0] if e.args else e}"
    except (OSError, ValueError) as e:
        return f"Notes: {e}"


TOOL = {
    "name": "notes",
    "description": (
        "The owner's Markdown notes (plain .md files, can be an Obsidian vault). create / append (quick capture, "
        "default note 'Inbox') / read / search / list / delete (to trash) / set_folder / folder / to_knowledge "
        "(index a note into a knowledge base). Use for 'note that…', 'add to my shopping note', 'what did I note "
        "about…'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(_ACTIONS)},
            "title": {"type": "STRING", "description": "Note title."},
            "text": {"type": "STRING", "description": "Note content / text to add."},
            "tags": {"type": "STRING", "description": "Comma-separated tags (create)."},
            "tag": {"type": "STRING", "description": "Filter by tag (list/search)."},
            "query": {"type": "STRING", "description": "Search words."},
            "folder": {"type": "STRING", "description": "Folder path (set_folder)."},
            "base": {"type": "STRING", "description": "Knowledge base name (to_knowledge)."},
        },
        "required": ["action"],
    },
    "handler": notes,
    "risk": "write",
    "timeout": 60,
}
