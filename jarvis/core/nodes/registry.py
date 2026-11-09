"""Which worker nodes exist, whether they answer, and what they can do.

Nodes come from ``mcp_servers.json`` entries with ``"role": "worker"``. A small
background thread asks each node for ``node_hello`` (identity, protocol version,
capabilities) and ``node_health`` (coarse load). States:

    unknown       not asked yet
    online        answered, healthy
    degraded      answered, low on disk or memory
    offline       did not answer (heartbeat missed); backs off to save the laptop's resources
    incompatible  answered with another protocol version or a malformed hello
    unconfigured  its bearer_env variable is not set on this computer

Transitions to/from online raise the ``node_online`` / ``node_offline`` hooks. No
node is trusted because it is reachable: every answer is validated, and a node whose
id changes is treated as a different machine (hello is asked again on reconnect).
With no worker configured the thread never starts, so the laptop pays nothing.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from jarvis.core import failsoft
from jarvis.core.mcp_client import ServerConfig, load_config
from jarvis.core.nodes.client import NodeClient, NodeRefused, NodeUnavailable
from jarvis.node import protocol
from jarvis.node.protocol import Health, NodeHello, ProtocolError

POLL_ONLINE_S = 15.0
POLL_OFFLINE_MAX_S = 120.0


@dataclass
class NodeState:
    name: str
    config: ServerConfig
    status: str = "unknown"
    hello: Optional[NodeHello] = None
    health: Optional[Health] = None
    last_ok: float = 0.0             # wall-clock of the last good heartbeat
    last_error: str = ""
    failures: int = 0
    next_poll: float = 0.0           # monotonic

    @property
    def usable(self) -> bool:
        return self.status in ("online", "degraded") and self.hello is not None

    def public(self) -> dict:
        """Plain view for the UI, dashboard and voice. No URL, token or env-var name."""
        h = self.health
        return {
            "name": self.name, "status": self.status,
            "node_id": self.hello.node_id if self.hello else "",
            "software": self.hello.software if self.hello else "",
            "capabilities": list(self.hello.capabilities) if self.hello else [],
            "last_ok": self.last_ok or None, "error": self.last_error,
            "cpu_percent": h.cpu_percent if h else None,
            "ram_available_mb": h.ram_available_mb if h else None,
            "running_jobs": h.running_jobs if h else None,
            "queued_jobs": h.queued_jobs if h else None,
        }


class NodeRegistry:
    def __init__(self, *, client: NodeClient | None = None, config_loader: Callable | None = None,
                 emit: Callable[[str, dict], None] | None = None, clock=time.monotonic):
        self.client = client or NodeClient()
        self._config_loader = config_loader or (lambda: load_config()[0])
        self._emit = emit if emit is not None else _emit_hook
        self._clock = clock
        self._lock = threading.RLock()
        self._nodes: dict[str, NodeState] = {}
        self._listeners: list[Callable[[], None]] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.reload()

    # ── configuration ────────────────────────────────────────────────────────
    def reload(self) -> None:
        try:
            configs = {n: c for n, c in self._config_loader().items() if c.role == "worker" and c.enabled}
        except Exception:
            failsoft.suppress("core.nodes.registry:reload")
            configs = {}
        with self._lock:
            for name in list(self._nodes):
                if name not in configs or configs[name] != self._nodes[name].config:
                    self._nodes.pop(name)
                    self.client.forget(name)
            for name, cfg in configs.items():
                self._nodes.setdefault(name, NodeState(name, cfg))
        self._notify()

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._nodes)

    def get(self, name: str) -> NodeState | None:
        with self._lock:
            return self._nodes.get(name)

    def nodes(self) -> list[NodeState]:
        with self._lock:
            return [self._nodes[n] for n in sorted(self._nodes)]

    def snapshot(self) -> list[dict]:
        return [n.public() for n in self.nodes()]

    def add_listener(self, fn: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(fn)
        return lambda: fn in self._listeners and self._listeners.remove(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                failsoft.suppress("core.nodes.registry:listener")

    # ── heartbeat ────────────────────────────────────────────────────────────
    def poll(self, name: str) -> NodeState | None:
        """Ask one node for hello (when needed) and health; update its state."""
        state = self.get(name)
        if state is None:
            return None
        before = state.status
        cfg = state.config
        if cfg.bearer_env and not os.environ.get(cfg.bearer_env):
            self._set(state, "unconfigured", f"set the {cfg.bearer_env} environment variable on this computer")
        else:
            try:
                if state.hello is None or state.status not in ("online", "degraded"):
                    hello = protocol.parse_hello(self.client.call(cfg, "node_hello"))
                    if hello.role != "worker":
                        raise ProtocolError(f"{name} is not a worker node")
                    if state.hello is not None and state.hello.node_id != hello.node_id:
                        state.health = None          # a different machine answers at this address
                    state.hello = hello
                health = protocol.parse_health(self.client.call(cfg, "node_health"))
                state.health = health
                state.last_ok, state.failures = time.time(), 0
                self._set(state, "degraded" if health.status == "degraded" else "online", "")
            except ProtocolError as exc:
                state.hello = None
                self._set(state, "incompatible", str(exc)[:200])
            except (NodeUnavailable, NodeRefused) as exc:
                state.failures += 1
                self._set(state, "offline", str(exc)[:200])
        delay = POLL_ONLINE_S if state.status in ("online", "degraded") else \
            min(POLL_OFFLINE_MAX_S, POLL_ONLINE_S * (2 ** min(state.failures, 3)))
        state.next_poll = self._clock() + delay
        was_up, is_up = before in ("online", "degraded"), state.status in ("online", "degraded")
        if is_up and not was_up:
            self._emit("node_online", {"node": name})
        elif was_up and not is_up:
            self._emit("node_offline", {"node": name, "reason": state.last_error[:120]})
        self._notify()                      # load numbers change even when the status does not
        return state

    def _set(self, state: NodeState, status: str, error: str) -> None:
        with self._lock:
            state.status, state.last_error = status, error

    def mark_unreachable(self, name: str, error: str) -> None:
        """A job call failed: let the next heartbeat run now instead of waiting."""
        state = self.get(name)
        if state is not None:
            state.next_poll = 0.0
            self._wake.set()

    def poll_due(self) -> None:
        now = self._clock()
        for state in self.nodes():
            if state.next_poll <= now:
                try:
                    self.poll(state.name)
                except Exception:
                    failsoft.suppress("core.nodes.registry:poll")

    def start_background(self) -> bool:
        """Start the heartbeat thread when at least one worker is configured."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            if not self._nodes:
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="jarvis-node-heartbeat", daemon=True)
            self._thread.start()
            return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_due()
            self._wake.wait(1.0)
            self._wake.clear()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self.client.close()


def _emit_hook(event: str, payload: dict) -> None:
    try:
        from jarvis.core import hooks
        hooks.emit(event, payload)
    except Exception:
        failsoft.suppress("core.nodes.registry:emit")


_REGISTRY: NodeRegistry | None = None
_REG_LOCK = threading.Lock()


def get_registry() -> NodeRegistry:
    global _REGISTRY
    with _REG_LOCK:
        if _REGISTRY is None:
            _REGISTRY = NodeRegistry()
        return _REGISTRY


def reset_registry_for_tests(registry: NodeRegistry | None = None) -> None:
    global _REGISTRY
    with _REG_LOCK:
        old, _REGISTRY = _REGISTRY, registry
    if old is not None and old is not registry:
        old.stop()
