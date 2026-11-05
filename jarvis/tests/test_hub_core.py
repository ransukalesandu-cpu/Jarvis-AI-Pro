"""Phase 2 Module A: binding rules, pairing tokens, device registry, hub auth."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

JARVIS_DIR = Path(__file__).resolve().parents[1]
if str(JARVIS_DIR) not in sys.path:
    sys.path.insert(0, str(JARVIS_DIR))

from aiohttp import WSMsgType  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from jarvis.hub import netbind, protocol  # noqa: E402
from jarvis.hub.config import load_config  # noqa: E402
from jarvis.hub.devices import DeviceRegistry  # noqa: E402
from jarvis.hub.pairing import TokenStore  # noqa: E402
from jarvis.hub.server import COOKIE, Hub  # noqa: E402

DEVICES = [{"name": "laptop", "kind": "agent"},
           {"name": "tablet", "kind": "android", "client": True},
           {"name": "phone", "kind": "android", "client": True}]


class NetBindTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(netbind.classify("127.0.0.1"), "loopback")
        self.assertEqual(netbind.classify("100.101.102.103"), "tailscale")
        self.assertEqual(netbind.classify("fd7a:115c:a1e0::1"), "tailscale")
        self.assertEqual(netbind.classify("192.168.1.20"), "lan")
        self.assertEqual(netbind.classify("8.8.8.8"), "public")
        self.assertEqual(netbind.classify("0.0.0.0"), "public")

    def test_never_binds_public_or_wildcard(self):
        addrs = netbind.bind_addresses(["0.0.0.0", "8.8.8.8", "192.168.1.5", "100.70.1.2", "::1"])
        self.assertEqual(addrs["plain"], ["127.0.0.1"])
        self.assertEqual(addrs["tls"], ["192.168.1.5", "100.70.1.2"])
        self.assertFalse(netbind.is_allowed_peer("1.1.1.1"))
        self.assertTrue(netbind.is_allowed_peer("100.64.0.7"))


class TokenStoreTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "tokens.json"

    def test_code_works_once_and_token_verifies(self):
        store = TokenStore(self.path)
        code = store.create_code("phone")
        token, info = store.redeem(code.code)
        self.assertEqual(info.device, "phone")
        self.assertIsNone(store.redeem(code.code))               # one use
        self.assertEqual(store.verify(token).device, "phone")
        self.assertIsNone(store.verify(token, "agent"))          # wrong role
        self.assertIsNone(store.verify("guess"))

    def test_expired_or_wrong_device_code_is_refused(self):
        store = TokenStore(self.path, pairing_minutes=0)
        code = store.create_code("phone")
        time.sleep(0.01)
        self.assertIsNone(store.redeem(code.code))
        store = TokenStore(self.path)
        code = store.create_code("phone")
        self.assertIsNone(store.redeem(code.code, device="tablet"))

    def test_only_hashes_are_stored_and_revoke_is_immediate(self):
        store = TokenStore(self.path)
        token, _ = store.redeem(store.create_code("phone").code)
        self.assertNotIn(token, self.path.read_text(encoding="utf-8"))
        reloaded = TokenStore(self.path)
        self.assertEqual(reloaded.verify(token).device, "phone")
        self.assertEqual(reloaded.revoke("phone"), 1)
        self.assertIsNone(reloaded.verify(token))
        self.assertIsNone(TokenStore(self.path).verify(token))


class RegistryTests(unittest.TestCase):
    def test_presence_and_timeout(self):
        changes = []
        reg = DeviceRegistry(DEVICES, offline_after=0.05, on_change=lambda o, n: changes.append(n))
        reg.heartbeat("tablet", "client")
        self.assertTrue(reg.online("tablet"))
        self.assertIn("tablet is online (client)", reg.describe())
        time.sleep(0.08)
        reg.sweep()
        self.assertFalse(reg.online("tablet"))
        self.assertEqual(changes[-1]["tablet"], ())
        with self.assertRaises(ValueError):
            reg.add({"name": "x", "kind": "toaster"})

    def test_companion_kind_is_reserved(self):
        reg = DeviceRegistry([{"name": "phone", "kind": "android_companion"}])
        self.assertEqual(reg.snapshot()[0]["kind"], "android_companion")


class ConfigTests(unittest.TestCase):
    def test_everything_comes_from_env_or_file(self):
        state = tempfile.mkdtemp()
        cfg_file = Path(state) / "hub.json"
        cfg_file.write_text(json.dumps({"port": 9100, "public_url": "https://hub.example.ts.net:9101"}))
        with patch.dict("os.environ", {"JARVIS_HUB_STATE": state, "JARVIS_HUB_CONFIG": str(cfg_file),
                                       "JARVIS_HUB_TLS_PORT": "9101", "JARVIS_HUB_LIVE": "0"}):
            cfg = load_config()
        self.assertEqual((cfg.port, cfg.tls_port, cfg.live), (9100, 9101, False))
        self.assertEqual(cfg.public_url, "https://hub.example.ts.net:9101")
        self.assertTrue((Path(state) / "devices.json").exists() or cfg.load_devices())


class HubServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        state = tempfile.mkdtemp()
        with patch.dict("os.environ", {"JARVIS_HUB_STATE": state, "JARVIS_HUB_LIVE": "0"}):
            self.config = load_config(heartbeat_seconds=0.2, offline_after_seconds=0.6)
        Path(self.config.devices_path).write_text(json.dumps({"devices": DEVICES}))
        self.hub = Hub(self.config)
        self.hub.loop = asyncio.get_running_loop()
        self.client = TestClient(TestServer(self.hub.app))
        await self.client.start_server()
        self.sweeper = asyncio.create_task(self.hub._sweeper())

    async def asyncTearDown(self):
        self.sweeper.cancel()
        await self.client.close()

    def _token(self, device="tablet", role="client"):
        token, _ = self.hub.tokens.redeem(self.hub.tokens.create_code(device, role).code)
        return token

    async def test_unpaired_client_and_agent_are_refused(self):
        for path in ("/ws/client", "/ws/agent"):
            ws = await self.client.ws_connect(path)
            await ws.send_str(json.dumps({"type": "hello", "token": "nope"}))
            msg = await ws.receive()
            self.assertEqual(msg.type, WSMsgType.CLOSE)
            self.assertEqual(ws.close_code, protocol.CLOSE_UNAUTHORIZED)

    async def test_client_token_cannot_connect_as_agent(self):
        token = self._token("laptop", "client")
        ws = await self.client.ws_connect("/ws/agent", headers={"Authorization": f"Bearer {token}"})
        await ws.receive()
        self.assertEqual(ws.close_code, protocol.CLOSE_UNAUTHORIZED)

    async def test_pairing_sets_cookie_and_paired_client_connects(self):
        code = self.hub.tokens.create_code("tablet")
        resp = await self.client.post("/api/pair", json={"code": code.code})
        body = await resp.json()
        self.assertEqual(body["device"], "tablet")
        self.assertIn(COOKIE, resp.cookies)
        ws = await self.client.ws_connect("/ws/client")     # cookie jar carries the token
        welcome = json.loads((await ws.receive()).data)
        self.assertEqual((welcome["type"], welcome["device"]), ("welcome", "tablet"))
        self.assertTrue(self.hub.registry.online("tablet", "client"))
        await ws.close()

    async def test_list_devices_follows_connect_and_disconnect(self):
        token = self._token("phone")
        ws = await self.client.ws_connect("/ws/client")
        await ws.send_str(json.dumps({"type": "hello", "token": token}))
        await ws.receive()
        self.assertIn("phone is online", self.hub.tools.run("list_devices", {}))
        await ws.close()
        await asyncio.sleep(0.05)
        self.assertIn("phone is offline", self.hub.tools.run("list_devices", {}))

    async def test_silent_connection_is_dropped_by_heartbeat_timeout(self):
        token = self._token("phone")
        ws = await self.client.ws_connect("/ws/client")
        await ws.send_str(json.dumps({"type": "hello", "token": token}))
        await ws.receive()
        deadline = time.monotonic() + 3
        while self.hub.registry.online("phone") and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        self.assertFalse(self.hub.registry.online("phone"))

    async def test_health_details_only_for_paired_devices(self):
        body = await (await self.client.get("/health")).json()
        self.assertEqual(body["status"], "ok")
        self.assertNotIn("devices", body)
        token = self._token()
        body = await (await self.client.get("/health", headers={"Authorization": f"Bearer {token}"})).json()
        self.assertIn("devices", body)

    async def test_public_peers_are_refused(self):
        with patch("jarvis.hub.netbind.is_allowed_peer", return_value=False):
            resp = await self.client.get("/health")
        self.assertEqual(resp.status, 403)

    async def test_revoked_device_is_refused(self):
        token = self._token("phone")
        self.hub.tokens.revoke("phone")
        ws = await self.client.ws_connect("/ws/client")
        await ws.send_str(json.dumps({"type": "hello", "token": token}))
        await ws.receive()
        self.assertEqual(ws.close_code, protocol.CLOSE_UNAUTHORIZED)


if __name__ == "__main__":
    unittest.main()
