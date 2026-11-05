"""Agent registry: which application agent owns which cc tools.

UFO² gives every application its own AppAgent. Here an "agent" is a small
descriptor — a name, the tools it may call, and a recovery helper — because the
actual control lives in the controllers (windows/, browser/, visual/). The Host
Agent routes each step to the agent that owns its tool, and new agents (browser
in Project 3, visual in Project 4, workflows in Project 5) register themselves
here without touching the host.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class AppAgent:
    name: str
    description: str
    tools: frozenset
    #: optional recovery hook: (host, step, result) -> list of extra step dicts to try once
    recover: Optional[Callable] = None
    apps: tuple = field(default_factory=tuple)      # app/process names it is best for


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AppAgent] = {}

    def register(self, agent: AppAgent) -> AppAgent:
        if agent.name in self._agents:
            raise ValueError(f"agent {agent.name!r} already registered")
        for other in self._agents.values():
            clash = other.tools & agent.tools
            if clash:
                raise ValueError(f"tools {sorted(clash)} already owned by {other.name}")
        self._agents[agent.name] = agent
        return agent

    def for_tool(self, tool: str) -> Optional[AppAgent]:
        for agent in self._agents.values():
            if tool in agent.tools:
                return agent
        return None

    def names(self) -> list[str]:
        return list(self._agents)

    def all(self) -> list[AppAgent]:
        return list(self._agents.values())


def _windows_recover(host, step, result) -> list[dict]:
    """One extra attempt for the common, safe-to-retry Windows failures."""
    message = (result.message or "").lower()
    args = dict(step.args)
    window = args.get("window") or args.get("window_title") or ""
    if "no window matches" in message and window:
        return [{"tool": "cc_window", "args": {"op": "wait", "window": window, "timeout": 8},
                 "description": f"wait for a window called '{window}'"}]
    if "no control matching" in message and args.get("name") and step.tool == "cc_control":
        retry = {**args, "name_contains": args.get("name"), "name": ""}
        return [{"tool": "cc_window", "args": {"op": "activate", "window": window}, "optional": True,
                 "description": "bring the window forward"},
                {"tool": "cc_control", "args": retry, "description": "retry with a looser name match"}]
    if "is disabled" in message and step.tool == "cc_control" and args.get("name"):
        return [{"tool": "cc_control", "args": {"op": "wait", "window": window, "name": args["name"],
                                                "timeout": 6},
                 "description": f"wait until '{args['name']}' is enabled"},
                {"tool": step.tool, "args": args, "description": "try again"}]
    return []


def _browser_recover(host, step, result) -> list[dict]:
    """No automatic browser retries: after a re-render the same ref can point at a
    different element, so a stale-ref failure goes back to the planner instead of
    clicking blindly. Only a slow page is waited for once."""
    message = (result.message or "").lower()
    if step.tool == "cc_browser" and str(step.args.get("op")) in ("navigate", "search") \
            and ("timeout" in message or "did not respond" in message):
        return [{"tool": "cc_browser", "args": dict(step.args), "description": "try loading the page again"}]
    return []


def default_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(AppAgent("windows", "Windows desktop apps, windows and controls (UI Automation).",
                          frozenset({"cc_app", "cc_window", "cc_control", "cc_pointer"}),
                          recover=_windows_recover))
    reg.register(AppAgent("browser", "Web pages in the installed Edge/Chrome (Playwright).",
                          frozenset({"cc_browser"}), recover=_browser_recover,
                          apps=("msedge", "chrome")))
    reg.register(AppAgent("engine", "Engine status and emergency stop.",
                          frozenset({"cc_engine_status", "cc_emergency_stop"})))
    for extra in _EXTRA_AGENTS:
        reg.register(extra())
    return reg


#: factories added by later projects (browser, visual, workflows)
_EXTRA_AGENTS: list[Callable[[], AppAgent]] = []


def add_agent_factory(factory: Callable[[], AppAgent]) -> None:
    if factory not in _EXTRA_AGENTS:
        _EXTRA_AGENTS.append(factory)
