"""Knowledge base (P1 of the Cherry Studio parity plan)."""
from __future__ import annotations

import os
import time

import pytest

from jarvis.knowledge import KnowledgeStore, format_hits
from jarvis.knowledge import extract
from jarvis.knowledge import store as kb_store

@pytest.fixture(autouse=True)
def _reset_untrusted_flag():
    """wrap_untrusted() marks the turn as untrusted globally; do not leak that into other test files."""
    yield
    from jarvis.core import security
    security.mark_user_turn_started()



@pytest.fixture()
def store(tmp_path):
    return KnowledgeStore(tmp_path / "kb.sqlite")


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_chunking_respects_size_and_overlap():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(20))
    chunks = extract.chunk_text(text, size=400, overlap=80)
    assert len(chunks) > 5
    assert all(len(c) <= 400 for c in chunks)
    assert extract.chunk_text("") == []
    huge = extract.chunk_text("x" * 5000, size=900, overlap=150)
    assert all(len(c) <= 900 for c in huge) and len(huge) >= 6


def test_html_to_text_drops_scripts_and_reads_title():
    title, text = extract.html_to_text(
        "<html><head><title>Pricing</title><script>evil()</script></head>"
        "<body><h1>Plans</h1><p>Pro costs 20 dollars.</p><style>.a{}</style></body></html>")
    assert title == "Pricing"
    assert "Pro costs 20 dollars." in text and "evil" not in text


def test_add_file_and_search_with_citation(store, tmp_path):
    f = _write(tmp_path / "docs" / "contract.md",
               "Payment terms: the client pays 50 percent upfront and the rest on delivery.\n\n"
               "Revisions: two rounds of revisions are included.")
    res = store.add_path("work", str(f))
    assert res.added == 1 and not res.failed
    hits = store.search("when does the client pay", base="work")
    assert hits and "upfront" in hits[0].text
    block = format_hits(hits)
    assert block.startswith("[1] contract.md (work:")


def test_folder_add_refresh_and_remove(store, tmp_path):
    folder = tmp_path / "notes"
    a = _write(folder / "a.txt", "Apples are red fruit.")
    _write(folder / "b.md", "Bananas are yellow fruit.")
    _write(folder / "node_modules" / "skip.txt", "should not be indexed bananas")
    _write(folder / "image.bin", "binary")
    res = store.add_path("fruit", str(folder))
    assert res.added == 2
    assert [b["name"] for b in store.list_bases()] == ["fruit"]
    assert all("skip.txt" not in s["location"] for s in store.list_sources("fruit"))

    # unchanged files are skipped, edited files re-indexed, new files picked up, deleted files dropped
    time.sleep(0.01)
    a.write_text("Apples can be green too.", encoding="utf-8")
    os.utime(a, (time.time() + 5, time.time() + 5))
    _write(folder / "c.txt", "Cherries are small.")
    (folder / "b.md").unlink()
    res = store.refresh("fruit")
    assert res.updated == 1 and res.added == 1
    assert store.search("green apples", base="fruit")[0].text == "Apples can be green too."
    assert not store.search("bananas", base="fruit")

    removed = store.remove_source("fruit", str(folder.resolve()))
    assert removed >= 3
    assert store.stats()["chunks"] == 0


def test_add_url_uses_fetcher_and_text(tmp_path):
    s = KnowledgeStore(tmp_path / "kb.sqlite", fetcher=lambda url: ("Docs page", "Gemini Live streams audio both ways."))
    assert s.add_url("research", "https://example.com/docs").added == 1
    assert s.add_text("research", "idea", "Use a glass orb for the HUD.").added == 1
    assert s.search("audio streams")[0].title == "Docs page"
    assert s.add_url("research", "https://example.com/docs").unchanged == 1


def test_embeddings_blend_and_fail_soft(tmp_path):
    def embed(texts):
        return [[1.0, 0.0] if "invoice" in t.lower() or "bill" in t.lower() else [0.0, 1.0] for t in texts]

    s = KnowledgeStore(tmp_path / "kb.sqlite", embedder=embed)
    s.add_text("work", "billing", "Send the invoice on the first Monday of the month.")
    s.add_text("work", "design", "The logo uses deep blue.")
    assert s.stats()["vectors"] == 2
    hits = s.search("bill", base="work")              # no keyword overlap: the vector finds it
    assert hits and hits[0].title == "billing"

    def broken(texts):
        raise RuntimeError("offline")

    s2 = KnowledgeStore(tmp_path / "kb2.sqlite", embedder=broken)
    s2.add_text("work", "design", "The logo uses deep blue.")
    assert s2.search("logo")[0].title == "design"


def test_names_active_base_and_delete(store):
    with pytest.raises(ValueError):
        store.create_base("../etc")
    store.create_base("Work Stuff")
    with pytest.raises(ValueError):
        store.create_base("work stuff")
    assert store.set_active("work stuff") == "work stuff"
    assert store.get_active() == "work stuff"
    store.add_text("work stuff", "t", "hello world")
    store.delete_base("work stuff")
    assert store.list_bases() == [] and store.stats()["chunks"] == 0
    with pytest.raises(KeyError):
        store.search("hello", base="work stuff")


def test_embeddings_off_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_KB_EMBEDDINGS", raising=False)
    assert kb_store.embeddings_enabled() is False
    assert KnowledgeStore(tmp_path / "kb.sqlite")._embedder_or_none() is None


def test_voice_tool_flow(monkeypatch, tmp_path):
    from jarvis.actions import knowledge as tool

    s = KnowledgeStore(tmp_path / "kb.sqlite")
    monkeypatch.setattr(tool, "get_store", lambda: s)
    f = _write(tmp_path / "plan.txt", "The JARVIS demo is on Friday at 5 pm.")
    assert "1 added" in tool.knowledge({"action": "add", "base": "work", "target": str(f)})
    assert "Active knowledge base: work" in tool.knowledge({"action": "use", "base": "work"})
    answer = tool.knowledge({"action": "ask", "query": "when is the demo"})
    assert "[1]" in answer and "Friday" in answer and "Cite" in answer
    assert "work (active)" in tool.knowledge({"action": "list"})
    assert "Unknown knowledge action" in tool.knowledge({"action": "explode"})
    assert "not found" in tool.knowledge({"action": "add", "base": "work", "target": str(tmp_path / "nope.pdf")})
    assert tool.TOOL["name"] == "knowledge"


def test_security_tiers_for_knowledge():
    from jarvis.core import security

    assert security.tier_for("knowledge", {"action": "ask"}) == security.TIER_SAFE
    assert security.tier_for("knowledge", {"action": "add"}) == security.TIER_SENSITIVE
    assert security.tier_for("knowledge", {"action": "delete_base"}) == security.TIER_DANGEROUS
