"""show_file: a laptop file, viewed on another device, through the hub.

1. ``show_file(device, path)`` asks the laptop agent for the file's details.
2. The hub makes a short-lived link (default 10 minutes) bound to the device
   that should open it, and tells that device's client to open it.
3. ``GET /files/<link>`` checks that the request comes from that same paired
   device (its token cookie), then streams the bytes from the agent, with
   HTTP Range support so video seeks and large files never sit on the phone.

Nothing goes to a third-party cloud; the hub stores nothing.
"""
from __future__ import annotations

import asyncio
import itertools
import re
import secrets
import time
from dataclasses import dataclass

from aiohttp import web

_RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


@dataclass
class FileLink:
    device: str
    agent: str
    path: str
    name: str
    size: int
    mime: str
    expires: float


class FileLinks:
    def __init__(self, hub):
        self.hub = hub
        self.links: dict[str, FileLink] = {}
        self._ids = itertools.count(1)
        self._info: dict[int, asyncio.Future] = {}
        hub.app.router.add_get("/files/{link}", self.serve)
        hub.agents.on_message.append(self._agent_message)

    # ── agent replies ───────────────────────────────────────────────────────
    async def _agent_message(self, conn, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "file_info":
            fut = self._info.get(int(msg.get("id", 0)))
            if fut is not None and not fut.done():
                fut.set_result(msg)
        elif kind == "file_end":
            queue = self.hub.remote.file_streams.get(int(msg.get("id", 0)))
            if queue is not None:
                await queue.put(msg)

    async def stat(self, agent: str, path: str) -> dict:
        conn = self.hub.agents.get(agent)
        if conn is None:
            raise RuntimeError(f"The {agent} is offline right now (is it on and awake?).")
        rid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._info[rid] = fut
        try:
            await conn.send({"type": "file_stat", "id": rid, "path": path})
            return await asyncio.wait_for(fut, 15)
        finally:
            self._info.pop(rid, None)

    # ── links ───────────────────────────────────────────────────────────────
    def create(self, device: str, agent: str, info: dict) -> str:
        self._prune()
        link = secrets.token_urlsafe(18)
        self.links[link] = FileLink(device=device, agent=agent, path=info["path"], name=info["name"],
                                    size=int(info["size"]), mime=info["mime"],
                                    expires=time.time() + self.hub.config.file_link_minutes * 60)
        return link

    def revoke_device(self, device: str) -> None:
        for key in [k for k, v in self.links.items() if v.device == device]:
            del self.links[key]

    def _prune(self) -> None:
        now = time.time()
        for key in [k for k, v in self.links.items() if v.expires < now]:
            del self.links[key]

    async def serve(self, request: web.Request):
        link = self.links.get(request.match_info["link"])
        info = self.hub.paired_device(request)
        if link is None or link.expires < time.time():
            raise web.HTTPNotFound(text="This file link has expired. Ask JARVIS to show it again.")
        if info is None or info.device != link.device:
            raise web.HTTPForbidden(text="This link belongs to another device.")
        start, end = 0, link.size - 1
        status = 200
        rng = request.headers.get("Range", "")
        m = _RANGE.match(rng.strip()) if rng else None
        if m and link.size:
            a, b = m.groups()
            if a == "" and b:
                start = max(0, link.size - int(b))
            else:
                start = int(a or 0)
                end = min(int(b), link.size - 1) if b else link.size - 1
            if start > end or start >= link.size:
                raise web.HTTPRequestRangeNotSatisfiable(headers={"Content-Range": f"bytes */{link.size}"})
            status = 206
        length = end - start + 1 if link.size else 0
        disposition = "attachment" if request.query.get("download") else "inline"
        headers = {"Content-Type": link.mime, "Accept-Ranges": "bytes", "Content-Length": str(length),
                   "Cache-Control": "no-store",
                   "Content-Disposition": f'{disposition}; filename="{link.name}"'}
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{link.size}"
        resp = web.StreamResponse(status=status, headers=headers)
        await resp.prepare(request)
        if length:
            await self._stream(link, start, length, resp)
        await resp.write_eof()
        return resp

    async def _stream(self, link: FileLink, offset: int, length: int, resp) -> None:
        conn = self.hub.agents.get(link.agent)
        if conn is None:
            return
        rid = next(self._ids) + 1_000_000
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self.hub.remote.file_streams[rid] = queue
        try:
            await conn.send({"type": "file_read", "id": rid, "path": link.path,
                             "offset": offset, "length": length})
            while True:
                item = await asyncio.wait_for(queue.get(), 30)
                if isinstance(item, dict):            # file_end
                    break
                await resp.write(item)
        except (asyncio.TimeoutError, ConnectionResetError):
            pass
        finally:
            self.hub.remote.file_streams.pop(rid, None)


def register_file_tools(hub, links: FileLinks) -> None:
    from jarvis.core.tool_runtime import ToolMeta
    tools = hub.tools

    def show_file(params, ctx):
        device = str(ctx.get("device") or "").strip().lower()
        if not device or device == "laptop":
            device = (hub.router.active or hub.router.last_active) if hub.router else ""
        path = str(params.get("path") or "").strip()
        source = str(params.get("source") or "laptop").strip().lower()
        if not path:
            return "Which file? Search for it first."
        if hub.clients.get(device) is None:
            return f"The {device or 'requesting device'} has no JARVIS screen open right now."
        try:
            info = tools.run_on_loop(links.stat(source, path), 20)
        except Exception as exc:
            return str(exc)
        if not info.get("exists"):
            return f"There is no file {path} on the {source}."
        link = links.create(device, source, info)
        url = f"/files/{link}"
        tools.run_on_loop(hub.clients.get(device).send({
            "type": "show_file", "url": url, "name": info["name"], "mime": info["mime"],
            "size": info["size"]}))
        size_mb = info["size"] / 1e6
        return f"Opened {info['name']} ({size_mb:.1f} MB) on the {device}. The link works for {int(hub.config.file_link_minutes)} minutes."

    def search_files(params, ctx):
        args = {"action": "search", "pattern": str(params.get("query") or params.get("pattern") or ""),
                "root": str(params.get("root") or ""), "contains": str(params.get("contains") or ""),
                "max_results": int(params.get("max_results") or 15)}
        return hub.remote.run("files", args, {"device": "laptop", "cancel_event": ctx.get("cancel_event")})

    def revoke_device(params, ctx):
        name = str(params.get("name") or ctx.get("device") or "").strip().lower()
        if not name or hub.registry.get(name) is None:
            return f"I don't know a device called '{name}'."
        removed = hub.tokens.revoke(name)
        links.revoke_device(name)
        for conns in (hub.clients, hub.agents):
            tools.run_on_loop(conns.close_device(name, 4403, "revoked"))
        hub.log_event(f"Revoked {name} ({removed} token(s)).", device=name, event="revoked")
        return (f"Revoked the {name}: it is disconnected and can no longer reach JARVIS. "
                "Pair it again to use it.")

    tools.register({
        "name": "show_file",
        "description": ("Open a laptop file on a device's JARVIS screen (device = phone, tablet...; "
                        "default: the device the owner is using). path = full path, e.g. from "
                        "search_files. Images, PDFs, video and text preview; others download."),
        "parameters": {"type": "OBJECT", "properties": {"path": {"type": "STRING"},
                                                        "source": {"type": "STRING"}}, "required": ["path"]},
    }, show_file, ToolMeta(risk="read", timeout=30))
    tools.register({
        "name": "search_files",
        "description": ("Find files on the laptop by name or glob (query), optionally containing text, "
                        "under a folder (root) or 'all' drives. Returns full paths."),
        "parameters": {"type": "OBJECT", "properties": {
            "query": {"type": "STRING"}, "root": {"type": "STRING"}, "contains": {"type": "STRING"},
            "max_results": {"type": "INTEGER"}}, "required": ["query"]},
    }, search_files, ToolMeta(risk="read", timeout=60))
    tools.register({
        "name": "revoke_device",
        "description": ("Immediately cut off a device (e.g. a lost phone): its token stops working, "
                        "it is disconnected, and its file links die."),
        "parameters": {"type": "OBJECT", "properties": {"name": {"type": "STRING"}}, "required": ["name"]},
    }, revoke_device, ToolMeta(risk="destructive", timeout=15))
