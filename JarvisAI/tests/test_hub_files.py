"""Phase 2 Module F: show_file links, range streaming, device binding, revoke."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

JARVIS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for p in (JARVIS_DIR, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import aiohttp  # noqa: E402
from aiohttp.test_utils import TestServer  # noqa: E402

from hub.server import COOKIE  # noqa: E402


class FileAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from hub.config import load_config
        from hub.files import FileLinks, register_file_tools
        from hub.remote_tools import RemoteToolRegistry
        from hub.server import Hub
        from laptop_agent.client import AgentClient
        from laptop_agent.config import AgentConfig
        from laptop_agent.files import FileServer
        from laptop_agent.tool_host import ToolHost

        state = tempfile.mkdtemp()
        with patch.dict("os.environ", {"JARVIS_HUB_STATE": state, "JARVIS_HUB_LIVE": "0"}):
            cfg = load_config(heartbeat_seconds=0.5)
        Path(cfg.devices_path).write_text(json.dumps({"devices": [
            {"name": "laptop", "kind": "agent"},
            {"name": "tablet", "kind": "android", "client": True},
            {"name": "phone", "kind": "android", "client": True}]}))
        self.hub = Hub(cfg)
        self.hub.loop = asyncio.get_running_loop()
        self.hub.router = SimpleNamespace(active="phone", last_active="phone")
        self.hub.remote = RemoteToolRegistry(self.hub)
        self.links = FileLinks(self.hub)
        register_file_tools(self.hub, self.links)
        self.server = TestServer(self.hub.app)
        await self.server.start_server()
        self.base = f"http://127.0.0.1:{self.server.port}"

        token, _ = self.hub.tokens.redeem(self.hub.tokens.create_code("laptop", "agent").code)
        host = ToolHost(None, state_dir=Path(tempfile.mkdtemp()))
        host.load_declarations()
        acfg = AgentConfig(hub_url=f"ws://127.0.0.1:{self.server.port}", token=token,
                           path=Path(tempfile.mkdtemp()) / "a.json")
        self.agent = AgentClient(acfg, host)
        self.agent.file_server = FileServer(self.agent)
        self.agent_task = asyncio.create_task(self.agent.run())
        await self._until(lambda: self.hub.remote.has("files"))

        self.folder = Path(tempfile.mkdtemp())
        self.pdf = self.folder / "invoice-2026-10.pdf"
        self.data = os.urandom(3 * 1024 * 1024 + 123)          # streamed, not buffered
        self.pdf.write_bytes(self.data)
        self.phone_token, _ = self.hub.tokens.redeem(self.hub.tokens.create_code("phone").code)
        self.tablet_token, _ = self.hub.tokens.redeem(self.hub.tokens.create_code("tablet").code)
        self.phone = await self._client(self.phone_token)

    async def asyncTearDown(self):
        from core import gemini
        gemini.set_remote_call(None)
        await self.phone["session"].close()
        self.agent.stop_event.set()
        self.agent_task.cancel()
        await asyncio.gather(self.agent_task, return_exceptions=True)
        await self.server.close()

    async def _until(self, pred, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return True
            await asyncio.sleep(0.05)
        self.fail("condition not reached")

    async def _client(self, token):
        session = aiohttp.ClientSession(cookies={COOKIE: token})
        ws = await session.ws_connect(f"{self.base}/ws/client")
        inbox: list = []

        async def pump():
            async for m in ws:
                if m.type == aiohttp.WSMsgType.TEXT:
                    inbox.append(json.loads(m.data))
        task = asyncio.create_task(pump())
        await self._until(lambda: any(m["type"] == "welcome" for m in inbox))
        return {"session": session, "ws": ws, "inbox": inbox, "task": task}

    async def _tool(self, name, params, device=""):
        return await asyncio.to_thread(self.hub.tools.run, name, params, {"device": device})

    async def test_find_invoice_and_open_it_on_the_phone(self):
        found = await self._tool("search_files", {"query": "invoice*.pdf", "root": str(self.folder)})
        self.assertIn(str(self.pdf), found)
        out = await self._tool("show_file", {"path": str(self.pdf)}, "phone")
        self.assertIn("Opened invoice-2026-10.pdf", out)
        await self._until(lambda: any(m["type"] == "show_file" for m in self.phone["inbox"]))
        msg = [m for m in self.phone["inbox"] if m["type"] == "show_file"][-1]
        self.assertEqual(msg["mime"], "application/pdf")
        async with self.phone["session"].get(self.base + msg["url"]) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(await resp.read(), self.data)
        headers = {"Range": "bytes=1000-1999"}
        async with self.phone["session"].get(self.base + msg["url"], headers=headers) as resp:
            self.assertEqual(resp.status, 206)
            self.assertEqual(resp.headers["Content-Range"], f"bytes 1000-1999/{len(self.data)}")
            self.assertEqual(await resp.read(), self.data[1000:2000])
        async with self.phone["session"].get(self.base + msg["url"] + "?download=1") as resp:
            self.assertIn("attachment", resp.headers["Content-Disposition"])
            await resp.read()

        # The link is bound to the phone: the tablet (or anyone else) is refused.
        async with aiohttp.ClientSession(cookies={COOKIE: self.tablet_token}) as other:
            async with other.get(self.base + msg["url"]) as resp:
                self.assertEqual(resp.status, 403)
        async with aiohttp.ClientSession() as anon:
            async with anon.get(self.base + msg["url"]) as resp:
                self.assertEqual(resp.status, 403)

    async def test_missing_file_and_screenless_device(self):
        self.assertIn("no file", await self._tool("show_file", {"path": str(self.folder / "nope.pdf")}, "phone"))
        self.assertIn("no JARVIS screen", await self._tool("show_file", {"path": str(self.pdf)}, "tablet"))

    async def test_revoked_phone_loses_access_at_once(self):
        await self._tool("show_file", {"path": str(self.pdf)}, "phone")
        await self._until(lambda: any(m["type"] == "show_file" for m in self.phone["inbox"]))
        url = [m for m in self.phone["inbox"] if m["type"] == "show_file"][-1]["url"]
        out = await self._tool("revoke_device", {"name": "phone"})
        self.assertIn("Revoked the phone", out)
        await self._until(lambda: self.phone["ws"].closed)
        async with self.phone["session"].get(self.base + url) as resp:
            self.assertIn(resp.status, (403, 404))
        ws = await self.phone["session"].ws_connect(f"{self.base}/ws/client")
        await ws.receive()
        self.assertEqual(ws.close_code, 4401)
        async with self.phone["session"].get(self.base + "/", allow_redirects=False) as resp:
            self.assertEqual(resp.status, 302)


if __name__ == "__main__":
    unittest.main()
