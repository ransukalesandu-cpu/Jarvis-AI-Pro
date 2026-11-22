"""File library + Mini Apps (P10 of the Cherry Studio parity plan)."""
from __future__ import annotations

import pytest

from jarvis import library as lib


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))


def test_register_list_search_forget(tmp_path):
    a = tmp_path / "contract (Sinhala).docx"
    a.write_text("x")
    b = tmp_path / "jarvis-backup-20261122-101010.zip"
    b.write_text("y")
    lib.register(a, "translation", source="translate")
    lib.register(b, "backup")
    lib.register(a, "translation")                       # re-register moves it to the top, no duplicate
    rows = lib.items()
    assert [r["name"] for r in rows] == [a.name, b.name]
    assert [r["name"] for r in lib.items(kind="backup")] == [b.name]
    assert lib.find_one("contract sinhala")["path"] == str(a.resolve())
    b.unlink()
    assert len(lib.items()) == 1 and len(lib.items(include_missing=True)) == 2
    assert lib.forget_missing() == 1
    lib.register(tmp_path / "x" / "..", "weird-kind")    # unknown kind -> other, never raises


def test_scan_pictures_folder(tmp_path):
    pics = tmp_path / "home" / "Pictures" / "JARVIS"
    pics.mkdir(parents=True)
    (pics / "ad-1.jpg").write_bytes(b"jpg")
    assert lib.scan_known_folders() == 1
    assert lib.items(kind="media")[0]["name"] == "ad-1.jpg"
    assert lib.scan_known_folders() == 0


def test_mini_apps_add_open_remove(tmp_path):
    assert "figma" in lib.mini_apps()
    with pytest.raises(ValueError):
        lib.add_app("bad", "http://insecure.example")
    with pytest.raises(ValueError):
        lib.add_app("bad", "https://user:pw@example.com")  # pragma: allowlist secret
    assert lib.add_app("Notion App", "https://www.notion.so/") == "notion"
    launched = []
    assert lib.open_app("notion", launcher=launched.append, browser="/usr/bin/msedge") == "notion"
    cmd = launched[0]
    assert cmd[0] == "/usr/bin/msedge" and cmd[1] == "--app=https://www.notion.so/"
    assert "miniapps" in cmd[2] and cmd[2].startswith("--user-data-dir=")
    assert lib.open_app("fig", launcher=launched.append, browser="x") == "figma"     # fuzzy single match
    lib.remove_app("figma")
    assert "figma" not in lib.mini_apps()
    with pytest.raises(KeyError):
        lib.open_app("nothing-like-this", launcher=launched.append, browser="x")


def test_voice_tools(tmp_path, monkeypatch):
    from jarvis.actions import library as tool

    assert "empty" in tool.file_library({"action": "list"})
    f = tmp_path / "logo.png"
    f.write_bytes(b"p")
    lib.register(f, "media")
    assert "logo.png" in tool.file_library({"action": "search", "query": "logo"})
    assert "Telegram is not set up" in tool.file_library({"action": "send_to_phone", "query": "logo"})
    assert "canva" in tool.mini_app({"action": "list"})
    assert "added" in tool.mini_app({"action": "add", "name": "trello", "url": "https://trello.com/"})
    assert "https://" in tool.mini_app({"action": "add", "name": "x", "url": "ftp://x"})


def test_tiers():
    from jarvis.core import security
    assert security.tier_for("file_library", {"action": "list"}) == security.TIER_SAFE
    assert security.tier_for("file_library", {"action": "send_to_phone"}) == security.TIER_DANGEROUS
    assert security.tier_for("mini_app", {"action": "open"}) == security.TIER_SENSITIVE
    assert security.tier_for("mini_app", {"action": "add"}) == security.TIER_DANGEROUS
