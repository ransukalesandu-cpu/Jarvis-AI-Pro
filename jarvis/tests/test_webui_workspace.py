"""Workspace persistence + the bridge/contract messages that carry it."""
from __future__ import annotations

import json

import pytest

from jarvis.webui import contract
from jarvis.webui.workspace_store import LAST, MAX_WORKSPACES, WorkspaceStore, clean_name, validate_layout


def _win(i=0, **o):
    w = {"id": f"w{i}", "kind": "monitor", "x": 20, "y": 80, "w": 320, "h": 300, "z": 1, "state": "normal"}
    w.update(o)
    return w


def _layout(*wins, page="home"):
    return {"windows": list(wins), "page": page}


def test_names():
    assert clean_name("Work 1") == "work 1"  # normalised to lower case
    assert clean_name("work-1") == "work-1"
    assert clean_name("../x") is None and clean_name("") is None and clean_name("a" * 40) is None
    assert clean_name(LAST) is None and clean_name(LAST, allow_internal=True) == LAST


@pytest.mark.parametrize("bad", [
    None, [], "x", {"windows": [], "page": "home", "x": 1}, {"windows": [], "page": "nope"},
    _layout(_win(kind="evil")), _layout(_win(state="gone")), _layout(_win(w=1e9)),
    _layout(_win(x=float("nan"))), _layout(_win(0), _win(0)), _layout(*[_win(i) for i in range(13)]),
    _layout(_win(extra=1)), _layout(_win(w=True)),
])
def test_invalid_layouts(bad):
    assert validate_layout(bad) is None


def test_valid_layout_roundtrip(tmp_path):
    store = WorkspaceStore(tmp_path / "ws.json")
    lay = _layout(_win(0), _win(1, kind="models", x=900))
    assert store.save("focus", lay)
    assert store.names() == ["focus"]
    assert store.load("focus") == validate_layout(lay)
    assert store.delete("focus") and store.names() == []


def test_last_is_hidden_and_corrupt_file_is_safe(tmp_path):
    p = tmp_path / "ws.json"
    store = WorkspaceStore(p)
    assert store.save(LAST, _layout(_win()))
    assert LAST not in store.names()
    assert store.load(LAST) is not None
    p.write_text("{not json", "utf-8")
    assert WorkspaceStore(p).names() == [] and WorkspaceStore(p).load("focus") is None


def test_outdated_stored_layout_is_dropped(tmp_path):
    p = tmp_path / "ws.json"
    p.write_text(json.dumps({"old": {"windows": [{"id": "z"}], "page": "home"}}), "utf-8")
    assert WorkspaceStore(p).load("old") is None


def test_workspace_limit(tmp_path):
    store = WorkspaceStore(tmp_path / "ws.json")
    for i in range(MAX_WORKSPACES):
        assert store.save(f"w{i}", _layout())
    assert not store.save("one-too-many", _layout())
    assert store.save("w0", _layout(_win()))  # overwrite is still fine


def test_contract_requests():
    ok = lambda m: contract.parse_request(json.dumps(m)) is not None
    assert ok({"kind": "workspace.list"})
    assert ok({"kind": "workspace.load", "name": "_last"})
    assert ok({"kind": "workspace.save", "name": "a", "layout": _layout(_win())})
    assert not ok({"kind": "workspace.delete", "name": "_last"})
    assert not ok({"kind": "workspace.save", "name": "a", "layout": {"windows": [{"id": 1}], "page": "home"}})
    assert not ok({"kind": "workspace.save", "name": "../x", "layout": _layout()})
    assert not ok({"kind": "workspace.load", "name": "x", "extra": 1})
