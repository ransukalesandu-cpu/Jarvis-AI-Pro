"""memory.status: on/off facts only; no URL, key or memory content may reach the page."""
from __future__ import annotations

import jarvis.memory.config_manager as cm
from jarvis.webui import contract as c
from jarvis.webui.memory_status import memory_status


def test_reports_cloud_from_env_without_leaking_it(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://secret-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "eyJ-secret")
    monkeypatch.setattr(cm, "get_personal_cloud_memory_enabled", lambda: True)
    monkeypatch.setattr(cm, "get_memory_encryption_enabled", lambda: False)
    st = memory_status()
    assert st == {"cloud": "configured", "personal": True, "encrypted": False}
    wire = c.encode_event("memory.status", **st)
    assert wire and "secret" not in wire and "eyJ" not in wire


def test_missing_key_means_not_configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    assert memory_status()["cloud"] == "not_configured"


def test_unreadable_config_reports_off_not_on(monkeypatch):
    def boom():
        raise OSError("config unreadable")
    monkeypatch.setattr(cm, "get_personal_cloud_memory_enabled", boom)
    st = memory_status()
    assert st["personal"] is False and st["encrypted"] is False


def test_contract_rejects_anything_but_the_closed_shape():
    assert c.encode_event("memory.status", cloud="configured", personal=True, encrypted=False)
    assert c.encode_event("memory.status", cloud="https://x.supabase.co", personal=True, encrypted=False) is None
    assert c.encode_event("memory.status", cloud="configured", personal=1, encrypted=False) is None
    assert c.encode_event("memory.status", cloud="configured", personal=True, encrypted=False, url="x") is None
