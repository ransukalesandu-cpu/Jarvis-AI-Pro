"""Features Hub bridge (P13 of the Cherry Studio parity plan): read-only snapshots, gated like typing."""
from __future__ import annotations

import json

import pytest

from jarvis.webui import contract, features_feed


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JARVIS_NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("JARVIS_BACKUP_DIR", str(tmp_path / "backups"))


def test_every_feature_builds_a_valid_snapshot(monkeypatch, tmp_path):
    from jarvis import notes
    from jarvis.knowledge import KnowledgeStore
    import jarvis.knowledge as kb

    store = KnowledgeStore(tmp_path / "kb.sqlite")
    store.add_text("work", "brief", "hello")
    monkeypatch.setattr(kb, "get_store", lambda: store)
    notes.create("Ideas", "orb", "design")
    for f in features_feed.FEATURES:
        summary, items = features_feed.snapshot(f)
        assert contract.encode_event("feature.snapshot", feature=f, summary=summary, items=items), f
    assert features_feed.snapshot("knowledge")[1][0]["title"] == "work"
    assert features_feed.snapshot("notes")[1][0]["title"] == "Ideas"


def test_snapshot_is_redacted_bounded_and_fail_soft(monkeypatch):
    monkeypatch.setitem(features_feed._BUILDERS, "notes", lambda: ("x" * 500, [{"title": "t" * 500, "detail": "sk-ant-" + "a" * 40}] * 50))
    summary, items = features_feed.snapshot("notes")
    assert len(summary) <= 200 and len(items) == 30
    assert all(len(i["title"]) <= 120 and "sk-ant-aaaa" not in i["detail"] for i in items)
    monkeypatch.setitem(features_feed._BUILDERS, "notes", lambda: 1 / 0)
    assert features_feed.snapshot("notes") == ("Unavailable (ZeroDivisionError)", [])
    assert features_feed.snapshot("shell") == ("Unknown feature", [])


def test_contract_shapes():
    assert contract.parse_request('{"kind":"feature.refresh","feature":"backup"}') == {"kind": "feature.refresh", "feature": "backup"}
    assert contract.parse_request('{"kind":"feature.refresh","feature":"run_command"}') is None
    assert contract.parse_request('{"kind":"feature.refresh","feature":"backup","path":"x"}') is None
    assert contract.encode_event("feature.snapshot", feature="notes", summary="", items=[]) is None
    assert contract.encode_event("feature.snapshot", feature="notes", summary="s", items=[{"title": "a"}]) is None


class _Gate:
    def __init__(self, state="ok"):
        self.state = state

    def availability(self):
        return self.state


def test_bridge_publishes_only_while_available():
    pytest.importorskip("PyQt6.QtCore")
    from jarvis.webui.bridge import WebUIBridge

    gate = _Gate()
    b = WebUIBridge(gate=gate, features=lambda f: (f"{f} ok", [{"title": "item", "detail": "d"}]))
    got = []
    b.event.connect(lambda s: got.append(json.loads(s)))
    b.request(json.dumps({"kind": "feature.refresh", "feature": "notes"}))
    assert got[-1] == {"type": "feature.snapshot", "feature": "notes", "summary": "notes ok", "items": [{"title": "item", "detail": "d"}]}
    gate.state = "guest"
    b.request(json.dumps({"kind": "feature.refresh", "feature": "notes"}))
    assert got[-1] == {"type": "feature.snapshot", "feature": "notes", "summary": "Hidden in Guest Mode", "items": []}
    b2 = WebUIBridge()
    got2 = []
    b2.event.connect(lambda s: got2.append(json.loads(s)))
    b2.request(json.dumps({"kind": "feature.refresh", "feature": "apps"}))
    assert got2[-1]["items"] == [] and got2[-1]["summary"] == "Not available right now"


def test_window_kind_is_accepted_in_saved_layouts():
    from jarvis.webui.workspace_store import WINDOW_KINDS
    assert "features" in WINDOW_KINDS
