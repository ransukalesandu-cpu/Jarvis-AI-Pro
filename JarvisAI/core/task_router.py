"""Task-based provider routing: which model family handles which kind of task.

Pure functions, no network and no file access. Callers pass the already-loaded
settings dict (config/api_keys.json). The mapping only applies when the owner
has a ``task_routing`` setting; without one, callers keep their legacy
provider choice exactly as before.

``task_routing`` may be ``true`` (use the defaults below) or a mapping that
overrides some categories, e.g. ``{"writing": "openai", "coding": "claude"}``.
Unknown categories and unknown provider names are ignored.

This module only picks the *preferred* provider. Missing keys are handled by
HybridLLMRouter's existing fallback ladder, which skips providers that have no
key and tries the next one, so that logic is not duplicated here. The one
exception is ``image_generation``, whose default is defined as "openai if a key
exists, else gemini".

Gemini Live remains the real-time voice/vision path; ``voice``, ``vision``,
``screen`` and ``camera`` map to gemini so a text fallback for those requests
stays on the same provider family.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

# Provider names as HybridLLMRouter knows them ("anthropic" is accepted as an alias).
KNOWN_PROVIDERS = ("gemini", "groq", "openai", "claude", "ollama")

TASK_CATEGORIES = (
    "voice", "vision", "screen", "camera",
    "coding", "planning", "reasoning", "writing",
    "image_generation", "simple",
)

DEFAULT_TASK_ROUTING: dict[str, str] = {
    "voice": "gemini",
    "vision": "gemini",
    "screen": "gemini",
    "camera": "gemini",
    "coding": "claude",
    "planning": "claude",
    "reasoning": "claude",
    "writing": "claude",
    "image_generation": "openai",
    "simple": "gemini",
}

_WRITING_PATTERN = re.compile(
    r"\b(write|draft|compose|rewrite|essay|letter|e-?mail|article|blog|story|"
    r"report|cover letter|speech|proofread)\b",
    re.IGNORECASE,
)


def _normalize_provider(value: Any) -> str:
    name = str(value or "").strip().lower()
    if name == "anthropic":
        name = "claude"
    return name if name in KNOWN_PROVIDERS else ""


def task_routing_enabled(config: Mapping[str, Any] | None) -> bool:
    """True when the owner opted into task routing with a ``task_routing`` setting."""
    if not isinstance(config, Mapping):
        return False
    value = config.get("task_routing")
    return value is True or isinstance(value, Mapping)


def task_routing_table(config: Mapping[str, Any] | None) -> dict[str, str]:
    """The defaults with the owner's valid overrides applied."""
    table = dict(DEFAULT_TASK_ROUTING)
    value = config.get("task_routing") if isinstance(config, Mapping) else None
    if isinstance(value, Mapping):
        for category, provider in value.items():
            category = str(category or "").strip().lower()
            provider = _normalize_provider(provider)
            if category in table and provider:
                table[category] = provider
    return table


def provider_for_task(
    category: str,
    config: Mapping[str, Any] | None = None,
    *,
    has_key: Callable[[str], bool] | None = None,
) -> str:
    """Preferred provider for a task category; unknown categories count as ``simple``.

    ``has_key(provider)`` is consulted only for image generation, whose default
    falls back to gemini when no OpenAI key is configured.
    """
    name = str(category or "").strip().lower()
    if name not in DEFAULT_TASK_ROUTING:
        name = "simple"
    provider = task_routing_table(config)[name]
    if name == "image_generation" and provider != "gemini" and has_key is not None:
        try:
            if not has_key(provider):
                return "gemini"
        except Exception:
            return "gemini"
    return provider


def category_for_request(text: str, profile: Any | None = None) -> str:
    """Map a text request (and its core.brain_protocol profile) to a category."""
    if profile is None:
        from core.brain_protocol import profile_request
        profile = profile_request(text)
    kind = str(getattr(profile, "kind", "") or "")
    complexity = str(getattr(profile, "complexity", "") or "")
    if kind == "planning":
        return "planning"
    if kind == "technical":
        return "coding"
    if kind == "current_information":
        return "simple"
    if _WRITING_PATTERN.search(str(text or "")):
        return "writing"
    return "reasoning" if complexity == "complex" else "simple"
