"""Phase 2 Module E: reconnects, relay, keep-awake, connect/disconnect logging."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

JARVIS_DIR = Path(__file__).resolve().parents[1]
if str(JARVIS_DIR) not in sys.path:
    sys.path.insert(0, str(JARVIS_DIR))

import aiohttp  # noqa: E402

from hub.config import load_config  # noqa: E402
from hub.server import Hub  # noqa: E402

DEVICES = [{"name": "laptop", "kind": "agent"},
           {"name": "tablet", "kind": "android", "client": True}]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _hub(state: str, port: int) -> Hub:
    with patch.dict("os.environ", {"JARVIS_HUB_STATE": state, "JARVIS_HUB_LIVE": "0"}):
        cfg = load_config(port=port, bind=["127.0.0.1"], heartbeat_seconds=0.5)
    Path(cfg.devices_path).write_text(json.dumps({"devices": DEVICES}))
    return Hub(cfg)


async def _until(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(0.05)
    return False


class ReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_reconnects_after_the_hub_restarts(self):
        from laptop_agent.client import AgentClient
        from laptop_agent.config import AgentConfig
        state, port = tempfile.mkdtemp(), _free_port()
        hub = _hub(state, port)
        await hub.start()
        token, _ = hub.tokens.redeem(hub.tokens.create_code("laptop", "agent").code)

        class Host:
            def announcement(self):
                return []

        agent = AgentClient(AgentConfig(hub_url=f"ws://127.0.0.1:{port}", token=token,
                                        path=Path(tempfile.mkdtemp()) / "a.json"), Host())
        task = asyncio.create_task(agent.run())
        try:
            self.assertTrue(await _until(lambda: hub.registry.online("laptop", "agent")))
            await hub.stop()
            self.assertTrue(await _until(lambda: not agent.connected.is_set()))
            hub2 = _hub(state, port)                     # same state: the token is still valid
            await hub2.start()
            started = time.monotonic()
            self.assertTrue(await _until(lambda: hub2.registry.online("laptop", "agent"), 20))
            print(f"\n[reliability] agent back {time.monotonic() - started:.1f}s after the hub restarted")
            await hub2.stop()
        finally:
            agent.stop_event.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            from core import gemini
            gemini.set_remote_call(None)

    async def test_connects_and_disconnects_reach_the_action_log(self):
        state, port = tempfile.mkdtemp(), _free_port()
        hub = _hub(state, port)
        log = Path(state) / "actions.jsonl"
        with patch("core.action_log.log_path", return_value=log):
            await hub.start()
            token, _ = hub.tokens.redeem(hub.tokens.create_code("tablet").code)
            async with aiohttp.ClientSession() as s:
                ws = await s.ws_connect(f"http://127.0.0.1:{port}/ws/client")
                await ws.send_str(json.dumps({"type": "hello", "token": token}))
                await ws.receive()
                await ws.close()
            await asyncio.sleep(0.1)
            await hub.stop()
        tools = [json.loads(x)["tool"] for x in log.read_text().splitlines()]
        self.assertIn("device_connect", tools)
        self.assertIn("device_disconnect", tools)


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_localhost_relay_reaches_a_remote_hub(self):
        from laptop_agent.relay import start_relay
        state, port = tempfile.mkdtemp(), _free_port()
        hub = _hub(state, port)
        await hub.start()
        relay_port = _free_port()
        relay = await start_relay(f"ws://127.0.0.1:{port}", relay_port)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"http://127.0.0.1:{relay_port}/health") as resp:
                    body = await resp.json()
            self.assertEqual(body["status"], "ok")
        finally:
            relay.close()
            await hub.stop()


class KeepAwakeTests(unittest.TestCase):
    def test_noop_off_windows_and_release_is_safe(self):
        from laptop_agent.keep_awake import keep_awake
        req = keep_awake()
        self.assertEqual(req.active, os.name == "nt")
        req.release()
        self.assertFalse(req.active)


if __name__ == "__main__":
    unittest.main()
