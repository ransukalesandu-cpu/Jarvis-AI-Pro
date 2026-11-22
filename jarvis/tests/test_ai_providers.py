"""Provider manager + usage meter (P8 of the Cherry Studio parity plan)."""
from __future__ import annotations

import json

import pytest

from jarvis.core import usage_meter


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    usage_meter.set_notifier(None)


def test_record_and_reports():
    usage_meter.record("claude", "claude-x", in_chars=4000, out_chars=8000, latency_ms=900, now=1_763_800_000)
    usage_meter.record("claude", "claude-x", in_chars=400, out_chars=400, now=1_763_800_000)
    usage_meter.record("ollama", "llama", in_chars=400, out_chars=400, now=1_763_800_000)
    import time
    day = time.strftime("%Y-%m-%d", time.localtime(1_763_800_000))
    d = usage_meter.day_usage(day)
    assert d["claude"]["calls"] == 2 and d["claude"]["in_tokens"] == 1100 and d["claude"]["cost_usd"] > 0
    assert d["ollama"]["cost_usd"] == 0
    m = usage_meter.month_usage(day[:7])
    assert m["claude"]["calls"] == 2
    text = usage_meter.report(d, "today")
    assert text.startswith("AI usage today") and "claude: 2 calls" in text
    assert usage_meter.report({}, "today") == "No AI usage recorded today."


def test_budget_alert_fires_once_per_day():
    alerts = []
    usage_meter.set_notifier(alerts.append)
    usage_meter.save_settings(daily_budget_usd=0.01)
    for _ in range(3):
        usage_meter.record("claude", in_chars=40_000, out_chars=40_000, now=1_763_800_000)
    assert len(alerts) == 1 and "daily budget" in alerts[0]


def test_record_never_raises(monkeypatch):
    monkeypatch.setattr(usage_meter, "_dir", lambda: (_ for _ in ()).throw(OSError("disk full")))
    usage_meter.record("gemini", in_chars=1, out_chars=1)


def test_router_records_usage(monkeypatch):
    from jarvis.core.hybrid_llm_router import HybridLLMRouter

    r = HybridLLMRouter("ollama", online_check=False)
    r.providers["ollama"] = lambda prompt, system, **kw: {"text": "hello there", "model": "llama3"}
    out = r.query("hi")
    assert out["provider"] == "ollama"
    assert usage_meter.day_usage()["ollama"]["calls"] == 1


def test_tool_routes_usage_budget_and_test(monkeypatch, tmp_path):
    from jarvis.actions import ai_providers as tool
    from jarvis.core import provider_settings, text_brain

    cfg_file = tmp_path / "api_keys.json"
    cfg_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(provider_settings, "_read", lambda: json.loads(cfg_file.read_text()))
    monkeypatch.setattr(provider_settings, "_write", lambda d: cfg_file.write_text(json.dumps(d)))
    assert "No task routes" in tool.ai_providers({"action": "routes"})
    assert "coding: ollama" in tool.ai_providers({"action": "set_route", "task": "coding", "provider": "local"})
    assert json.loads(cfg_file.read_text())["task_routing"] == {"coding": "ollama"}
    assert "Unknown task" in tool.ai_providers({"action": "set_route", "task": "dancing", "provider": "claude"})
    assert "$2.00" in tool.ai_providers({"action": "set_budget", "budget_usd": 2})
    assert "No AI usage" in tool.ai_providers({"action": "usage"})
    monkeypatch.setattr(text_brain, "_override", lambda prompt, system, provider: {"text": "OK", "model": "m"})
    assert "claude works" in tool.ai_providers({"action": "test", "provider": "anthropic"})
    assert "ollama: local" in tool.ai_providers({"action": "status"})


def test_tiers():
    from jarvis.core import security
    assert security.tier_for("ai_providers", {"action": "status"}) == security.TIER_SAFE
    assert security.tier_for("ai_providers", {"action": "set_route"}) == security.TIER_SENSITIVE
