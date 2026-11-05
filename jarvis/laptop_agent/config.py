"""Agent settings: <user data>/agent.json, overridable by environment variables.

    JARVIS_AGENT_CONFIG   path of the JSON file (default <user data>/agent.json)
    JARVIS_AGENT_HUB      hub URL, e.g. ws://localhost:8765 or wss://hub.tailnet.ts.net:8766
    JARVIS_AGENT_TOKEN    device token (normally written by `pair`)
    JARVIS_AGENT_DEVICE   this agent's device name (default laptop)

The token is a secret: it lives only in this file (owner-only permissions) or
the environment, never in the repository.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _default_path() -> Path:
    from jarvis.core.user_data import user_data_file
    return user_data_file("agent.json")


@dataclass
class AgentConfig:
    hub_url: str = "ws://localhost:8765"
    token: str = ""
    device: str = "laptop"
    keep_awake: bool = True
    local_audio: bool = False          # laptop mic/speaker + wake word (opt-in)
    relay_port: int = 0                # >0: serve the hub on localhost:PORT (hub moved off the laptop)
    path: Path = field(default_factory=_default_path, repr=False)

    def save(self) -> None:
        data = {k: v for k, v in asdict(self).items() if k != "path"}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, self.path)


def load_agent_config() -> AgentConfig:
    path = Path(os.environ.get("JARVIS_AGENT_CONFIG") or _default_path())
    data: dict = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    cfg = AgentConfig(**{k: v for k, v in data.items() if k in AgentConfig.__dataclass_fields__ and k != "path"})
    cfg.path = path
    for env, key in (("JARVIS_AGENT_HUB", "hub_url"), ("JARVIS_AGENT_TOKEN", "token"),
                     ("JARVIS_AGENT_DEVICE", "device")):
        if os.environ.get(env):
            setattr(cfg, key, os.environ[env].strip())
    return cfg
