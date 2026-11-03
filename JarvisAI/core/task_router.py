"""Task-based provider routing: which model family should handle a kind of task.

Gemini Live keeps everything real-time (voice, vision, screen, camera) and the
simple requests; Claude takes the work that needs deep reasoning (coding,
planning, long reasoning, writing); image generation goes to OpenAI when its key
is configured, otherwise Gemini.

The mapping is the ``task_routing`` setting in config/api_keys.json, a JSON
object of category -> provider, merged over :data:`DEFAULT_ROUTING`. Without
that setting nothing changes: :func:`routing_from_config` returns None and the
callers keep their previous provider choice. Whether a provider actually has a
key is not decided here: the chosen provider simply goes first in
HybridLLMRouter's existing ladder, which skips providers without keys.

Pure functions, no I/O, no network.
"""
from __future__ import annotations

import re
from typing import Any

from core.brain_protocol import profile_request

CATEGORIES = ("voice", "vision", "screen", "camera", "coding", "planning",
              "reasoning", "writing", "image_generation", "simple")
PROVIDERS = ("gemini", "claude", "openai", "groq", "ollama")

DEFAULT_ROUTING: dict[str, str] = {
    "voice": "gemini", "vision": "gemini", "screen": "gemini", "camera": "gemini",
    "coding": "claude", "planning": "claude", "reasoning": "claude", "writing": "claude",
    "image_generation": "openai",
    "simple": "gemini",
}

_IMAGE = re.compile(r"\b(generate|create|make|draw|paint|render|design)\b.{0,40}"
                    r"\b(image|picture|photo|illustration|logo|icon|wallpaper|art)\b", re.I)
_CAMERA = re.compile(r"\b(camera|webcam)\b", re.I)
_SCREEN = re.compile(r"\b(my screen|on screen|the screen|screenshot)\b", re.I)
_VISION = re.compile(r"\b(look at|what do you see|in this (image|photo|picture))\b", re.I)
_WRITING = re.compile(r"\b(write|draft|compose|rewrite|proofread|essay|letter|email|"
                      r"article|report|blog|cover letter|story|speech)\b", re.I)
_REASONING = re.compile(r"\b(why|explain|analy[sz]e|compare|evaluate|prove|derive|"
                        r"pros and cons|trade-?offs?|reason)\b", re.I)


def _normalize(provider: Any) -> str:
    p = str(provider or "").strip().lower()
    return "claude" if p == "anthropic" else p


def routing_from_config(config: dict[str, Any] | None) -> dict[str, str] | None:
    """The routing table, or None when the owner has not set ``task_routing``
    (callers then behave exactly as before)."""
    raw = (config or {}).get("task_routing")
    if not isinstance(raw, dict):
        return None
    table = dict(DEFAULT_ROUTING)
    for category, provider in raw.items():
        category = str(category).strip().lower()
        provider = _normalize(provider)
        if category in CATEGORIES and provider in PROVIDERS:
            table[category] = provider
    return table


def classify(text: str) -> str:
    """A task category from the request's wording (heuristic, no model call)."""
    request = str(text or "").strip()
    if not request:
        return "simple"
    if _IMAGE.search(request):
        return "image_generation"
    if _CAMERA.search(request):
        return "camera"
    if _SCREEN.search(request):
        return "screen"
    if _VISION.search(request):
        return "vision"
    profile = profile_request(request)
    if profile.kind == "planning":
        return "planning"
    if profile.kind == "technical":
        return "coding"
    if _WRITING.search(request):
        return "writing"
    if _REASONING.search(request) or profile.complexity == "complex":
        return "reasoning"
    return "simple"


def provider_for(category: str, table: dict[str, str],
                 has_key: dict[str, bool] | None = None) -> str:
    """The provider for ``category`` under ``table``.

    Image generation drops to Gemini when OpenAI has no key (it is the one
    category where the fallback is part of the routing rule itself).
    """
    category = category if category in CATEGORIES else "simple"
    provider = table.get(category) or table.get("simple") or "gemini"
    if category == "image_generation" and provider == "openai" and has_key is not None \
            and not has_key.get("openai"):
        return "gemini"
    return provider
