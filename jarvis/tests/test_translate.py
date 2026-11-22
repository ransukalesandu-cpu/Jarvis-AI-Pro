"""Translation (P4 of the Cherry Studio parity plan). The LLM is faked."""
from __future__ import annotations

import re

import pytest

from jarvis import translate as tr


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))


def fake_upper(prompt: str, system: str) -> str:
    """'Translate' by upper-casing the text after the instruction line, keeping markers."""
    body = prompt.split("\n\n", 1)[1]
    body = body.split("\n\nEach segment starts", 1)[0]
    return body.upper()


def test_translate_text_and_history():
    calls = []

    def ask(prompt, system):
        calls.append(prompt)
        return fake_upper(prompt, system)

    out = tr.translate_text("hello world", "Sinhala", ask=ask)
    assert out == "HELLO WORLD"
    assert "Sinhala script" in calls[0]
    assert tr.history(1)[0]["to"] == "Sinhala"
    with pytest.raises(ValueError):
        tr.translate_text("   ", "English", ask=ask)
    with pytest.raises(ValueError):
        tr.translate_text("hi", "", ask=ask)


def test_long_text_is_chunked():
    text = "\n\n".join("para %d " % i + "x" * 900 for i in range(10))
    seen = []
    tr.translate_text(text, "French", ask=lambda p, s: seen.append(p) or "ok")
    assert len(seen) >= 3


def test_segments_batch_and_fallback():
    segs = ["one", "", "two", "three"]
    assert tr.translate_segments(segs, "X", ask=fake_upper) == ["ONE", "", "TWO", "THREE"]

    calls = []

    def broken(prompt, system):
        calls.append(prompt)
        return "no markers here" if "⟦" in prompt else fake_upper(prompt, system)

    assert tr.translate_segments(["a", "b"], "X", ask=broken) == ["A", "B"]
    assert len(calls) == 3                                     # one batch + one per segment


def test_translate_docx_keeps_structure(tmp_path):
    from docx import Document
    src = tmp_path / "letter.docx"
    d = Document()
    d.add_paragraph("Dear client")
    d.add_paragraph("")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "price"
    t.cell(0, 1).text = "100"
    d.save(str(src))
    out = tr.translate_file(src, "German", ask=fake_upper)
    assert out.name == "letter (German).docx"
    doc = Document(str(out))
    assert [p.text for p in doc.paragraphs][:2] == ["DEAR CLIENT", ""]
    assert doc.tables[0].cell(0, 0).text == "PRICE"
    assert tr.translate_file(src, "German", ask=fake_upper).name == "letter (German 2).docx"


def test_translate_text_file_and_errors(tmp_path):
    src = tmp_path / "notes.md"
    src.write_text("# Title\n\nbody text", encoding="utf-8")
    out = tr.translate_file(src, "Tamil", ask=fake_upper)
    assert out.suffix == ".md" and out.read_text(encoding="utf-8") == "# TITLE\n\nBODY TEXT"
    with pytest.raises(FileNotFoundError):
        tr.translate_file(tmp_path / "missing.docx", "Tamil", ask=fake_upper)
    bad = tmp_path / "x.exe"
    bad.write_bytes(b"MZ")
    with pytest.raises(ValueError):
        tr.translate_file(bad, "Tamil", ask=fake_upper)


def test_voice_tool(monkeypatch):
    from jarvis.actions import translate as tool
    from jarvis.core import text_brain

    monkeypatch.setattr(text_brain, "_override", lambda prompt, system, provider: {"text": re.sub(r"(?s).*\n\n", "", prompt).upper()})
    assert tool.translate({"action": "text", "text": "good morning", "target_language": "Sinhala"}) == "GOOD MORNING"
    assert "Unknown translate action" in tool.translate({"action": "dance"})
    assert "file not found" in tool.translate({"action": "file", "path": "/nope.docx", "target_language": "x"})
    assert "Recent translations" in tool.translate({"action": "history"})


def test_tiers():
    from jarvis.core import security
    assert security.tier_for("translate", {"action": "text"}) == security.TIER_SAFE
    assert security.tier_for("translate", {"action": "file"}) == security.TIER_SENSITIVE
