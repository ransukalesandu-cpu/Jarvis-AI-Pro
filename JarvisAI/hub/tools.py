"""Tools that live in the hub itself (they need the hub's own state).

They use the same interface as core.action_loader.ActionRegistry, so the
Phase 1 dispatch (`_execute_tool`) runs them like any other tool. Handlers run
in a worker thread; ``hub.call_soon(coro)`` reaches the hub's event loop.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from core.tool_runtime import ToolMeta


class HubToolRegistry:
    def __init__(self, hub):
        self.hub = hub
        self._tools: dict[str, dict] = {}

    def register(self, decl: dict, handler: Callable, meta: ToolMeta | None = None) -> None:
        self._tools[decl["name"]] = {"decl": decl, "handler": handler, "meta": meta or ToolMeta()}

    # ActionRegistry interface ------------------------------------------------
    def get_tool_declarations(self) -> list[dict]:
        return [t["decl"] for t in self._tools.values()]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> set[str]:
        return set(self._tools)

    def meta(self, name: str):
        tool = self._tools.get(name)
        return tool["meta"] if tool else None

    def scheduling(self, name: str):
        return None

    def run(self, name: str, parameters: dict, ctx: dict | None = None) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Tool '{name}' is not available."
        return tool["handler"](dict(parameters or {}), ctx or {})

    def run_on_loop(self, coro, timeout: float = 60.0):
        """From a worker thread: run a coroutine on the hub loop and wait."""
        return asyncio.run_coroutine_threadsafe(coro, self.hub.loop).result(timeout)


def register_core_tools(registry: HubToolRegistry) -> None:
    hub = registry.hub

    def list_devices(_params, _ctx):
        return hub.registry.describe()

    registry.register({
        "name": "list_devices",
        "description": "Which of the owner's devices (laptop, tablet, phone...) are online right now.",
        "parameters": {"type": "OBJECT", "properties": {}},
    }, list_devices, ToolMeta(risk="read", timeout=5))
