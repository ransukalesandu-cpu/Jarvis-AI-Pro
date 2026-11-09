"""Read-only mirror of the worker-node list for the web page.

Source of truth is :class:`jarvis.core.nodes.registry.NodeRegistry`. Only the node's
configured name, status and coarse load are published: no URL, token, environment
variable name, error text or capability detail reaches page JavaScript.
"""
from __future__ import annotations

from jarvis.core import ui_state


def _row(n: dict) -> tuple:
    def num(v):
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return (str(n["name"])[:32], str(n["status"]), num(n.get("cpu_percent")), num(n.get("ram_available_mb")),
            num(n.get("running_jobs")), num(n.get("queued_jobs")), num(n.get("last_ok")))


class NodesFeed:
    def __init__(self, registry, bus=None):
        self._registry = registry
        self._bus = bus or ui_state.bus()
        self._unsub = registry.add_listener(self.publish)
        self.publish()

    def publish(self) -> None:
        self._bus.set(ui_state.NODES, tuple(_row(n) for n in self._registry.snapshot()[:8]))

    def close(self) -> None:
        self._unsub()
