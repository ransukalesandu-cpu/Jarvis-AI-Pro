"""Structural contracts shared by JARVIS text providers and brain routing.

These interfaces describe the stable boundary between orchestration and
provider implementations. They contain no provider SDK or network logic.
"""
from __future__ import annotations

from typing import Any, NotRequired, Protocol, TypedDict, runtime_checkable


class ProviderResult(TypedDict):
    """Normalized response exposed by every text provider."""

    text: str
    model: NotRequired[str]
    provider: NotRequired[str]
    mode: NotRequired[str]
    latency_ms: NotRequired[float]


@runtime_checkable
class TextProvider(Protocol):
    """Callable provider adapter accepted by the hybrid router."""

    def __call__(
        self, prompt: str, system_prompt: str, **kwargs: Any
    ) -> ProviderResult:
        ...


@runtime_checkable
class TextProviderRouter(Protocol):
    """Minimal router contract required by brain orchestration."""

    def configured_key_status(self) -> dict[str, bool]:
        ...

    def query(
        self, prompt: str, system_prompt: str = ..., **kwargs: Any
    ) -> ProviderResult:
        ...
