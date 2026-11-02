"""Hub settings: environment variables first, then a JSON file, then defaults.

    JARVIS_HUB_CONFIG     path of a JSON file with any of the keys below
    JARVIS_HUB_STATE      folder for tokens and runtime state (default: user data/hub)
    JARVIS_HUB_DEVICES    path of devices.json (default: <state>/devices.json)
    JARVIS_HUB_PORT       plain-HTTP port, served on localhost only (default 8765)
    JARVIS_HUB_TLS_PORT   HTTPS port for LAN/Tailscale clients (default 8766)
    JARVIS_HUB_BIND       comma-separated addresses to bind instead of auto-detect
    JARVIS_HUB_CERT / JARVIS_HUB_KEY   TLS certificate and key (tailscale cert)
    JARVIS_HUB_PUBLIC_URL how clients reach the hub, e.g. https://hub.tailnet.ts.net:8766
    JARVIS_HUB_LIVE       0 to run without the Gemini session (tests, setup)

The same file runs unchanged on Windows, macOS and Linux (x86 or ARM).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DEVICES = {
    "devices": [
        {"name": "laptop", "kind": "agent", "description": "Main Windows laptop (runs the laptop agent)"},
        {"name": "tablet", "kind": "android", "client": True,
         "adb": {"serial": "usb", "via": "laptop"},
         "description": "Android tablet next to the laptop: main display, USB to the laptop"},
        {"name": "phone", "kind": "android", "client": True,
         "adb": {"address": "", "via": "laptop"},
         "description": "Android phone: wireless debugging when on the same network"},
    ]
}


def _default_state_dir() -> Path:
    try:
        from core.user_data import user_data_dir
        return user_data_dir() / "hub"
    except Exception:
        return Path.home() / ".jarvis-hub"


@dataclass
class HubConfig:
    state_dir: Path = field(default_factory=_default_state_dir)
    devices_path: Path | None = None
    port: int = 8765
    tls_port: int = 8766
    bind: list[str] = field(default_factory=list)      # [] = auto (core of netbind)
    cert: str = ""
    key: str = ""
    public_url: str = ""
    live: bool = True
    heartbeat_seconds: float = 4.0
    offline_after_seconds: float = 10.0
    pairing_minutes: float = 15.0
    file_link_minutes: float = 10.0

    def __post_init__(self):
        self.state_dir = Path(self.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.devices_path is None:
            self.devices_path = self.state_dir / "devices.json"
        self.devices_path = Path(self.devices_path)

    @property
    def tokens_path(self) -> Path:
        return self.state_dir / "tokens.json"

    def load_devices(self) -> list[dict]:
        path = self.devices_path
        if not path.exists():
            path.write_text(json.dumps(DEFAULT_DEVICES, indent=2), encoding="utf-8")
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("devices", []))


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value is not None and value.strip() != "" else None


def load_config(**overrides) -> HubConfig:
    data: dict = {}
    file = _env("JARVIS_HUB_CONFIG")
    if file:
        data.update(json.loads(Path(file).read_text(encoding="utf-8")))
    env_map = {
        "JARVIS_HUB_STATE": ("state_dir", str),
        "JARVIS_HUB_DEVICES": ("devices_path", str),
        "JARVIS_HUB_PORT": ("port", int),
        "JARVIS_HUB_TLS_PORT": ("tls_port", int),
        "JARVIS_HUB_CERT": ("cert", str),
        "JARVIS_HUB_KEY": ("key", str),
        "JARVIS_HUB_PUBLIC_URL": ("public_url", str),
    }
    for env, (key, cast) in env_map.items():
        value = _env(env)
        if value is not None:
            data[key] = cast(value)
    bind = _env("JARVIS_HUB_BIND")
    if bind:
        data["bind"] = [b.strip() for b in bind.split(",") if b.strip()]
    live = _env("JARVIS_HUB_LIVE")
    if live is not None:
        data["live"] = live.lower() not in {"0", "false", "no", "off"}
    data.update({k: v for k, v in overrides.items() if v is not None})
    known = {k: v for k, v in data.items() if k in HubConfig.__dataclass_fields__}
    return HubConfig(**known)
