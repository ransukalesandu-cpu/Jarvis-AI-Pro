"""Multi-model compare (P3 of the Cherry Studio parity plan)."""
from __future__ import annotations

import time

import pytest

from jarvis import compare as cmp


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))


def fake_ask(provider, prompt, system):
    if provider == "groq":
        raise RuntimeError("no API key configured for groq")
    if provider == "ollama":
        time.sleep(0.3)
    return {"text": f"{provider} says 42", "model": f"{provider}-model", "latency_ms": 100}


def test_parallel_compare_collects_failures():
    c = cmp.compare("meaning of life?", ["Claude", "gemini", "groq", "gpt"], ask=fake_ask)
    by = {a.provider: a for a in c.answers}
    assert list(by) == ["claude", "gemini", "groq", "openai"]
    assert by["claude"].ok and by["claude"].text == "claude says 42" and by["claude"].est_cost_usd > 0
    assert not by["groq"].ok and "no API key" in by["groq"].error
    text = cmp.summary(c)
    assert "## claude (claude-model)" in text and "groq — failed" in text


def test_timeout_marks_slow_provider():
    c = cmp.compare("q", ["gemini", "ollama"], ask=fake_ask, timeout=0.1)
    by = {a.provider: a for a in c.answers}
    assert by["gemini"].ok and by["ollama"].error == "timed out"


def test_validation():
    with pytest.raises(ValueError):
        cmp.compare("  ", ["gemini"], ask=fake_ask)
    with pytest.raises(ValueError):
        cmp.compare("q", ["skynet"], ask=fake_ask)


def test_pick_winner_and_wins():
    c = cmp.compare("write a haiku", ["claude", "gemini", "groq"], task="writing", ask=fake_ask)
    assert cmp.pick_winner("claude") == {"claude": 1}
    assert cmp.latest().winner == "claude"
    with pytest.raises(ValueError):
        cmp.pick_winner("groq")                 # it failed in that comparison
    cmp.pick_winner("claude", c.id)
    assert cmp.wins() == {"writing": {"claude": 2}}


def test_voice_tool(monkeypatch):
    from jarvis.actions import compare_models as tool

    monkeypatch.setattr(cmp, "_default_ask", fake_ask)
    out = tool.compare_models({"action": "compare", "prompt": "best laptop?", "providers": "claude, gemini"})
    assert "claude says 42" in out and "verdict" in out
    assert "## gemini" in tool.compare_models({"action": "show"})
    assert "claude: 1" in tool.compare_models({"action": "pick_winner", "provider": "claude"})
    assert "chat: claude 1" in tool.compare_models({"action": "wins"})


def test_tier():
    from jarvis.core import security
    assert security.tier_for("compare_models", {"action": "compare"}) == security.TIER_SAFE
    assert security.tier_for("compare_models", {"action": "pick_winner"}) == security.TIER_SENSITIVE
