"""Worker-node settings: environment variables, then defaults. No secrets live here.

    JARVIS_NODE_STATE         state folder (ledger, token hashes, work folders);
                              default <user data>/node — never inside the repository
    JARVIS_NODE_ID            stable node id, lowercase (default "forge")
    JARVIS_NODE_PORT          port (default 8770)
    JARVIS_NODE_BIND          comma-separated addresses; default: loopback only without a
                              certificate, LAN + Tailscale addresses with one
    JARVIS_NODE_CERT / _KEY   TLS certificate and key (e.g. from `tailscale cert`)
    JARVIS_NODE_PUBLIC_HOST   the name the laptop uses, e.g. forge.tail1234.ts.net
                              (accepted in the Host header; DNS-rebinding protection)
    JARVIS_NODE_MAX_PARALLEL  concurrent jobs (default: half the CPU cores, 1..4)

Public addresses are never bound (same rules as the hub, ``hub/netbind.py``), and
without a certificate the node listens on loopback only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.node.protocol import check_node_id


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _default_state_dir() -> Path:
    from jarvis.core.user_data import user_data_dir
    return user_data_dir() / "node"


def _default_parallel() -> int:
    return max(1, min(4, (os.cpu_count() or 2) // 2))


@dataclass
class NodeConfig:
    state_dir: Path = field(default_factory=_default_state_dir)
    node_id: str = "forge"
    port: int = 8770
    bind: list[str] = field(default_factory=list)
    cert: str = ""
    key: str = ""
    public_host: str = ""
    max_parallel: int = field(default_factory=_default_parallel)
    lease_s: float = 15.0

    def __post_init__(self):
        self.state_dir = Path(self.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.node_id = check_node_id(self.node_id)
        if bool(self.cert) != bool(self.key):
            raise ValueError("set both JARVIS_NODE_CERT and JARVIS_NODE_KEY, or neither")

    @property
    def tls(self) -> bool:
        return bool(self.cert and self.key)

    @property
    def tokens_path(self) -> Path:
        return self.state_dir / "tokens.json"

    @property
    def ledger_dir(self) -> Path:
        return self.state_dir / "ledger"

    @property
    def work_dir(self) -> Path:
        return self.state_dir / "work"


def load_config(**overrides) -> NodeConfig:
    data: dict = {}
    for env, key, cast in (("JARVIS_NODE_STATE", "state_dir", str), ("JARVIS_NODE_ID", "node_id", str),
                           ("JARVIS_NODE_PORT", "port", int), ("JARVIS_NODE_CERT", "cert", str),
                           ("JARVIS_NODE_KEY", "key", str), ("JARVIS_NODE_PUBLIC_HOST", "public_host", str),
                           ("JARVIS_NODE_MAX_PARALLEL", "max_parallel", int)):
        value = _env(env)
        if value is not None:
            data[key] = cast(value)
    bind = _env("JARVIS_NODE_BIND")
    if bind:
        data["bind"] = [b.strip() for b in bind.split(",") if b.strip()]
    data.update({k: v for k, v in overrides.items() if v is not None})
    return NodeConfig(**data)
