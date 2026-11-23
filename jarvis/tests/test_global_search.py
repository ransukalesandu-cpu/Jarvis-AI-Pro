"""Conversation archive + global search (P12 of the Cherry Studio parity plan)."""
from __future__ import annotations

import pytest

from jarvis import search as gs

@pytest.fixture(autouse=True)
def _reset_untrusted_flag():
    """wrap_untrusted() marks the turn as untrusted globally; do not leak that into other test files."""
    yield
    from jarvis.core import security
    security.mark_user_turn_started()



@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JARVIS_NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.delenv("JARVIS_CHAT_HISTORY", raising=False)
    monkeypatch.setattr(gs, "_archive", None)


def test_archive_records_only_safe_lines(tmp_path):
    state = {"ok": True}
    arc = gs.ConversationArchive(tmp_path / "h", available=lambda: state["ok"], clock=lambda: 1_763_800_000)
    (tmp_path / "h").mkdir()
    arc.on_line("You: what's the logo price for the client")
    arc.on_line("JARVIS: You quoted 50 dollars for the logo.")
    arc.on_line("SEC: Owner credential verified.")
    arc.on_line("You: /pin 1234")
    arc.on_line("SYS: tool ran")
    state["ok"] = False                                      # locked / guest: nothing recorded
    arc.on_line("You: secret plans")
    files = list((tmp_path / "h").glob("*.jsonl"))
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "secret plans" not in files[0].read_text() and "1234" not in files[0].read_text()
    hits = arc.search("logo price")
    assert hits and hits[0]["role"] == "owner"
    assert arc.search("") == []


def test_archive_disabled_and_prune(tmp_path, monkeypatch):
    (tmp_path / "h").mkdir()
    arc = gs.ConversationArchive(tmp_path / "h", available=lambda: True, clock=lambda: 1_763_800_000)
    monkeypatch.setenv("JARVIS_CHAT_HISTORY", "0")
    arc.on_line("You: hello")
    assert not list((tmp_path / "h").glob("*.jsonl"))
    monkeypatch.delenv("JARVIS_CHAT_HISTORY")
    (tmp_path / "h" / "2020-01-01.jsonl").write_text("{}\n")
    arc.on_line("You: hello")
    assert arc.prune(keep_days=30) == 1
    assert arc.clear() == 1


def test_search_all_across_sources(tmp_path, monkeypatch):
    from jarvis import library, notes
    from jarvis.knowledge import KnowledgeStore
    import jarvis.knowledge as kb

    arc = gs.ConversationArchive(tmp_path / "h", available=lambda: True)
    (tmp_path / "h").mkdir()
    monkeypatch.setattr(gs, "_archive", arc)
    arc.on_line("You: the hologram should be orange")
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    store.add_text("design", "brief", "Orange hologram with circuit traces.")
    monkeypatch.setattr(kb, "get_store", lambda: store)
    notes.create("Hologram", "orange eyes, no heart")
    f = tmp_path / "orange-hologram.png"
    f.write_bytes(b"x")
    library.register(f, "media")
    res = gs.search_all("orange hologram")
    assert res["conversations"] and res["knowledge"] and res["notes"] and res["files"]
    text = gs.format_results(res)
    assert "## conversations" in text and "## notes" in text
    only = gs.search_all("orange", sources={"notes"})
    assert set(only) == {"notes"}


def test_voice_tool(monkeypatch, tmp_path):
    from jarvis.actions import global_search as tool

    assert "What should I search for" in tool.global_search({"action": "search"})
    assert "Nothing found" in tool.global_search({"action": "search", "query": "zzzz-nothing", "sources": "notes"})
    from jarvis import notes
    notes.create("Invoice", "client paid 50 percent")
    out = tool.global_search({"action": "search", "query": "client paid", "sources": "notes"})
    assert "Invoice" in out and "Search results" in out
    assert "Deleted" in tool.global_search({"action": "clear_history"})


def test_tiers():
    from jarvis.core import security
    assert security.tier_for("global_search", {"action": "search"}) == security.TIER_SAFE
    assert security.tier_for("global_search", {"action": "clear_history"}) == security.TIER_DANGEROUS
