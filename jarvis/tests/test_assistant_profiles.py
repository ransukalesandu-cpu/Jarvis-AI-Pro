"""Assistant profiles (P9 of the Cherry Studio parity plan)."""
from __future__ import annotations

import pytest

from jarvis import assistants as ap


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))


def test_builtins_switch_and_prompt():
    assert {"coding", "writer", "designer", "tutor"} <= set(ap.all_profiles())
    assert ap.prompt_block() == ""
    prof = ap.activate("Coding assistant")
    assert prof["name"] == "coding" and ap.active_name() == "coding"
    block = ap.prompt_block()
    assert "ACTIVE ASSISTANT PROFILE: coding" in block and "same identity" in block
    assert ap.preferred_provider() == "claude"
    assert ap.activate("default") == {} and ap.active() is None
    with pytest.raises(KeyError):
        ap.activate("pirate")


def test_custom_profile_with_allow_list_and_kb(tmp_path, monkeypatch):
    from jarvis.knowledge import KnowledgeStore
    import jarvis.knowledge as kb

    store = KnowledgeStore(tmp_path / "kb.sqlite")
    store.create_base("clients")
    monkeypatch.setattr(kb, "get_store", lambda: store)
    name = ap.save_profile("Fiverr", "Help with client work.", provider="gpt", knowledge_base="clients",
                           allowed_tools=["web_search", "notes", "bad name!"])
    assert name == "fiverr"
    prof = ap.all_profiles()["fiverr"]
    assert prof["provider"] == "openai" and prof["allowed_tools"] == ["notes", "web_search"]
    ap.activate("fiverr")
    assert store.get_active() == "clients"
    assert ap.tool_block_reason("web_search") == ""
    assert ap.tool_block_reason("knowledge") == ""            # always allowed
    assert "does not use the run_command tool" in ap.tool_block_reason("run_command")
    ap.delete_profile("fiverr")
    assert ap.active() is None and ap.tool_block_reason("run_command") == ""


def test_validation():
    with pytest.raises(ValueError):
        ap.save_profile("x" * 60, "y")
    with pytest.raises(ValueError):
        ap.save_profile("ok", "")
    with pytest.raises(ValueError):
        ap.save_profile("ok", "y", provider="skynet")
    with pytest.raises(KeyError):
        ap.delete_profile("coding")                          # built-in


def test_guard_enforces_allow_list(monkeypatch):
    from jarvis.core import security

    ap.save_profile("research", "Research only.", allowed_tools=["web_search"])
    ap.activate("research")
    out = security.guard("weather_report", {}, lambda: "RAN")
    assert "does not use the weather_report tool" in out


def test_text_brain_prefers_profile_provider(monkeypatch):
    from jarvis.core import text_brain

    calls = []
    monkeypatch.setattr(text_brain, "ask_provider", lambda prov, prompt, system="": calls.append(prov) or {"text": "hi"})
    ap.activate("writer")
    assert text_brain.ask("x")["text"] == "hi" and calls == ["claude"]


def test_voice_tool():
    from jarvis.actions import assistant_profiles as tool

    assert "designer [built-in]" in tool.assistant_profiles({"action": "list"})
    assert "Switched to the tutor profile" in tool.assistant_profiles({"action": "switch", "name": "tutor"})
    assert "Active profile: tutor" in tool.assistant_profiles({"action": "current"})
    assert "saved" in tool.assistant_profiles({"action": "create", "name": "chef", "instructions": "Cook.",
                                                 "allowed_tools": "web_search, notes"})
    assert "Back to default" in tool.assistant_profiles({"action": "switch", "name": "jarvis"})
    assert "Profile deleted" in tool.assistant_profiles({"action": "delete", "name": "chef"})


def test_tiers():
    from jarvis.core import security
    assert security.tier_for("assistant_profiles", {"action": "list"}) == security.TIER_SAFE
    assert security.tier_for("assistant_profiles", {"action": "switch"}) == security.TIER_SENSITIVE
    assert security.tier_for("assistant_profiles", {"action": "create"}) == security.TIER_DANGEROUS
