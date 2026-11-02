"""Which device owns the conversation, and where audio goes.

* Exactly one device streams its microphone at a time: the one the owner
  tapped (the *active* device). Frames from any other device are ignored.
* JARVIS's voice goes to the active device. When nobody is active (a reminder,
  a finished background job), it goes to the most recently active device, or
  the tablet if none has been active yet, or any connected client.
* Tapping another device moves the conversation there: the old device is told
  to stop listening and to flush its speaker queue. The Gemini session is the
  same, so the context carries over.
* ``flush()`` clears the target's playback queue at once (barge-in, stop word).

An *endpoint* is any connection that can play and capture audio: a web client
or the laptop agent's optional local audio (laptop_agent/local_audio.py).
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from hub import protocol

DEFAULT_OUTPUT = "tablet"


class AudioRouter:
    def __init__(self, hub, *, on_mic: Callable[[bytes], None] | None = None,
                 on_control: Callable[[str, dict], Awaitable[None] | None] | None = None):
        self.hub = hub
        self.active: str | None = None          # device streaming the mic now
        self.last_active: str | None = None
        self.listening: set[str] = set()
        self.conversation: dict[str, bool] = {}
        self.buffered_ms: dict[str, float] = {}
        self.on_mic = on_mic                    # (pcm16@16k) -> None, set by hub/live.py
        self.on_control = on_control            # ("text"/"stop"/...) handler
        self.frames_in = 0
        self.frames_out = 0
        self.last_mic_at = 0.0
        hub.clients.on_message.append(self._client_message)
        hub.clients.on_binary.append(self._client_binary)
        hub.clients.on_close.append(self._closed)
        hub.agents.on_binary.append(self._client_binary)
        hub.agents.on_message.append(self._agent_message)
        hub.agents.on_close.append(self._closed)

    # ── endpoints ─────────────────────────────────────────────────────────────
    def endpoint(self, device: str | None):
        if not device:
            return None
        return self.hub.clients.get(device) or (
            self.hub.agents.get(device) if self._agent_has_audio(device) else None)

    def _agent_has_audio(self, device: str) -> bool:
        conn = self.hub.agents.get(device)
        return bool(conn and conn.info.get("local_audio"))

    def output_target(self) -> str | None:
        for name in (self.active, self.last_active, DEFAULT_OUTPUT):
            if name and self.endpoint(name) is not None:
                return name
        devices = self.hub.clients.devices()
        return devices[0] if devices else None

    # ── control ───────────────────────────────────────────────────────────────
    async def activate(self, device: str) -> None:
        previous = self.active
        if previous and previous != device:
            await self._tell(previous, {"type": "listen", "on": False})
            await self._tell(previous, {"type": "flush"})
            self.listening.discard(previous)
        self.active = device
        self.last_active = device
        self.listening.add(device)
        await self.hub.clients.broadcast({"type": "active", "device": device})
        if self.on_control:
            await _maybe_await(self.on_control("activate", {"device": device}))

    async def deactivate(self, device: str) -> None:
        self.listening.discard(device)
        if self.active == device:
            self.active = None
            await self.hub.clients.broadcast({"type": "active", "device": None})
        if self.on_control:
            await _maybe_await(self.on_control("deactivate", {"device": device}))

    async def end_turn(self) -> None:
        """JARVIS finished answering: tap-to-talk devices stop listening."""
        device = self.active
        if device and not self.conversation.get(device):
            self.listening.discard(device)
            await self._tell(device, {"type": "listen", "on": False})

    async def _tell(self, device: str, msg: dict) -> None:
        ep = self.endpoint(device)
        if ep is not None:
            await ep.send(msg)

    # ── audio out ─────────────────────────────────────────────────────────────
    async def send_audio(self, pcm: bytes) -> str | None:
        target = self.output_target()
        ep = self.endpoint(target)
        if ep is None:
            return None
        if await ep.send_bytes(protocol.audio_frame(pcm)):
            self.frames_out += 1
        return target

    async def flush(self) -> None:
        target = self.output_target()
        if target:
            await self._tell(target, {"type": "flush"})
        if self.active and self.active != target:
            await self._tell(self.active, {"type": "flush"})

    # ── inbound ───────────────────────────────────────────────────────────────
    async def _client_binary(self, conn, tag: int, payload: bytes) -> None:
        if tag != protocol.TAG_AUDIO:
            return
        if conn.device != self.active or conn.device not in self.listening:
            return                       # only the active device's microphone counts
        self.frames_in += 1
        self.last_mic_at = time.monotonic()
        if self.on_mic is not None:
            self.on_mic(payload)

    async def _client_message(self, conn, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "activate":
            await self.activate(conn.device)
        elif kind == "deactivate":
            await self.deactivate(conn.device)
        elif kind == "conversation_mode":
            self.conversation[conn.device] = bool(msg.get("on"))
        elif kind == "playback":
            self.buffered_ms[conn.device] = float(msg.get("buffered_ms") or 0.0)
        elif kind in ("stop", "text") and self.on_control:
            if kind == "text" and self.active != conn.device:
                await self.activate(conn.device)
            await _maybe_await(self.on_control(kind, {"device": conn.device, **msg}))

    async def _agent_message(self, conn, msg: dict) -> None:
        # The laptop agent's local audio (wake word) uses the same verbs.
        if msg.get("type") in ("audio_activate", "audio_deactivate", "audio_stop"):
            verb = msg["type"].split("_", 1)[1]
            await self._client_message(conn, {"type": verb, "on": msg.get("on")})

    async def _closed(self, conn) -> None:
        self.listening.discard(conn.device)
        self.buffered_ms.pop(conn.device, None)
        if self.active == conn.device:
            self.active = None
            await self.hub.clients.broadcast({"type": "active", "device": None})
            if self.on_control:
                await _maybe_await(self.on_control("closed", {"device": conn.device}))


async def _maybe_await(value):
    if asyncio.iscoroutine(value):
        return await value
    return value
