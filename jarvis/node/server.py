"""The node's MCP endpoint: streamable HTTP, bearer tokens, private addresses only.

Seven tools, each taking and returning one JSON object as text
(see :mod:`jarvis.node.protocol`): ``node_hello``, ``node_health``, ``job_submit``,
``job_status``, ``job_result``, ``job_cancel``, ``job_list``.

Security, outermost first:

1. **Peer filter** — a connection from a public address is refused before anything
   else (``hub/netbind.is_allowed_peer``), whatever the bind address.
2. **Bearer token** — every request must carry ``Authorization: Bearer <token>`` for
   a device paired with the ``controller`` role. Only SHA-256 hashes are stored
   (``hub/pairing.TokenStore``). Repeated failures from one address are throttled.
3. **Host header** — the MCP SDK's DNS-rebinding protection accepts only the bound
   addresses, loopback and ``JARVIS_NODE_PUBLIC_HOST``.
4. **Per-device scoping** — each tool resolves the device from the token again and
   the ledger shows a device only its own jobs.

Tokens never appear in logs: only the device name and the outcome are recorded.
"""

import asyncio
import json
import time
from collections import defaultdict, deque

from jarvis.hub import netbind
from jarvis.hub.pairing import TokenStore
from jarvis.node.config import NodeConfig
from jarvis.node.service import CONTROLLER_ROLE, NodeService

MCP_PATH = "/mcp"
FAIL_WINDOW_S = 60.0
FAIL_LIMIT = 10


class ReloadingTokenStore(TokenStore):
    """A TokenStore that notices `python -m jarvis.node revoke` run in another process.

    Before every check the token file's size and modification time are compared
    with what was loaded; any change reloads it, so a revoked device is refused on
    its very next request without restarting the node.
    """

    def __init__(self, *args, **kwargs):
        self._stamp = None
        super().__init__(*args, **kwargs)
        self._stamp = self._file_stamp()

    def _file_stamp(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def verify(self, token, role=None):
        stamp = self._file_stamp()
        if stamp != self._stamp:
            with self._lock:
                self._tokens = {}
                self._load()
                self._stamp = stamp
        return super().verify(token, role)

    def _save(self) -> None:
        super()._save()
        self._stamp = self._file_stamp()


def make_token_store(config: NodeConfig) -> TokenStore:
    return ReloadingTokenStore(config.tokens_path, roles=(CONTROLLER_ROLE,))


def bearer_from_headers(headers) -> str | None:
    value = ""
    if headers is not None:
        value = headers.get("authorization") or headers.get("Authorization") or ""
    scheme, _, token = str(value).partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


class GuardMiddleware:
    """Pure ASGI wrapper: peer filter, bearer check and failure throttling."""

    def __init__(self, app, tokens: TokenStore, *, log=print):
        self.app = app
        self.tokens = tokens
        self.log = log
        self._fails: dict[str, deque] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            return await _reply(send, 404, {"error": "not found"})
        peer = (scope.get("client") or ("", 0))[0]
        if not netbind.is_allowed_peer(peer):
            return await _reply(send, 403, {"error": "refused"})
        if self._throttled(peer):
            return await _reply(send, 429, {"error": "too many failed attempts; wait a minute"})
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        info = self.tokens.verify(bearer_from_headers(headers), CONTROLLER_ROLE)
        if info is None:
            self._fails[peer].append(time.monotonic())
            self.log(f"[Node] Refused an unauthenticated request from {peer}.")
            return await _reply(send, 401, {"error": "this device is not paired with the node"})
        scope.setdefault("state", {})["jarvis_device"] = info.device
        return await self.app(scope, receive, send)

    def _throttled(self, peer: str) -> bool:
        window = self._fails[peer]
        cutoff = time.monotonic() - FAIL_WINDOW_S
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) >= FAIL_LIMIT


async def _reply(send, status: int, body: dict) -> None:
    data = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode())]})
    await send({"type": "http.response.body", "body": data})


def allowed_hosts(config: NodeConfig, addresses: list[str]) -> list[str]:
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    for addr in addresses:
        hosts.append(f"[{addr}]:*" if ":" in addr else f"{addr}:*")
    if config.public_host:
        hosts.append(f"{config.public_host}:*")
    return hosts


def build_app(service: NodeService, tokens: TokenStore, *, addresses: list[str], log=print):
    """The authenticated ASGI app (MCP SDK 2.x)."""
    from mcp.server.mcpserver import Context, MCPServer
    from mcp.server.transport_security import TransportSecuritySettings

    mcp = MCPServer("jarvis-node", version="1", log_level="WARNING")

    def device_of(ctx: Context) -> str:
        info = tokens.verify(bearer_from_headers(ctx.headers), CONTROLLER_ROLE)
        if info is None:                       # the middleware already refused; belt and braces
            raise PermissionError("not paired")
        return info.device

    def answer(value: dict) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def parse(text: str):
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return None

    @mcp.tool(description="Node identity: protocol version, node id, capabilities and job kinds.")
    def node_hello(ctx: Context) -> str:
        return answer(service.hello(device_of(ctx)))

    @mcp.tool(description="Coarse node health and load.")
    def node_health(ctx: Context) -> str:
        return answer(service.health(device_of(ctx)))

    @mcp.tool(description="Submit a job (JSON job request). Idempotent per idempotency_key.")
    def job_submit(request: str, ctx: Context) -> str:
        return answer(service.submit(device_of(ctx), parse(request)))

    @mcp.tool(description="Status of one of your jobs.")
    def job_status(job_id: str, ctx: Context) -> str:
        return answer(service.status(device_of(ctx), job_id))

    @mcp.tool(description="Status and result of one of your jobs.")
    def job_result(job_id: str, ctx: Context) -> str:
        return answer(service.result(device_of(ctx), job_id))

    @mcp.tool(description="Ask the node to cancel one of your jobs.")
    def job_cancel(job_id: str, ctx: Context) -> str:
        return answer(service.cancel(device_of(ctx), job_id))

    @mcp.tool(description="Your most recent jobs on this node.")
    def job_list(ctx: Context, limit: int = 20) -> str:
        return answer(service.list(device_of(ctx), limit))

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts(service.config, addresses),
        allowed_origins=[],
    )
    app = mcp.streamable_http_app(streamable_http_path=MCP_PATH, stateless_http=True, json_response=True,
                                  transport_security=security, max_request_body_size=256 * 1024)
    return GuardMiddleware(app, tokens, log=log)


def listen_addresses(config: NodeConfig) -> list[str]:
    """Loopback only without TLS; with TLS the private (LAN/Tailscale) addresses. Never public."""
    if not config.tls:
        if any(netbind.classify(a) != "loopback" for a in config.bind if _valid(a)):
            raise ValueError("listening beyond this computer needs JARVIS_NODE_CERT and JARVIS_NODE_KEY")
        return ["127.0.0.1"]
    chosen = netbind.bind_addresses(config.bind or None)["tls"]
    if not chosen:
        raise ValueError("no private (LAN or Tailscale) address to listen on")
    return chosen


def _valid(addr: str) -> bool:
    try:
        netbind.classify(addr)
        return True
    except ValueError:
        return False


async def serve(config: NodeConfig, *, service: NodeService | None = None, log=print) -> None:
    import uvicorn
    service = service or NodeService(config)
    tokens = make_token_store(config)
    addresses = listen_addresses(config)
    app = build_app(service, tokens, addresses=addresses, log=log)
    servers = []
    for index, addr in enumerate(addresses):
        # The SDK's session manager starts in the ASGI lifespan and may start only once:
        # the first server runs it, the others share the same app on the same loop.
        kwargs = dict(host=addr, port=config.port, log_level="warning", access_log=False,
                      server_header=False, proxy_headers=False, lifespan="on" if index == 0 else "off")
        if config.tls:
            kwargs.update(ssl_certfile=config.cert, ssl_keyfile=config.key)
        servers.append(uvicorn.Server(uvicorn.Config(app, **kwargs)))
    scheme = "https" if config.tls else "http"
    for addr in addresses:
        host = f"[{addr}]" if ":" in addr else addr
        log(f"[Node] {config.node_id} listening on {scheme}://{host}:{config.port}{MCP_PATH}")
    try:
        await asyncio.gather(*(s.serve() for s in servers))
    finally:
        service.stop()
