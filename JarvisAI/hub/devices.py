"""Device registry: who exists (devices.json) and who is online (heartbeats).

Each entry in devices.json::

    {"name": "tablet", "kind": "android", "client": true,
     "adb": {"serial": "usb", "via": "laptop"}}

kind
    ``agent``            runs the laptop agent (tools execute there)
    ``android``          controlled over ADB by the agent named in ``adb.via``
    ``web``              only a browser client (e.g. a laptop browser window)
    ``android_companion`` reserved for the Phase 3 phone app

``client: true`` means the device also opens the web client (display, mic,
speaker). A device can be online in up to three ways at once — as a web
client, as an agent, and as an ADB target — and each is tracked separately.
A way counts as online while its last heartbeat is newer than
``offline_after`` seconds.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

KINDS = ("agent", "android", "web", "android_companion")
LINKS = ("client", "agent", "adb")


@dataclass
class Device:
    name: str
    kind: str
    client: bool = False
    adb: dict = field(default_factory=dict)
    description: str = ""
    seen: dict = field(default_factory=dict)        # link -> last heartbeat (monotonic)
    detail: dict = field(default_factory=dict)      # link -> extra info (e.g. adb state)

    def online_links(self, now: float, offline_after: float) -> list[str]:
        return [link for link, at in self.seen.items() if now - at <= offline_after]


class DeviceRegistry:
    def __init__(self, entries: list[dict], *, offline_after: float = 10.0,
                 on_change=None):
        self.offline_after = offline_after
        self._lock = threading.RLock()
        self._devices: dict[str, Device] = {}
        self._on_change = on_change
        self._last_state: dict[str, tuple] = {}
        for row in entries:
            self.add(row)

    def add(self, row: dict) -> Device:
        name = str(row.get("name") or "").strip().lower()
        kind = str(row.get("kind") or "web").strip().lower()
        if not name:
            raise ValueError("a device needs a name")
        if kind not in KINDS:
            raise ValueError(f"unknown device kind '{kind}'")
        dev = Device(name=name, kind=kind, client=bool(row.get("client", kind == "web")),
                     adb=dict(row.get("adb") or {}), description=str(row.get("description") or ""))
        with self._lock:
            self._devices[name] = dev
        return dev

    def get(self, name: str) -> Device | None:
        return self._devices.get(str(name or "").strip().lower())

    def names(self) -> list[str]:
        return sorted(self._devices)

    def heartbeat(self, name: str, link: str, **detail) -> None:
        dev = self.get(name)
        if dev is None:
            return
        with self._lock:
            dev.seen[link] = time.monotonic()
            if detail:
                dev.detail[link] = detail
        self._notify_if_changed()

    def drop(self, name: str, link: str) -> None:
        dev = self.get(name)
        if dev is None:
            return
        with self._lock:
            dev.seen.pop(link, None)
            dev.detail.pop(link, None)
        self._notify_if_changed()

    def online(self, name: str, link: str | None = None) -> bool:
        dev = self.get(name)
        if dev is None:
            return False
        links = dev.online_links(time.monotonic(), self.offline_after)
        return bool(links) if link is None else link in links

    def snapshot(self) -> list[dict]:
        now = time.monotonic()
        out = []
        with self._lock:
            for dev in sorted(self._devices.values(), key=lambda d: d.name):
                links = dev.online_links(now, self.offline_after)
                out.append({"name": dev.name, "kind": dev.kind, "online": bool(links),
                            "links": sorted(links), "description": dev.description})
        return out

    def describe(self) -> str:
        rows = self.snapshot()
        parts = []
        for r in rows:
            if r["online"]:
                parts.append(f"{r['name']} is online ({', '.join(r['links'])})")
            else:
                parts.append(f"{r['name']} is offline")
        return "; ".join(parts) + "."

    def sweep(self) -> None:
        """Called periodically: fire on_change when a device timed out."""
        self._notify_if_changed()

    def _notify_if_changed(self) -> None:
        state = {r["name"]: tuple(r["links"]) for r in self.snapshot()}
        if state != self._last_state:
            old, self._last_state = self._last_state, state
            if self._on_change is not None:
                try:
                    self._on_change(old, state)
                except Exception as exc:
                    print(f"[Devices] change hook failed: {exc}")
