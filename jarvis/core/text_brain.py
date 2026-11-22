"""One-shot text answers from the hybrid router, for tools that need an LLM without the live session.

Used by translate, quick actions and model compare. Keys come from
``config/api_keys.json`` (field names) mapped to the router's provider names,
with environment variables as fallback (the router reads those itself).
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

PROVIDERS = ("gemini", "groq", "openai", "claude", "ollama")
_FIELDS = {"gemini": "gemini_api_key", "openai": "openai_api_key", "claude": "anthropic_api_key", "groq": "groq_api_key"}
_ENV = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "claude": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY"}
_ALIASES = {"anthropic": "claude", "gpt": "openai", "chatgpt": "openai", "google": "gemini", "local": "ollama",
            "llama": "ollama"}

_router = None
_router_lock = threading.Lock()
_router_at = 0.0
_override: Optional[Callable[..., dict]] = None     # tests


def normalize(provider: str) -> str:
    p = str(provider or "").strip().lower()
    return _ALIASES.get(p, p)


def _config() -> dict:
    try:
        from jarvis.memory.config_manager import load_api_keys
        return load_api_keys() or {}
    except Exception:
        return {}


def configured() -> list[str]:
    """Cloud providers with a key, plus ollama (local, may or may not be running)."""
    cfg = _config()
    out = [p for p in ("gemini", "groq", "openai", "claude")
           if str(cfg.get(_FIELDS[p]) or "").strip() or os.environ.get(_ENV[p], "").strip()]
    return out + ["ollama"]


def get_router():
    global _router, _router_at
    with _router_lock:
        if _router is None or time.monotonic() - _router_at > 300:       # pick up key changes
            from jarvis.core.hybrid_llm_router import HybridLLMRouter, resolve_preferred_provider
            cfg = _config()
            keys = {p: str(cfg.get(f) or "") for p, f in _FIELDS.items() if cfg.get(f)}
            _router = HybridLLMRouter(resolve_preferred_provider(cfg), api_keys=keys, timeout=90.0,
                                      online_check=False)
            _router_at = time.monotonic()
        return _router


def ask(prompt: str, system: str = "You are JARVIS, a capable personal AI assistant.", *, task: str = "chat") -> dict:
    """{'text', 'provider', 'model', 'latency_ms'} from the first provider that answers. Raises when none can."""
    if _override is not None:
        return _override(prompt, system, None)
    return dict(get_router().query(prompt, system_prompt=system, task=task))


def ask_text(prompt: str, system: str = "You are JARVIS, a capable personal AI assistant.", *, task: str = "chat") -> str:
    return str(ask(prompt, system, task=task).get("text") or "").strip()


def ask_provider(provider: str, prompt: str, system: str = "You are a helpful assistant.") -> dict:
    """Ask exactly one provider (no failover). Raises on failure."""
    provider = normalize(provider)
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider '{provider}'")
    if _override is not None:
        return _override(prompt, system, provider)
    r = get_router()
    if provider != "ollama" and not r._key(provider):
        raise RuntimeError(f"no API key configured for {provider}")
    started = time.monotonic()
    result = r._validate_result(r.providers[provider](prompt, system), provider)
    result = dict(result)
    result.update({"provider": provider, "latency_ms": round((time.monotonic() - started) * 1000, 1)})
    from jarvis.core import usage_meter
    usage_meter.record(provider, str(result.get("model") or ""), in_chars=len(prompt) + len(system),
                       out_chars=len(str(result.get("text") or "")), latency_ms=result["latency_ms"])
    return result
