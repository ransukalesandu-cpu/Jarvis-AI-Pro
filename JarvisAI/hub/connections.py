"""Live WebSocket connections from web clients and device agents.

One connection per device name and role: a newer connection replaces an older
one (the old socket is closed with CLOSE_REPLACED), so a tablet that silently
lost Wi-Fi and reconnected never leaves a ghost behind. Every message counts as
a heartbeat; the hub's sweeper closes sockets that have been silent for three
heartbeat periods (CLOSE_TIMEOUT).
"""
from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core import failsoft
from hub import protocol

Handler = Callable[["Connection", dict], Awaitable[None] | None]
BinaryHandler = Callable[["Connection", int, bytes], Awaitable[None] | None]


@dataclass
class Connection:
    ws: Any
    device: str
    role: str                         # "client" or "agent"
    remote: str = ""
    opened: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    info: dict = field(default_factory=dict)      # hello payload
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, msg: dict) -> bool:
        try:
            async with self._send_lock:
                await self.ws.send_str(protocol.encode(msg))
            return True
        except Exception:
            return False

    async def send_bytes(self, data: bytes) -> bool:
        try:
            async with self._send_lock:
                await self.ws.send_bytes(data)
            return True
        except Exception:
            return False

    async def close(self, code: int, reason: str = "") -> None:
        try:
            await self.ws.close(code=code, message=reason.encode()[:120])
        except Exception:
            failsoft.suppress("hub.connections:close")


class ConnectionSet:
    """All connections of one role, keyed by device name."""

    def __init__(self, role: str, registry, *, on_message: list[Handler] | None = None,
                 on_binary: list[BinaryHandler] | None = None,
                 on_open: list[Callable] | None = None, on_close: list[Callable] | None = None):
        self.role = role
        self.registry = registry
        self.by_device: dict[str, Connection] = {}
        self.on_message: list[Handler] = on_message or []
        self.on_binary: list[BinaryHandler] = on_binary or []
        self.on_open: list[Callable] = on_open or []
        self.on_close: list[Callable] = on_close or []
        self._ids = itertools.count(1)

    def get(self, device: str) -> Connection | None:
        return self.by_device.get(device)

    def devices(self) -> list[str]:
        return sorted(self.by_device)

    async def attach(self, conn: Connection) -> None:
        old = self.by_device.get(conn.device)
        self.by_device[conn.device] = conn
        if old is not None and old is not conn:
            await old.close(protocol.CLOSE_REPLACED, "replaced by a newer connection")
        self.registry.heartbeat(conn.device, self.role)
        for hook in self.on_open:
            await _maybe_await(hook(conn))

    async def detach(self, conn: Connection) -> None:
        if self.by_device.get(conn.device) is conn:
            del self.by_device[conn.device]
            self.registry.drop(conn.device, self.role)
            for hook in self.on_close:
                await _maybe_await(hook(conn))

    async def dispatch_text(self, conn: Connection, msg: dict) -> None:
        conn.last_seen = time.monotonic()
        self.registry.heartbeat(conn.device, self.role)
        if msg.get("type") == "ping":
            await conn.send({"type": "pong", "t": msg.get("t")})
            return
        for handler in list(self.on_message):
            await _maybe_await(handler(conn, msg))

    async def dispatch_binary(self, conn: Connection, data: bytes) -> None:
        conn.last_seen = time.monotonic()
        tag, payload = protocol.split_binary(data)
        for handler in list(self.on_binary):
            await _maybe_await(handler(conn, tag, payload))

    async def broadcast(self, msg: dict, *, exclude: str | None = None) -> None:
        for name, conn in list(self.by_device.items()):
            if name != exclude:
                await conn.send(msg)

    async def close_device(self, device: str, code: int, reason: str) -> bool:
        conn = self.by_device.get(device)
        if conn is None:
            return False
        await conn.close(code, reason)
        await self.detach(conn)
        return True

    async def sweep(self, timeout: float) -> list[str]:
        """Close connections silent for longer than ``timeout``. Returns their names."""
        now = time.monotonic()
        stale = [c for c in self.by_device.values() if now - c.last_seen > timeout]
        for conn in stale:
            await conn.close(protocol.CLOSE_TIMEOUT, "heartbeat timeout")
            await self.detach(conn)
        return [c.device for c in stale]


async def _maybe_await(value):
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value
