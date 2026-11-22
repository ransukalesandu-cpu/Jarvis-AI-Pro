"""Markdown notes (P6 of the Cherry Studio parity plan)."""
from __future__ import annotations

import pytest

from jarvis import notes as nt


@pytest.fixture()
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JARVIS_NOTES_DIR", str(tmp_path / "vault"))
    return tmp_path / "vault"


def test_create_read_append_with_tags(folder):
    p = nt.create("Logo feedback", "The client wants blue.", "Client, logo")
    assert p.parent == folder and p.name == "Logo feedback.md"
    n = nt.read("logo")
    assert n.tags == ["client", "logo"] and "wants blue" in n.body and n.body.startswith("# Logo feedback")
    nt.append("Logo feedback", "Also a darker shade.")
    assert "darker shade" in nt.read("Logo feedback").body
    assert nt.create("Logo feedback").name == "Logo feedback 2.md"


def test_append_creates_inbox_and_slug_is_safe(folder):
    nt.append("Inbox", "buy milk")
    assert (folder / "Inbox.md").exists()
    p = nt.create('a/b:c*?"<>|', "x")
    assert p.name == "abc.md"
    with pytest.raises(FileNotFoundError):
        nt.append("missing", "x", create_missing=False)


def test_search_list_delete(folder):
    nt.create("Groceries", "milk eggs bread", "home")
    nt.create("Work", "send invoice to client", "work")
    hits = nt.search("invoice")
    assert [n.title for n, _ in hits] == ["Work"] and "invoice" in hits[0][1]
    assert [n.title for n, _ in nt.search("", tag="home")] == ["Groceries"]
    assert len(nt.all_notes()) == 2
    dest = nt.delete("Groceries")
    assert dest.parent.name == ".trash" and len(nt.all_notes()) == 1
    with pytest.raises(FileNotFoundError):
        nt.read("Groceries")


def test_set_folder_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("JARVIS_NOTES_DIR", raising=False)
    target = nt.set_notes_dir(str(tmp_path / "obsidian"))
    assert nt.notes_dir() == target


def test_voice_tool_and_knowledge_link(folder, monkeypatch, tmp_path):
    from jarvis.actions import notes as tool
    from jarvis.knowledge import KnowledgeStore
    import jarvis.knowledge as kb

    assert tool.notes({"action": "create", "title": "Ideas", "text": "glass orb HUD"}) == "Note saved: Ideas"
    assert "Added to note 'Inbox'" in tool.notes({"action": "append", "text": "call mom"})
    assert "glass orb" in tool.notes({"action": "read", "title": "ideas"})
    assert "Ideas" in tool.notes({"action": "list"})
    assert "Ideas" in tool.notes({"action": "search", "query": "orb"})
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    monkeypatch.setattr(kb, "get_store", lambda: store)
    assert "1 added" in tool.notes({"action": "to_knowledge", "title": "Ideas", "base": "ideas"})
    assert store.search("orb")[0].title == "Ideas.md"
    assert "no note called" in tool.notes({"action": "read", "title": "nothing here"})
    assert "Unknown notes action" in tool.notes({"action": "burn"})


def test_tiers():
    from jarvis.core import security
    assert security.tier_for("notes", {"action": "read"}) == security.TIER_SAFE
    assert security.tier_for("notes", {"action": "create"}) == security.TIER_SENSITIVE
    assert security.tier_for("notes", {"action": "set_folder"}) == security.TIER_DANGEROUS
