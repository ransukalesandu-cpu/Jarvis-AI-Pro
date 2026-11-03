"""Provider selection and execution for JARVIS's text-only Live fallback.

This module does not coordinate UI state or security gates. The caller must do
those checks before and after the provider request, since the lock can change
while a network request is running.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from core.hybrid_llm_router import HybridLLMRouter, resolve_preferred_provider
from core.provider_protocol import ProviderResult, TextProviderRouter


_FALLBACK_PROMPT_RULES = (
    "\n\nHYBRID TEXT FALLBACK RULES: You are in a text-only fallback "
    "with no live tools or computer-control capability. Never claim you "
    "opened apps, changed files, searched the web, or completed an action. "
    "Explain limitations honestly and answer informational questions directly."
)


def build_fallback_system_prompt(base_prompt: str) -> str:
    """Append the no-tools contract used by the text-only fallback."""
    return (base_prompt or "") + _FALLBACK_PROMPT_RULES


def _load_provider_config(config_path: str | Path) -> dict[str, Any]:
    """Load provider settings without ever logging credentials."""
    try:
        with Path(config_path).open("r", encoding="utf-8") as stream:
            loaded = json.load(stream)
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError, TypeError, UnicodeError):
        return {}


def _env_claude_key() -> bool:
    from core.provider_settings import get_provider_api_key
    return bool(get_provider_api_key("anthropic"))


def _provider_keys(config: dict[str, Any]) -> dict[str, str]:
    """Map local provider credential fields to the hybrid router names."""
    return {
        "gemini": str(config.get("gemini_api_key") or "").strip(),
        "groq": str(config.get("groq_api_key") or "").strip(),
        "openai": str(config.get("openai_api_key") or "").strip(),
        "claude": str(
            config.get("anthropic_api_key") or config.get("claude_api_key") or ""
        ).strip(),
    }


def query_text_fallback(
    text: str,
    *,
    config_path: str | Path,
    base_system_prompt: str,
    router_factory: Callable[..., TextProviderRouter] | None = None,
    toolbox: Any = None,
    tool_client_factory: Callable | None = None,
    task_text: str | None = None,
) -> tuple[ProviderResult, str]:
    """Run provider-routed text fallback and return results plus provider names.

    The second return value contains provider names only, never credentials.
    router_factory is injectable so tests need not make network requests.

    With a ``toolbox`` (core/fallback_tools.FallbackToolbox) and an Anthropic
    key, Claude answers first and may call the toolbox's read-only tools; if
    that fails for any reason the ordinary text-only route below runs.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Text fallback requires a non-empty prompt.")
    # Classify the owner's request, not a prompt that wraps it in history and
    # guidance (BrainEngine passes the request as task_text).
    task_text = task_text if isinstance(task_text, str) and task_text.strip() else text

    config = _load_provider_config(config_path)
    keys = _provider_keys(config)
    if toolbox is not None and (keys.get("claude") or _env_claude_key()):
        import time as _time
        from core.fallback_tools import answer_with_tools
        started = _time.monotonic()
        try:
            result = answer_with_tools(text, base_system_prompt, toolbox,
                                       client_factory=tool_client_factory,
                                       task_text=task_text)
            result.update({"mode": "cloud",
                           "latency_ms": round((_time.monotonic() - started) * 1000, 2)})
            configured = ",".join(name for name, value in keys.items() if value) or "claude"
            return result, configured
        except Exception as exc:
            # Fall through to the text-only ladder; log the type only.
            print(f"[Fallback] Claude with tools unavailable ({type(exc).__name__}); "
                  "using the text-only route.")
    preferred = resolve_preferred_provider(config)
    factory = router_factory or HybridLLMRouter
    # Task routing (core/task_router.py) only when the owner set task_routing;
    # otherwise the router is built and queried exactly as before.
    from core.task_router import classify, routing_from_config
    routing = routing_from_config(config)
    if routing is None:
        router = factory(preferred_provider=preferred, api_keys=keys)
        route_kwargs: dict[str, Any] = {}
    else:
        router = factory(preferred_provider=preferred, api_keys=keys, task_routing=routing)
        route_kwargs = {"task": classify(task_text)}
    status = router.configured_key_status()
    configured = ",".join(name for name, present in status.items() if present) or "none"
    result = router.query(
        text,
        system_prompt=build_fallback_system_prompt(base_system_prompt),
        **route_kwargs,
    )
    if not isinstance(result, dict):
        raise RuntimeError("The selected provider returned an invalid result.")
    return result, configured
