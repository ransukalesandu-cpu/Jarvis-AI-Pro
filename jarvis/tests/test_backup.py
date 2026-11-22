"""Backup and restore (P7 of the Cherry Studio parity plan)."""
from __future__ import annotations

import zipfile

import pytest

from jarvis import backup as bk


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "userdata"))
    monkeypatch.delenv("JARVIS_BACKUP_PASSWORD", raising=False)
    monkeypatch.setenv("JARVIS_BACKUP_DIR", str(tmp_path / "out"))
    data, config, memory = tmp_path / "data", tmp_path / "config", tmp_path / "memory"
    (data / "knowledge").mkdir(parents=True)
    (data / "knowledge" / "kb.sqlite").write_bytes(b"SQLITE")
    (data / "notes").mkdir()
    (data / "notes" / "idea.md").write_text("orb", encoding="utf-8")
    (data / "cc-screenshots").mkdir()
    (data / "cc-screenshots" / "big.png").write_bytes(b"x")
    config.mkdir()
    (config / "api_keys.json").write_text('{"gemini_api_key": "SECRET"}', encoding="utf-8")
    (config / "settings.json").write_text('{"theme": "dark"}', encoding="utf-8")
    (config / "__init__.py").write_text("code", encoding="utf-8")
    memory.mkdir()
    (memory / "memory.db").write_bytes(b"MEM")
    (memory / "memory_manager.py").write_text("code", encoding="utf-8")
    sources = {"data": (data, False), "config": (config, True), "memory": (memory, True)}
    return sources, tmp_path


def _names(path):
    with zipfile.ZipFile(path) as z:
        return set(z.namelist())


def test_plain_backup_excludes_secrets_and_code(env):
    sources, tmp = env
    r = bk.create_backup(password="", sources=sources, upload=False, clock=lambda: 1_700_000_000)
    assert r.path.suffix == ".zip" and not r.encrypted and r.skipped_secrets == 1
    names = _names(r.path)
    assert {"data/knowledge/kb.sqlite", "data/notes/idea.md", "config/settings.json", "memory/memory.db"} <= names
    assert "config/api_keys.json" not in names
    assert not any("cc-screenshots" in n or n.endswith(".py") for n in names)


def test_encrypted_backup_includes_secrets_and_roundtrips(env):
    sources, tmp = env
    r = bk.create_backup(password="hunter2", sources=sources, upload=False)
    blob = r.path.read_bytes()
    assert r.path.suffix == ".jvbk" and blob.startswith(bk.MAGIC) and b"SECRET" not in blob
    info = bk.preview(r.path, password="hunter2")
    assert info["files"] == 5 and info["by_root"]["config"] == 2
    with pytest.raises(ValueError, match="wrong backup password"):
        bk.preview(r.path, password="nope")
    with pytest.raises(ValueError, match="encrypted"):
        bk.preview(r.path, password="")


def test_restore_overwrites_and_makes_safety_backup(env):
    sources, tmp = env
    r = bk.create_backup(password="pw", sources=sources, upload=False, clock=lambda: 1_700_000_000)
    note = sources["data"][0] / "notes" / "idea.md"
    note.write_text("changed", encoding="utf-8")
    (sources["config"][0] / "api_keys.json").write_text("{}", encoding="utf-8")
    n = bk.restore(r.path, password="pw", targets=sources)
    assert n == 5 and note.read_text(encoding="utf-8") == "orb"
    assert "SECRET" in (sources["config"][0] / "api_keys.json").read_text(encoding="utf-8")
    assert len(bk.list_backups()) == 2                 # original + safety backup


def test_zip_slip_is_blocked(env, tmp_path):
    sources, _ = env
    evil = bk.backup_dir() / "jarvis-backup-20200101-000000.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("data/../../escaped.txt", "pwned")
        z.writestr("data/ok.txt", "fine")
    n = bk.restore(evil, password="", targets=sources, safety_backup=False)
    assert n == 1 and not (tmp_path / "escaped.txt").exists()


def test_prune_and_schedule(env, monkeypatch):
    sources, tmp = env
    for i in range(4):
        bk.create_backup(password="", sources=sources, upload=False, keep=2, clock=lambda i=i: 1_700_000_000 + i)
    assert len(bk.list_backups()) == 2
    assert bk.due() is False                           # no schedule
    bk.save_config(every_days=1, last_backup=0)
    assert bk.due(now=86_400 * 2) is True
    bk.save_config(last_backup=86_400 * 2)
    assert bk.due(now=86_400 * 2.5) is False


def test_webdav_upload_https_only(env, tmp_path):
    f = tmp_path / "x.zip"
    f.write_bytes(b"z")
    with pytest.raises(ValueError):
        bk.webdav_upload(f, {"url": "http://insecure"})
    seen = {}

    class Resp:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        seen["url"], seen["auth"], seen["method"] = req.full_url, req.get_header("Authorization"), req.get_method()
        return Resp()

    dest = bk.webdav_upload(f, {"url": "https://dav.example.com/jarvis/", "user": "me", "password": "p"}, opener=opener)
    assert dest == "https://dav.example.com/jarvis/x.zip" and seen["method"] == "PUT" and seen["auth"].startswith("Basic ")


def test_voice_tool(env, monkeypatch):
    from jarvis.actions import backup as tool

    sources, _ = env
    monkeypatch.setattr(bk, "roots", lambda: sources)
    assert "No backups yet" in tool.backup({"action": "list"})
    out = tool.backup({"action": "create"})
    assert "Backup saved" in out and "left out" in out
    assert "files" in tool.backup({"action": "preview", "name": "latest"})
    assert "every 2 day(s)" in tool.backup({"action": "schedule", "every_days": 2})
    assert "Schedule: every 2 day(s)" in tool.backup({"action": "status"})
    assert "Automatic backups are off" in tool.backup({"action": "schedule", "every_days": 0})


def test_tiers():
    from jarvis.core import security
    assert security.tier_for("backup", {"action": "status"}) == security.TIER_SAFE
    assert security.tier_for("backup", {"action": "create"}) == security.TIER_SENSITIVE
    assert security.tier_for("backup", {"action": "restore"}) == security.TIER_DANGEROUS
