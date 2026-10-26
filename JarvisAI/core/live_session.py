"""Policy helpers for Gemini Live session selection and reconnect setup.

The live task orchestration stays in JarvisLive for now. Pure session policy is
isolated here so fallback selection and API-version decisions can be tested
without opening a Live connection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def select_live_model(
    *,
    primary_model: str,
    fallback_models: Sequence[str],
    cooldowns: Mapping[str, float],
    now: float,
    proactive_audio_enabled: bool,
    proactive_audio_model: str,
) -> str:
    """Select the first available model; otherwise retry the earliest cooldown."""
    candidates = (primary_model, *fallback_models)
    if not proactive_audio_enabled:
        candidates = tuple(
            model for model in candidates if model != proactive_audio_model
        )
    if not candidates:
        raise ValueError("At least one Gemini Live model must be configured.")

    for model in candidates:
        if cooldowns.get(model, 0.0) <= now:
            return model
    return min(candidates, key=lambda model: cooldowns.get(model, 0.0))


def select_live_api_version(
    *,
    enhanced_live: bool,
    active_model: str,
    primary_model: str,
) -> str:
    """Keep the enhanced primary model on v1alpha, all other sessions on v1beta."""
    return (
        "v1alpha"
        if enhanced_live and active_model == primary_model
        else "v1beta"
    )
