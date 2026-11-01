"""Stable contracts between JARVIS reasoning agents and protected action dispatch.

These are structural typing boundaries only. They do not grant permission to run
an action: the existing authentication, privacy-lock, confirmation, and
ActionDispatcher checks remain mandatory at the application call site.
"""
from __future__ import annotations

from typing import Any, NotRequired, Protocol, TypedDict, runtime_checkable


class AgentResponse(TypedDict):
    """Normalized result returned by a reasoning agent."""

    text: str
    provider: NotRequired[str]
    model: NotRequired[str]
    mode: NotRequired[str]
    latency_ms: NotRequired[float | None]
    task_profile: NotRequired[dict[str, Any]]
    memory_hits: NotRequired[int]
    history_items: NotRequired[int]
    context_chars: NotRequired[int]
    configured_providers: NotRequired[str]


@runtime_checkable
class ReasoningAgent(Protocol):
    """Interface for agents that produce answers but do not execute actions."""

    def respond(self, user_text: str, **kwargs: Any) -> AgentResponse:
        ...


@runtime_checkable
class ActionGateway(Protocol):
    """Minimal existing dispatch boundary; callers still enforce authorization."""

    def run(
        self, name: str, parameters: dict[str, Any], ctx: dict[str, Any] | None = None
    ) -> str:
        ...
