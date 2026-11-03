"""Provider selection and execution for JARVIS's text-only Live fallback.

This module does not coordinate UI state or security gates. The caller must do
those checks before and after the provider request, since the lock can change
while a network request is running.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from core.hybrid_llm_router import HybridLLMRouter, resolve_preferred_provider
from core.provider_protocol import ProviderResult, TextProviderRouter

logger = logging.getLogger("Jarvis.ProviderFallback")


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
    router_factory: Callable[..., TextProviderRouter] | None = None,
    task: str | None = None,
    tool_executor: Callable[[str, dict], str] | None = None,
    tool_declarations: list[dict] | None = None,
    claude_client_factory: Callable[..., Any] | None = None,
) -> tuple[ProviderResult, str]:
    """Run provider-routed text fallback and return results plus provider names.

    The second return value contains provider names only, never credentials.
    router_factory is injectable so tests need not make network requests.
    `task` is a core.task_router category; it only matters when the owner has
    a `task_routing` setting.

    With `tool_executor` and `tool_declarations`, and an Anthropic key, Claude
    answers first with the read-only allow-list in core/fallback_tools.py; the
    executor must run tools through the normal security/dispatcher path. If
    that fails for any reason, the text-only route below runs unchanged.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Text fallback requires a non-empty prompt.")

    config = _load_provider_config(config_path)
    keys = _provider_keys(config)
    preferred = resolve_preferred_provider(config, task=task)
    factory = router_factory or HybridLLMRouter
    router = factory(preferred_provider=preferred, api_keys=keys)
    status = router.configured_key_status()
    configured = ",".join(name for name, present in status.items() if present) or "none"
    claude_key = keys["claude"] or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if tool_executor is not None and tool_declarations and claude_key:
        from core.fallback_tools import run_claude_tool_fallback
        try:
            result = run_claude_tool_fallback(
                text,
                system_prompt=base_system_prompt,
                api_key=claude_key,
                declarations=tool_declarations,
                execute=tool_executor,
                task=task,
                client_factory=claude_client_factory,
            )
            return result, configured
        except Exception as exc:
            # Exception text can contain request details; log only the type.
            logger.warning("Claude tool fallback unavailable (%s); using text-only route",
                           type(exc).__name__)
    result = router.query(
        text,
        system_prompt=build_fallback_system_prompt(base_system_prompt),
    )
    if not isinstance(result, dict):
        raise RuntimeError("The selected provider returned an invalid result.")
    return result, configured
