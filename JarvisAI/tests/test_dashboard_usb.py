import os
import sys
import time
import socket
import unittest
import urllib.request
import urllib.error
import json
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project roots to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in [str(ROOT_DIR), str(JARVIS_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from fastapi.testclient import TestClient
    import uvicorn
    from dashboard.server import DashboardServer, _select_dashboard_bind_host
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

from services.adb_bridge import (
    find_adb,
    parse_adb_devices,
    select_authorized_device,
    is_reverse_rule_active,
    apply_reverse_forwarding,
    remove_reverse_forwarding,
)


class TestADBBridgeServices(unittest.TestCase):

    def test_parse_adb_devices(self):
        sample_output = """List of devices attached
3a2b1c0d	device
9f8e7d6c	unauthorized
1a2b3c4d	offline
"""
        parsed = parse_adb_devices(sample_output)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0], {"serial": "3a2b1c0d", "status": "device"})
        self.assertEqual(parsed[1], {"serial": "9f8e7d6c", "status": "unauthorized"})
        self.assertEqual(parsed[2], {"serial": "1a2b3c4d", "status": "offline"})

    def test_select_authorized_device(self):
        devices = [
            {"serial": "bad_one", "status": "unauthorized"},
            {"serial": "good_one", "status": "device"},
            {"serial": "offline_one", "status": "offline"},
        ]
        selected = select_authorized_device(devices)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["serial"], "good_one")

        no_good = [
            {"serial": "bad_one", "status": "unauthorized"},
            {"serial": "offline_one", "status": "offline"},
        ]
        self.assertIsNone(select_authorized_device(no_good))

    def test_is_reverse_rule_active(self):
        rule_output = """(remote) tcp:8000 (local) tcp:8000
(remote) tcp:9000 (local) tcp:9000
"""
        self.assertTrue(is_reverse_rule_active(rule_output, 8000))
        self.assertFalse(is_reverse_rule_active(rule_output, 8001))
        self.assertFalse(is_reverse_rule_active("tcp:8000 tcp:8000", 800))

    @patch("subprocess.run")
    def test_apply_reverse_forwarding_success(self, mock_run):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "8000"
        mock_res.stderr = ""
        mock_run.return_value = mock_res

        ok, out = apply_reverse_forwarding("adb", "3a2b1c0d", 8000, 8000)
        self.assertTrue(ok)
        self.assertEqual(out, "8000")
        mock_run.assert_called_once_with(
            ["adb", "-s", "3a2b1c0d", "reverse", "tcp:8000", "tcp:8000"],
            capture_output=True,
            text=True,
            timeout=10,
        )


class TestDashboardServerAndSecurity(unittest.TestCase):
    def test_lan_listener_requires_tls(self):
        self.assertEqual(_select_dashboard_bind_host(False, False), "127.0.0.1")
        self.assertEqual(_select_dashboard_bind_host(True, True), "0.0.0.0")
        with self.assertRaises(RuntimeError):
            _select_dashboard_bind_host(True, False)


    def setUp(self):
        if not _HAS_FASTAPI:
            self.skipTest("fastapi/uvicorn not installed")
        self.dashboard = DashboardServer()
        self.client = TestClient(self.dashboard.app)

    def test_health_endpoint_returns_200(self):
        """Verify GET /health responds with 200 OK and expected JSON without auth."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("service"), "jarvis-dashboard")
        self.assertIn("timestamp", data)

    def test_unauthenticated_protected_api_returns_401(self):
        """Verify protected endpoints require authentication."""
        response = self.client.get("/api/files")
        self.assertEqual(response.status_code, 401)

    def test_csrf_origin_middleware_blocks_unauthorized_external_origins(self):
        """Verify state-changing POST requests from unauthorized external origins are rejected with 403."""
        # Unauthenticated request with bad origin header
        headers = {"Origin": "https://evil-malicious-website.com"}
        response = self.client.post("/api/command", json={"text": "test"}, headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertIn("Forbidden", response.json().get("error", ""))

    def test_real_socket_server_startup_and_health_check(self):
        """Start the actual DashboardServer Uvicorn listener on a real loopback port and verify socket requests."""
        srv = DashboardServer()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            test_port = probe.getsockname()[1]
        server_holder = {}

        def run_srv():
            cfg = uvicorn.Config(srv.app, host="127.0.0.1", port=test_port, log_level="error")
            instance = uvicorn.Server(cfg)
            server_holder["server"] = instance
            instance.run()

        t = threading.Thread(target=run_srv, daemon=True)
        t.start()
        deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline:
                instance = server_holder.get("server")
                if instance is not None and instance.started:
                    break
                if not t.is_alive():
                    self.fail("Uvicorn exited before the health endpoint became available")
                time.sleep(0.05)
            else:
                self.fail("Uvicorn listener did not start within 5 seconds")

            url = f"http://127.0.0.1:{test_port}/health"
            with urllib.request.urlopen(url, timeout=3) as resp:
                self.assertEqual(resp.status, 200)
                body = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(body.get("status"), "ok")
                self.assertEqual(body.get("service"), "jarvis-dashboard")
        finally:
            instance = server_holder.get("server")
            if instance is not None:
                instance.should_exit = True
            t.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
