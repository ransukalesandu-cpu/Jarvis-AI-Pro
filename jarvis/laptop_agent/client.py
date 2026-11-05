"""The agent's connection to the hub: authenticate, announce, run calls, reconnect.

Outbound only (the laptop opens the connection), so nothing on the laptop has
to accept inbound traffic. Reconnects with exponential backoff (0.5 s .. 15 s).
Each call runs in a worker thread with its own cancel event; results, frames
for Gemini and log lines go back over the same socket in order.
"""
from __future__ import annotations

import asyncio
import base64
import itertools
import json
import random
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from jarvis.hub import protocol

HEARTBEAT = 4.0


class UiProxy:
    """What a Phase 1 tool calls `player`: forwards display calls to the hub."""

    def __init__(self, agent):
        self._agent = agent
        self.muted = False
        self.current_file = None

    def __getattr__(self, name):
        def forward(*args, **_kwargs):
            if name in ("write_log", "show_content", "request_say"):
                self._agent.event({"event": "ui", "method": name,
                                   "args": [str(a)[:2000] for a in args]})
            return None
        return forward

    def hud_video_is_active(self) -> bool:
        return False


class AgentClient:
    def __init__(self, config, host, android_manager=None, local_audio=None):
        self.config = config
        self.host = host                      # ToolHost
        self.android = android_manager
        self.local_audio = local_audio
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ws = None
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="agent-tool")
        self.cancels: dict[int, threading.Event] = {}
        self._gemini_ids = itertools.count(1)
        self._gemini: dict[int, Future] = {}
        self.stop_event = threading.Event()
        self.connected = asyncio.Event()
        self.file_server = None               # set by Module F (laptop_agent/files.py)

    # ── sending (thread-safe) ───────────────────────────────────────────────
    async def _send(self, msg: dict) -> None:
        if self.ws is not None:
            await self.ws.send(protocol.encode(msg))

    def send_threadsafe(self, msg: dict) -> None:
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(self._send(msg), self.loop)

    def send_bytes_threadsafe(self, data: bytes) -> None:
        if self.loop is not None and self.ws is not None:
            asyncio.run_coroutine_threadsafe(self.ws.send(data), self.loop)

    def event(self, payload: dict) -> None:
        self.send_threadsafe({"type": "event", **payload})

    # ── gemini proxy ────────────────────────────────────────────────────────
    def gemini_call(self, contents, tier, config, timeout_ms):
        from jarvis.core import gemini_wire
        if self.loop is None:
            return None
        rid = next(self._gemini_ids)
        fut: Future = Future()
        self._gemini[rid] = fut
        self.send_threadsafe({"type": "gemini", "id": rid, "tier": tier, "timeout_ms": timeout_ms,
                              "request": gemini_wire.encode(contents, config)})
        try:
            return fut.result(timeout=timeout_ms / 1000 + 15)
        except Exception:
            return None
        finally:
            self._gemini.pop(rid, None)

    # ── tool calls ──────────────────────────────────────────────────────────
    def _ctx(self, call_id: int, device: str) -> dict:
        def show_image(data: bytes, mime: str, question: str, source: str):
            self.event({"event": "show_image", "data": base64.b64encode(data).decode("ascii"),
                        "mime": mime, "question": question, "source": source})
        return {"player": UiProxy(self), "speak": lambda text: self.event({"event": "speak", "text": text}),
                "show_image": show_image, "cancel_event": self.cancels[call_id], "device": device,
                "response": None, "session_memory": None}

    def _run_call(self, msg: dict) -> None:
        call_id = int(msg["id"])
        try:
            result = self.host.run(msg["tool"], dict(msg.get("args") or {}),
                                   str(msg.get("device") or "laptop"), self._ctx(call_id, msg.get("device")))
        except Exception as exc:
            result = f"The {str(msg.get('tool', 'tool')).replace('_', ' ')} tool failed on the laptop: {exc}"
        finally:
            self.cancels.pop(call_id, None)
        self.send_threadsafe({"type": "result", "id": call_id, "result": str(result)})

    async def _handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "call":
            self.cancels[int(msg["id"])] = threading.Event()
            self.loop.run_in_executor(self.pool, self._run_call, msg)
        elif kind == "cancel":
            ev = self.cancels.get(int(msg.get("id", 0)))
            if ev is not None:
                ev.set()
        elif kind == "gemini_result":
            fut = self._gemini.get(int(msg.get("id", 0)))
            if fut is not None and not fut.done():
                fut.set_result(msg.get("text"))
        elif kind == "android_config" and self.android is not None:
            self.android.configure(msg.get("devices") or [])
            await self._send({"type": "hello", "tools": self.host.announcement(),
                              "local_audio": bool(self.local_audio)})
        elif kind in ("file_stat", "file_read") and self.file_server is not None:
            self.loop.run_in_executor(self.pool, self.file_server.handle, msg)
        elif kind in ("flush", "listen") and self.local_audio is not None:
            self.local_audio.control(msg)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT)
            msg = {"type": "ping", "t": time.time()}
            if self.android is not None:
                status = await asyncio.to_thread(self.android.poll_status)
                await self._send({"type": "devices", "android": status})
            await self._send(msg)

    async def run(self) -> None:
        from websockets.asyncio.client import connect
        self.loop = asyncio.get_running_loop()
        from jarvis.core import gemini
        gemini.set_remote_call(self.gemini_call)
        backoff = 0.5
        url = self.config.hub_url.rstrip("/") + "/ws/agent"
        while not self.stop_event.is_set():
            try:
                async with connect(url, additional_headers={"Authorization": f"Bearer {self.config.token}"},
                                   max_size=8 * 1024 * 1024, ping_interval=None,
                                   open_timeout=10) as ws:
                    self.ws = ws
                    await self._send({"type": "hello", "device": self.config.device,
                                      "tools": self.host.announcement(),
                                      "local_audio": bool(self.local_audio),
                                      "version": protocol.PROTOCOL_VERSION})
                    beat = asyncio.create_task(self._heartbeat())
                    self.connected.set()
                    backoff = 0.5
                    print(f"[Agent] Connected to {url}")
                    try:
                        async for raw in ws:
                            if isinstance(raw, (bytes, bytearray)):
                                if self.local_audio is not None:
                                    tag, payload = protocol.split_binary(bytes(raw))
                                    if tag == protocol.TAG_AUDIO:
                                        self.local_audio.play(payload)
                                continue
                            await self._handle(json.loads(raw))
                    finally:
                        beat.cancel()
                        self.connected.clear()
                        self.ws = None
                        for ev in list(self.cancels.values()):
                            ev.set()
            except Exception as exc:
                code = getattr(getattr(exc, "rcvd", None), "code", None)
                if code in (protocol.CLOSE_UNAUTHORIZED, protocol.CLOSE_REFUSED):
                    print("[Agent] The hub refused this agent's token. Pair again: "
                          "python -m laptop_agent pair <URL>")
                    return
                print(f"[Agent] Hub unavailable ({type(exc).__name__}: {exc}); retrying in {backoff:.1f}s")
            if self.stop_event.is_set():
                break
            await asyncio.sleep(backoff + random.random() * 0.3)
            backoff = min(backoff * 2, 15.0)
