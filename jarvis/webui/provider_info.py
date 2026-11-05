"""What the one-shot AI provider currently is, from the real settings. Never contains a key."""
from __future__ import annotations

_LABELS = {"gemini": "Gemini", "openai": "OpenAI GPT", "anthropic": "Anthropic Claude"}


def snapshot() -> dict | None:
    try:
        from jarvis.core import provider_settings as ps

        s = ps.get_provider_settings()
        p = s["provider"]
        if p == "openai":
            model, has = s["openai_model_reasoning"], s["has_openai_key"]
        elif p == "anthropic":
            model, has = s["anthropic_model_reasoning"], s["has_anthropic_key"]
        else:
            model, has = "default", bool(ps._read().get("gemini_api_key"))
        return {"provider": _LABELS.get(p, "Gemini"), "model": str(model)[:120] or "default", "connected": bool(has), "fallback": False}
    except (OSError, KeyError, ValueError, TypeError):
        return None   # unknown -> the UI shows "not reported", not a guess
