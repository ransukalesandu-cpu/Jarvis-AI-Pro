"""The hub service: HTTP(S) + WebSockets on aiohttp.

aiohttp is already in memory once the Gemini Live client loads, so the web
server adds about 3 MB (measured; see PR). It serves:

    GET  /              the web client (client/ static files)
    GET  /pair          pairing page (one-time code -> device token)
    POST /api/pair      {code, device?} -> {token, device}; sets the cookie
    GET  /health        {"status": "ok", ...}; device detail only when paired
    WS   /ws/client     paired web clients (tablet, phone, laptop browser)
    WS   /ws/agent      paired device agents (the laptop agent)
    GET  /files/{link}  short-lived file links (hub/files.py)

Security: connections from public addresses are dropped before anything else
(hub/netbind.py); every WebSocket must present a valid device token.
"""
from __future__ import annotations

import asyncio
import json
import ssl
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from hub import netbind, protocol
from hub.config import HubConfig
from hub.connections import Connection, ConnectionSet
from hub.devices import DeviceRegistry
from hub.pairing import TokenStore
from hub.tools import HubToolRegistry, register_core_tools

CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"
COOKIE = "jarvis_token"
HELLO_TIMEOUT = 10.0


class Hub:
    def __init__(self, config: HubConfig, *, tokens: TokenStore | None = None,
                 registry: DeviceRegistry | None = None):
        self.config = config
        self.started = time.time()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.tokens = tokens or TokenStore(config.tokens_path, pairing_minutes=config.pairing_minutes)
        self.registry = registry or DeviceRegistry(
            config.load_devices(), offline_after=config.offline_after_seconds,
            on_change=self._devices_changed)
        if registry is not None:
            registry._on_change = self._devices_changed
        self.clients = ConnectionSet("client", self.registry)
        self.agents = ConnectionSet("agent", self.registry)
        self.tools = HubToolRegistry(self)
        register_core_tools(self.tools)
        self.extensions: list = []          # objects with optional start()/stop()
        self.live = None                    # HubJarvisLive when the Gemini session runs
        self.router = None                  # hub.audio_router.AudioRouter
        self.app = self._build_app()
        self._runners: list[web.AppRunner] = []
        self._tasks: list[asyncio.Task] = []
        self.urls: list[str] = []

    # ── app ───────────────────────────────────────────────────────────────────
    def _build_app(self) -> web.Application:
        app = web.Application(middlewares=[self._peer_filter], client_max_size=2 * 1024 * 1024)
        app.router.add_get("/health", self._health)
        app.router.add_get("/pair", self._pair_page)
        app.router.add_post("/api/pair", self._api_pair)
        app.router.add_get("/ws/client", self._ws_client)
        app.router.add_get("/ws/agent", self._ws_agent)
        app.router.add_get("/", self._index)
        # The PWA's manifest and service worker must sit at the root scope.
        app.router.add_get("/manifest.webmanifest", self._root_file("manifest.webmanifest",
                                                                   "application/manifest+json"))
        app.router.add_get("/sw.js", self._root_file("sw.js", "application/javascript"))
        if CLIENT_DIR.exists():
            app.router.add_static("/static/", CLIENT_DIR, show_index=False)
        return app

    @web.middleware
    async def _peer_filter(self, request: web.Request, handler):
        if not netbind.is_allowed_peer(request.remote):
            return web.Response(status=403, text="Not allowed from this network.")
        return await handler(request)

    def token_from_request(self, request: web.Request) -> str | None:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return request.cookies.get(COOKIE)

    def paired_device(self, request: web.Request, role: str = "client"):
        return self.tokens.verify(self.token_from_request(request), role)

    async def _index(self, request: web.Request):
        index = CLIENT_DIR / "index.html"
        if not index.exists():
            return web.Response(text="JARVIS hub is running. The web client is not installed.")
        if self.paired_device(request) is None:
            raise web.HTTPFound("/pair")
        return web.FileResponse(index, headers={"Cache-Control": "no-cache"})

    def _root_file(self, name: str, content_type: str):
        async def handler(_request: web.Request):
            path = CLIENT_DIR / name
            if not path.exists():
                raise web.HTTPNotFound()
            return web.FileResponse(path, headers={"Content-Type": content_type,
                                                   "Cache-Control": "no-cache"})
        return handler

    async def _pair_page(self, request: web.Request):
        page = CLIENT_DIR / "pair.html"
        if page.exists():
            return web.FileResponse(page, headers={"Cache-Control": "no-store"})
        return web.Response(text="Pairing page missing.", status=500)

    async def _api_pair(self, request: web.Request):
        try:
            body = await request.json()
        except (ValueError, json.JSONDecodeError):
            body = {}
        result = self.tokens.redeem(str(body.get("code") or ""), body.get("device"))
        if result is None:
            await asyncio.sleep(0.5)            # slow down guessing
            return web.json_response({"error": "That pairing code is wrong or expired."}, status=403)
        token, info = result
        resp = web.json_response({"token": token, "device": info.device, "role": info.role})
        resp.set_cookie(COOKIE, token, max_age=10 * 365 * 86400, httponly=True,
                        samesite="Strict", secure=request.secure)
        self.log_event(f"Paired {info.device} ({info.role}).")
        return resp

    async def _health(self, request: web.Request):
        body = {"status": "ok", "uptime_s": int(time.time() - self.started),
                "version": protocol.PROTOCOL_VERSION}
        if self.paired_device(request) or self.paired_device(request, "agent"):
            body["devices"] = self.registry.snapshot()
            body["rss_mb"] = _rss_mb()
        return web.json_response(body)

    # ── WebSockets ────────────────────────────────────────────────────────────
    async def _ws_client(self, request: web.Request):
        return await self._serve_ws(request, self.clients, "client")

    async def _ws_agent(self, request: web.Request):
        return await self._serve_ws(request, self.agents, "agent")

    async def _serve_ws(self, request: web.Request, conns: ConnectionSet, role: str):
        ws = web.WebSocketResponse(heartbeat=None, max_msg_size=8 * 1024 * 1024)
        await ws.prepare(request)
        presented = self.token_from_request(request)
        info = self.tokens.verify(presented, role)
        hello: dict = {}
        if info is None and not presented:
            # Browsers cannot set headers on a WebSocket: accept the token in
            # the first message instead (still before anything else happens).
            try:
                first = await asyncio.wait_for(ws.receive(), HELLO_TIMEOUT)
                if first.type == WSMsgType.TEXT:
                    hello = protocol.decode(first.data)
                    info = self.tokens.verify(hello.get("token"), role)
            except (asyncio.TimeoutError, ValueError):
                info = None
        if info is None:
            await ws.close(code=protocol.CLOSE_UNAUTHORIZED, message=b"not paired")
            return ws
        if self.registry.get(info.device) is None:
            await ws.close(code=protocol.CLOSE_REFUSED, message=b"device not in devices.json")
            return ws
        conn = Connection(ws=ws, device=info.device, role=role, remote=str(request.remote))
        conn.info = {k: v for k, v in hello.items() if k != "token"}
        await conns.attach(conn)
        await conn.send({"type": "welcome", "device": conn.device, "role": role,
                         "devices": self.registry.snapshot(),
                         "heartbeat_s": self.config.heartbeat_seconds})
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = protocol.decode(msg.data)
                    except ValueError:
                        continue
                    if data.get("type") == "hello":
                        conn.info.update({k: v for k, v in data.items() if k != "token"})
                    await conns.dispatch_text(conn, data)
                elif msg.type == WSMsgType.BINARY:
                    await conns.dispatch_binary(conn, msg.data)
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            await conns.detach(conn)
        return ws

    # ── device presence ──────────────────────────────────────────────────────
    def _devices_changed(self, old: dict, new: dict) -> None:
        for name in set(old) | set(new):
            before, after = set(old.get(name, ())), set(new.get(name, ()))
            for link in after - before:
                self.log_event(f"{name} connected ({link}).", device=name, event="connect")
            for link in before - after:
                self.log_event(f"{name} disconnected ({link}).", device=name, event="disconnect")
        if self.loop is not None and self.loop.is_running():
            self.loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self.clients.broadcast(
                    {"type": "devices", "devices": self.registry.snapshot()})))

    def log_event(self, text: str, *, device: str = "", event: str = "hub") -> None:
        print(f"[Hub] {text}")
        try:
            from core import action_log
            action_log.record(f"device_{event}", {"device": device} if device else {}, text,
                              status="ok", risk="read", device=device or "hub")
        except Exception as exc:
            print(f"[Hub] action log unavailable: {exc}")

    async def _sweeper(self) -> None:
        stale_after = self.config.heartbeat_seconds * 3
        while True:
            await asyncio.sleep(min(2.0, self.config.heartbeat_seconds / 2))
            await self.clients.sweep(stale_after)
            await self.agents.sweep(stale_after)
            self.registry.sweep()

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def ssl_context(self) -> ssl.SSLContext | None:
        if not (self.config.cert and self.config.key):
            return None
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(self.config.cert, self.config.key)
        return ctx

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        addrs = netbind.bind_addresses(self.config.bind or None)
        runner = web.AppRunner(self.app, access_log=None, shutdown_timeout=3.0)
        await runner.setup()
        self._runners.append(runner)
        for host in addrs["plain"]:
            await web.TCPSite(runner, host, self.config.port).start()
            self.urls.append(f"http://localhost:{self.config.port}")
        tls = self.ssl_context()
        if tls is not None:
            for host in addrs["tls"]:
                try:
                    await web.TCPSite(runner, host, self.config.tls_port, ssl_context=tls).start()
                    shown = f"[{host}]" if ":" in host else host
                    self.urls.append(f"https://{shown}:{self.config.tls_port}")
                except OSError as exc:
                    print(f"[Hub] could not listen on {host}: {exc}")
        elif addrs["tls"]:
            print("[Hub] No TLS certificate configured: only localhost clients can use the "
                  "microphone. See README (tailscale cert).")
        self._tasks.append(asyncio.create_task(self._sweeper()))
        from core import action_log
        action_log.add_listener(self._action_entry)
        for ext in self.extensions:
            starter = getattr(ext, "start", None)
            if starter is not None:
                await starter()

    def _action_entry(self, entry: dict) -> None:
        """Stream every action-log entry to the clients (from any thread)."""
        loop = self.loop
        if loop is None or not loop.is_running():
            return
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(
            self.clients.broadcast({"type": "action", "entry": entry})))

    async def stop(self) -> None:
        from core import action_log
        action_log.remove_listener(self._action_entry)
        for ext in reversed(self.extensions):
            stopper = getattr(ext, "stop", None)
            if stopper is not None:
                await stopper()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        # Close sockets first so clients and agents reconnect at once instead
        # of the server waiting out their idle connections.
        for conns in (self.clients, self.agents):
            for name in list(conns.devices()):
                await conns.close_device(name, 1001, "hub stopping")
        for runner in self._runners:
            await runner.cleanup()

    def pairing_url(self, code: str, device: str) -> str:
        base = self.config.public_url or (self.urls[-1] if self.urls else
                                          f"http://localhost:{self.config.port}")
        return f"{base.rstrip('/')}/pair?device={device}&code={code}"


def _rss_mb() -> float:
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e6, 1)
    except Exception:
        return 0.0
