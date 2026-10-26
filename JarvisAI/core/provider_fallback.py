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
    router_factory: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """Run provider-routed text fallback and return results plus provider names.

    The second return value contains provider names only, never credentials.
    router_factory is injectable so tests need not make network requests.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Text fallback requires a non-empty prompt.")

    config = _load_provider_config(config_path)
    keys = _provider_keys(config)
    preferred = resolve_preferred_provider(config)
    factory = router_factory or HybridLLMRouter
    router = factory(preferred_provider=preferred, api_keys=keys)
    status = router.configured_key_status()
    configured = ",".join(name for name, present in status.items() if present) or "none"
    result = router.query(
        text,
        system_prompt=build_fallback_system_prompt(base_system_prompt),
    )
    if not isinstance(result, dict):
        raise RuntimeError("The selected provider returned an invalid result.")
    return result, configured
