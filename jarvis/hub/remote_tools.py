"""Tools that run on a device agent (the laptop and, through it, Android).

When the laptop agent connects it announces its tool declarations. This
registry exposes them to Gemini (with the ActionRegistry interface the Phase 1
dispatch already uses) and forwards each call to the agent that owns the
target device:

    device=laptop          -> the agent named "laptop"
    device=tablet / phone  -> the agent in that device's ``adb.via``

An unknown or offline device, or an agent that drops mid-call, gives a sentence
JARVIS can speak. While a call runs the agent may send events — a frame to
show Gemini, a log line, text to speak, or a Gemini request (agents hold no
keys) — which are handled here.
"""
from __future__ import annotations

import asyncio
import base64
import itertools
import threading
import time

from jarvis.core.tool_runtime import ToolMeta, meta_from_declaration

_UI_METHODS = {"write_log", "show_content", "request_say"}


class RemoteCallError(RuntimeError):
    pass


class RemoteToolRegistry:
    def __init__(self, hub):
        self.hub = hub
        self._ids = itertools.count(1)
        self._pending: dict[int, dict] = {}         # id -> {future, device, agent}
        self._tools: dict[str, dict] = {}            # name -> {decl, meta, agents:set}
        self._lock = threading.Lock()
        self.on_tools_changed = None                 # set by hub/live.py
        hub.agents.on_message.append(self._agent_message)
        hub.agents.on_binary.append(self._agent_binary)
        hub.agents.on_open.append(self._agent_open)
        hub.agents.on_close.append(self._agent_close)
        self.file_streams: dict[int, asyncio.Queue] = {}

    # ── ActionRegistry interface ────────────────────────────────────────────
    def get_tool_declarations(self) -> list[dict]:
        with self._lock:
            return [t["decl"] for t in self._tools.values() if t["agents"]]

    def has(self, name: str) -> bool:
        with self._lock:
            return bool(self._tools.get(name, {}).get("agents"))

    def names(self) -> set[str]:
        with self._lock:
            return {n for n, t in self._tools.items() if t["agents"]}

    def meta(self, name: str):
        tool = self._tools.get(name)
        return tool["meta"] if tool else None

    def scheduling(self, name: str):
        return None

    def run(self, name: str, parameters: dict, ctx: dict | None = None) -> str:
        """Called in a worker thread by the Phase 1 dispatch."""
        ctx = ctx or {}
        device = str(ctx.get("device") or "laptop")
        loop = self.hub.loop
        meta = self.meta(name) or ToolMeta()
        try:
            agent = self.agent_for(device)
        except RemoteCallError as exc:
            return str(exc)
        future = asyncio.run_coroutine_threadsafe(
            self.call(agent, name, parameters, device, meta.timeout), loop)
        cancel = ctx.get("cancel_event")
        cancelled = False
        deadline = time.monotonic() + meta.timeout + 5
        while True:
            try:
                return future.result(timeout=0.2)
            except TimeoutError:
                pass                     # still running: check for the stop word below
            except RemoteCallError as exc:
                return str(exc)
            except Exception as exc:
                return f"The {name.replace('_', ' ')} tool failed: {exc}"
            if cancel is not None and cancel.is_set() and not cancelled:
                cancelled = True
                asyncio.run_coroutine_threadsafe(self.cancel_all(agent), loop)
            if time.monotonic() > deadline:
                return f"The {device} did not answer in time."

    # ── routing ─────────────────────────────────────────────────────────────
    def agent_for(self, device: str) -> str:
        dev = self.hub.registry.get(device)
        if dev is None:
            raise RemoteCallError(f"I don't know a device called '{device}'.")
        if dev.kind == "agent":
            agent = dev.name
        elif dev.kind in ("android", "android_companion"):
            agent = str(dev.adb.get("via") or "laptop")
        else:
            raise RemoteCallError(f"The {device} only shows the JARVIS screen; it can't run tools.")
        if self.hub.agents.get(agent) is None:
            if agent == device:
                raise RemoteCallError(f"The {device} is offline right now (is it on and awake?).")
            raise RemoteCallError(f"I can't reach the {device}: the {agent} that controls it is offline.")
        if dev.kind == "android" and not self.hub.registry.online(device, "adb"):
            raise RemoteCallError(f"The {device} is not connected to the {agent} over ADB right now.")
        return agent

    async def call(self, agent: str, name: str, args: dict, device: str, timeout: float) -> str:
        conn = self.hub.agents.get(agent)
        if conn is None:
            raise RemoteCallError(f"The {agent} is offline right now.")
        call_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[call_id] = {"future": future, "agent": agent, "device": device, "tool": name}
        try:
            if not await conn.send({"type": "call", "id": call_id, "tool": name, "args": args,
                                    "device": device, "timeout": timeout}):
                raise RemoteCallError(f"The {agent} disconnected.")
            return await asyncio.wait_for(future, timeout + 5)
        except asyncio.TimeoutError as exc:
            raise RemoteCallError(f"The {device} did not finish {name.replace('_', ' ')} in time.") from exc
        finally:
            self._pending.pop(call_id, None)

    async def cancel_all(self, agent: str) -> None:
        conn = self.hub.agents.get(agent)
        if conn is None:
            return
        for call_id, p in list(self._pending.items()):
            if p["agent"] == agent:
                await conn.send({"type": "cancel", "id": call_id})

    # ── agent connection ────────────────────────────────────────────────────
    async def _agent_open(self, conn) -> None:
        android = []
        for dev in self.hub.registry._devices.values():
            if dev.kind == "android" and str(dev.adb.get("via") or "laptop") == conn.device:
                reverse = dev.adb.get("reverse", [self.hub.config.port] if dev.client else [])
                android.append({"name": dev.name, "serial": dev.adb.get("serial", ""),
                                "address": dev.adb.get("address", ""), "reverse_ports": reverse})
        await conn.send({"type": "android_config", "devices": android})
        self._announce(conn)

    def _announce(self, conn) -> None:
        tools = conn.info.get("tools") or []
        with self._lock:
            for row in tools:
                decl = row.get("declaration") or row
                name = decl.get("name")
                if not name:
                    continue
                entry = self._tools.setdefault(name, {"agents": set()})
                entry["decl"] = decl
                entry["meta"] = meta_from_declaration(row.get("meta") or {})
                entry["agents"].add(conn.device)
        if tools:
            self._changed()

    async def _agent_close(self, conn) -> None:
        with self._lock:
            for entry in self._tools.values():
                entry["agents"].discard(conn.device)
        for call_id, p in list(self._pending.items()):
            if p["agent"] == conn.device and not p["future"].done():
                p["future"].set_exception(RemoteCallError(
                    f"The {conn.device} disconnected while running {p['tool'].replace('_', ' ')}."))
        for name in list(self.hub.registry.names()):
            dev = self.hub.registry.get(name)
            if dev and dev.kind == "android" and str(dev.adb.get("via") or "laptop") == conn.device:
                self.hub.registry.drop(name, "adb")
        self._changed()

    def _changed(self) -> None:
        if self.on_tools_changed is not None:
            try:
                self.on_tools_changed()
            except Exception as exc:
                print(f"[Hub] tools-changed hook failed: {exc}")

    async def _agent_message(self, conn, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "hello":
            self._announce(conn)
        elif kind == "result":
            p = self._pending.get(int(msg.get("id", 0)))
            if p and not p["future"].done():
                p["future"].set_result(str(msg.get("result", "")))
        elif kind == "devices":
            for row in msg.get("android") or []:
                if row.get("online"):
                    self.hub.registry.heartbeat(row["name"], "adb", **{k: v for k, v in row.items()
                                                                       if k in ("serial", "transport")})
                else:
                    self.hub.registry.drop(row["name"], "adb")
        elif kind == "event":
            await self._event(conn, msg)
        elif kind == "gemini":
            asyncio.ensure_future(self._gemini(conn, msg))
        elif kind == "emit":
            from jarvis.core import events
            await asyncio.to_thread(events.emit, str(msg.get("source") or ""), dict(msg.get("payload") or {}))

    async def _agent_binary(self, conn, tag: int, payload: bytes) -> None:
        from jarvis.hub import protocol
        if tag != protocol.TAG_FILE:
            return
        request_id, data = protocol.split_file(payload)
        queue = self.file_streams.get(request_id)
        if queue is not None:
            await queue.put(data)

    async def _event(self, conn, msg: dict) -> None:
        live = self.hub.live
        event = msg.get("event")
        if event == "show_image" and live is not None:
            live._queue_vision(base64.b64decode(msg.get("data", "")), msg.get("mime", "image/jpeg"),
                               msg.get("question", "What do you see?"), msg.get("source", conn.device))
        elif event == "speak" and live is not None:
            live.speak(str(msg.get("text", "")))
        elif event == "ui" and live is not None and msg.get("method") in _UI_METHODS:
            getattr(live.ui, msg["method"])(*msg.get("args", []))
        elif event == "log":
            await self.hub.clients.broadcast({"type": "log", "text": f"[{conn.device}] {msg.get('text', '')}"})

    async def _gemini(self, conn, msg: dict) -> None:
        """An agent tool wants a generation: run it here, where the key is."""
        from jarvis.core import gemini, gemini_wire
        try:
            parts, config = gemini_wire.decode(msg.get("request") or {})
            reply = await asyncio.to_thread(gemini.call, parts, msg.get("tier") or gemini.FAST,
                                            config, int(msg.get("timeout_ms") or 30000))
            text = None if reply is None else (getattr(reply, "text", None) or "")
            await conn.send({"type": "gemini_result", "id": msg.get("id"), "text": text})
        except Exception as exc:
            await conn.send({"type": "gemini_result", "id": msg.get("id"), "text": None,
                             "error": f"{type(exc).__name__}: {exc}"})


class CompositeRegistry:
    """Several registries behind one ActionRegistry interface (first wins)."""

    def __init__(self, registries: list):
        self.registries = registries

    def _owner(self, name: str):
        for reg in self.registries:
            if reg.has(name):
                return reg
        return None

    def get_tool_declarations(self) -> list[dict]:
        seen, out = set(), []
        for reg in self.registries:
            for decl in reg.get_tool_declarations():
                if decl["name"] not in seen:
                    seen.add(decl["name"])
                    out.append(decl)
        return out

    def has(self, name: str) -> bool:
        return self._owner(name) is not None

    def names(self) -> set[str]:
        return set().union(*(reg.names() for reg in self.registries))

    def meta(self, name: str):
        reg = self._owner(name)
        return reg.meta(name) if reg is not None and hasattr(reg, "meta") else None

    def scheduling(self, name: str):
        reg = self._owner(name)
        return reg.scheduling(name) if reg is not None else None

    def run(self, name: str, parameters: dict, ctx: dict | None = None) -> str:
        reg = self._owner(name)
        if reg is None:
            return f"Action '{name}' is not available."
        return reg.run(name, parameters, ctx)
