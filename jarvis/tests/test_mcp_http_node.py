"""Remote device nodes: an MCP server reached over streamable HTTP (real server, loopback)."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.core import mcp_client

SERVER = textwrap.dedent("""
    import sys
    try:
        from mcp.server.mcpserver import MCPServer as S
    except ImportError:
        from mcp.server.fastmcp import FastMCP as S
    port = int(sys.argv[1])
    app = S("node")

    @app.tool()
    def whoami() -> str:
        \"\"\"Name this node.\"\"\"
        return "node-pc2"

    try:
        app.run(transport="streamable-http", host="127.0.0.1", port=port)
    except TypeError:
        app.settings.host, app.settings.port = "127.0.0.1", port
        app.run(transport="streamable-http")
""")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class NodeConfigTests(unittest.TestCase):
    def load(self, servers):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            path.write_text(json.dumps({"servers": servers}))
            return mcp_client.load_config(path)

    def test_url_rules(self):
        ok, bad = self.load({
            "pc2": {"url": "https://pc2.example.com/mcp", "bearer_env": "PC2_TOKEN"},
            "local": {"url": "http://127.0.0.1:9000/mcp"},
            "plain": {"url": "http://pc2.example.com/mcp"},
            "creds": {"url": "https://user:pw@pc2.example.com/mcp"},
            "badenv": {"url": "https://pc2.example.com/mcp", "bearer_env": "bad name"},
            "none": {},
        })
        self.assertEqual(set(ok), {"pc2", "local"})
        self.assertEqual(ok["pc2"].bearer_env, "PC2_TOKEN")
        self.assertEqual(set(bad), {"plain", "creds", "badenv", "none"})


class NodeRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = _free_port()
        script = Path(cls.tmp.name) / "node.py"
        script.write_text(SERVER)
        cls.proc = subprocess.Popen([sys.executable, str(script), str(cls.port)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.3).close()
                break
            except OSError:
                time.sleep(0.25)
        else:
            cls.proc.kill()
            raise unittest.SkipTest("HTTP MCP test server did not start")
        cfg = Path(cls.tmp.name) / "mcp_servers.json"
        cfg.write_text(json.dumps({"servers": {"pc2": {"url": f"http://127.0.0.1:{cls.port}/mcp"}}}))
        cls.manager = mcp_client.McpManager(cfg)

    @classmethod
    def tearDownClass(cls):
        cls.manager.shutdown()
        cls.proc.kill()
        cls.proc.wait(timeout=5)
        cls.tmp.cleanup()

    def test_discovery_and_call_over_http(self):
        tools = self.manager.list_tools("pc2")
        self.assertEqual([t.name for t in tools], ["whoami"])
        self.assertIn("node-pc2", self.manager.call("pc2", "whoami", {}))

    def test_missing_token_variable_is_a_clear_failure(self):
        cfg = Path(self.tmp.name) / "tok.json"
        cfg.write_text(json.dumps({"servers": {"p": {"url": f"http://127.0.0.1:{self.port}/mcp",
                                                       "bearer_env": "JARVIS_TEST_NO_SUCH_TOKEN"}}}))
        manager = mcp_client.McpManager(cfg)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_TEST_NO_SUCH_TOKEN", None)
            with self.assertRaises(mcp_client.McpError):
                manager.connect("p")
        manager.shutdown()


if __name__ == "__main__":
    unittest.main()
