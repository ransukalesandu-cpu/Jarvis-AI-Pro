"""Worker-node server over real loopback HTTP: auth, revocation, peers, Host header, scoping."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from jarvis.core.mcp_client import ServerConfig
from jarvis.core.nodes.client import NodeClient, NodeRefused, NodeUnavailable
from jarvis.node.__main__ import issue_token
from jarvis.node.config import NodeConfig
from jarvis.node.server import build_app, listen_addresses, make_token_store
from jarvis.node.service import NodeService


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(url: str, token: str | None = None, host: str | None = None) -> int:
    req = urllib.request.Request(url, data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


class NodeServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile

        import uvicorn
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = _free_port()
        cls.config = NodeConfig(state_dir=cls.tmp.name, port=cls.port, lease_s=3, max_parallel=1)
        cls.service = NodeService(cls.config)
        cls.tokens = make_token_store(cls.config)
        cls.laptop_token = issue_token(cls.tokens, "laptop")
        cls.phone_token = issue_token(cls.tokens, "phone")
        cls.logs: list[str] = []
        app = build_app(cls.service, cls.tokens, addresses=["127.0.0.1"], log=cls.logs.append)
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="error",
                                                   lifespan="on", access_log=False))
        cls.thread = threading.Thread(target=lambda: asyncio.run(cls.server.serve()), daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        cls.url = f"http://127.0.0.1:{cls.port}/mcp"
        os.environ["TEST_NODE_LAPTOP"] = cls.laptop_token
        os.environ["TEST_NODE_PHONE"] = cls.phone_token
        cls.client = NodeClient()
        cls.laptop = ServerConfig("forge", "", url=cls.url, bearer_env="TEST_NODE_LAPTOP", role="worker")
        cls.phone = ServerConfig("forge-phone", "", url=cls.url, bearer_env="TEST_NODE_PHONE", role="worker")

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.service.stop()
        cls.tmp.cleanup()

    def test_requests_without_a_valid_token_are_refused(self):
        self.assertEqual(_post(self.url), 401)
        self.assertEqual(_post(self.url, "not-a-token"), 401)
        self.assertTrue(any("unauthenticated" in line for line in self.logs))
        self.assertFalse(any(self.laptop_token in line for line in self.logs))

    def test_public_peer_is_refused_before_auth(self):
        with patch("jarvis.hub.netbind.is_allowed_peer", return_value=False):
            self.assertEqual(_post(self.url, self.laptop_token), 403)

    def test_foreign_host_header_is_refused(self):
        self.assertIn(_post(self.url, self.laptop_token, host=f"evil.example:{self.port}"), (400, 403, 421))

    def test_round_trip_and_device_scoping(self):
        hello = self.client.call(self.laptop, "node_hello")
        self.assertEqual((hello["protocol"], hello["role"], hello["node_id"]), (1, "worker", "forge"))
        health = self.client.call(self.laptop, "node_health")
        self.assertIn(health["status"], ("ok", "degraded"))
        request = json.dumps({"kind": "diag.echo", "capability": "assistant.orchestrate",
                              "idempotency_key": "k-srv00001", "payload": {"text": "hi"}})
        job = self.client.call(self.laptop, "job_submit", {"request": request})
        again = self.client.call(self.laptop, "job_submit", {"request": request})
        self.assertEqual(job["id"], again["id"])
        with self.assertRaises(NodeRefused):            # the phone cannot see the laptop's job
            self.client.call(self.phone, "job_status", {"job_id": job["id"]})
        deadline = time.time() + 20
        view = job
        while time.time() < deadline and view["state"] not in ("succeeded", "failed"):
            time.sleep(0.2)
            view = self.client.call(self.laptop, "job_result", {"job_id": job["id"]})
        self.assertEqual(view["state"], "succeeded")
        self.assertEqual(view["result"]["echo"], "hi")
        self.assertEqual(self.client.call(self.phone, "job_list")["jobs"], [])

    def test_bad_requests_are_refused_with_a_reason(self):
        with self.assertRaises(NodeRefused):
            self.client.call(self.laptop, "job_submit", {"request": "not json"})
        with self.assertRaises(NodeRefused):
            self.client.call(self.laptop, "job_submit", {"request": json.dumps(
                {"kind": "engineering.cad", "capability": "engineering.cadquery", "idempotency_key": "k-cad00001"})})
        with self.assertRaises(NodeRefused):
            self.client.call(self.laptop, "job_status", {"job_id": "../../etc/passwd"})

    def test_revocation_applies_to_the_running_node(self):
        other = make_token_store(self.config)              # as `python -m jarvis.node revoke` would
        token = issue_token(other, "tablet")
        time.sleep(0.05)
        self.assertNotEqual(_post(self.url, token), 401)
        other.revoke("tablet")
        self.assertEqual(_post(self.url, token), 401)


class ListenRulesTests(unittest.TestCase):
    def test_without_tls_only_loopback(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(listen_addresses(NodeConfig(state_dir=tmp)), ["127.0.0.1"])
            with self.assertRaises(ValueError):
                listen_addresses(NodeConfig(state_dir=tmp, bind=["192.168.1.20"]))

    def test_with_tls_never_public(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg = NodeConfig(state_dir=tmp, cert="c.pem", key="k.pem", bind=["8.8.8.8", "100.101.102.103"])
            self.assertEqual(listen_addresses(cfg), ["100.101.102.103"])
            with self.assertRaises(ValueError):
                listen_addresses(NodeConfig(state_dir=tmp, cert="c.pem", key="k.pem", bind=["8.8.8.8"]))
            with self.assertRaises(ValueError):
                NodeConfig(state_dir=tmp, cert="c.pem")      # both or neither


class ClientErrorsTests(unittest.TestCase):
    def test_unreachable_node_is_reported_not_raised_raw(self):
        os.environ["TEST_NODE_DEAD"] = "x" * 20
        client = NodeClient()
        try:
            cfg = ServerConfig("dead", "", url=f"http://127.0.0.1:{_free_port()}/mcp", bearer_env="TEST_NODE_DEAD")
            with self.assertRaises(NodeUnavailable) as ctx:
                client.call(cfg, "node_hello", timeout=3)
            self.assertNotIn("x" * 20, str(ctx.exception))
        finally:
            client.close()
