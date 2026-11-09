"""Talk to worker nodes: one private asyncio loop, one MCP session per node, reconnect on failure.

Transport is the existing remote-node path of :mod:`jarvis.core.mcp_client`
(``https`` + a bearer token read from the environment variable named in
``bearer_env``). Every answer is parsed as JSON and validated by the caller with
:mod:`jarvis.node.protocol`; nothing a node says is trusted as-is.
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import AsyncExitStack
from typing import Any

from jarvis.core import failsoft
from jarvis.core.mcp_client import ServerConfig, _open_http, format_result
from jarvis.node import protocol

CONNECT_TIMEOUT = 10.0
CALL_TIMEOUT = 15.0


class NodeUnavailable(RuntimeError):
    """The node could not be reached or did not answer (safe to show)."""


class NodeRefused(RuntimeError):
    """The node answered with a refusal ({"error": ...}); the text is safe to show."""


class NodeClient:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[Any, AsyncExitStack]] = {}

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or not self._loop.is_running():
                loop = asyncio.new_event_loop()
                ready = threading.Event()

                def run():
                    asyncio.set_event_loop(loop)
                    loop.call_soon(ready.set)
                    loop.run_forever()
                threading.Thread(target=run, name="jarvis-node-client", daemon=True).start()
                ready.wait(5)
                self._loop = loop
            return self._loop

    async def _session(self, cfg: ServerConfig):
        cached = self._sessions.get(cfg.name)
        if cached is not None:
            return cached[0]
        from mcp import ClientSession
        stack = AsyncExitStack()
        try:
            read, write = await _open_http(stack, cfg)
            session = await stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(), CONNECT_TIMEOUT)
        except BaseException:
            await _close_quietly(stack)
            raise
        self._sessions[cfg.name] = (session, stack)
        return session

    async def _drop(self, name: str) -> None:
        cached = self._sessions.pop(name, None)
        if cached is not None:
            await _close_quietly(cached[1])

    def call(self, cfg: ServerConfig, tool: str, arguments: dict | None = None,
             timeout: float = CALL_TIMEOUT) -> Any:
        """Call one node tool and return its parsed JSON answer (dict)."""
        async def run():
            try:
                session = await self._session(cfg)
                result = await asyncio.wait_for(session.call_tool(tool, arguments or {}), timeout)
            except BaseException:
                await self._drop(cfg.name)
                raise
            return format_result(result)

        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(run(), loop)
        try:
            text = future.result(timeout + CONNECT_TIMEOUT + 2)
        except FutureTimeout:
            future.cancel()
            raise NodeUnavailable(f"the {cfg.name} node did not answer in time") from None
        except BaseException as exc:
            raise NodeUnavailable(f"the {cfg.name} node is unreachable ({_short(exc)})") from None
        if text.startswith("MCP tool reported an error"):
            raise NodeUnavailable(f"the {cfg.name} node failed to answer {tool}")
        data = protocol.loads(text)
        refusal = protocol.parse_error(data)
        if refusal is not None:
            raise NodeRefused(refusal)
        return data

    def forget(self, name: str) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._drop(name), loop)

    def close(self) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return

        async def close_all():
            for name in list(self._sessions):
                await self._drop(name)
        try:
            asyncio.run_coroutine_threadsafe(close_all(), loop).result(5)
        except Exception:
            failsoft.suppress("core.nodes.client:close")
        loop.call_soon_threadsafe(loop.stop)


async def _close_quietly(stack: AsyncExitStack) -> None:
    try:
        await asyncio.wait_for(stack.aclose(), 5)
    except BaseException:
        failsoft.suppress("core.nodes.client:close_stack")


def _short(exc: BaseException) -> str:
    # Never echo headers or URLs with secrets: the exception *type* is enough here.
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return type(exc).__name__
