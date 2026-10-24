"""Regression tests for the built-in MCP tool hub."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.mcp_hub import MCPPluginHub, mcp_hub  # noqa: E402


class MCPPluginHubTests(unittest.TestCase):
    def test_builtin_system_tool_is_registered(self):
        schemas = mcp_hub.get_tool_schemas()
        matching = [
            item["function"]
            for item in schemas
            if item.get("function", {}).get("name") == "get_battery_and_system_specs"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["parameters"], {"type": "object", "properties": {}})

    def test_builtin_system_tool_returns_metrics(self):
        result = mcp_hub.execute_tool("get_battery_and_system_specs", {})
        self.assertEqual(
            set(result),
            {"cpu_percent", "ram_percent", "battery"},
        )
        self.assertIsInstance(result["cpu_percent"], (int, float))
        self.assertIsInstance(result["ram_percent"], (int, float))

    def test_custom_tool_registration_and_execution(self):
        hub = MCPPluginHub()
        hub.register_tool(
            name="test_echo",
            description="Echo a value for the regression test.",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            handler=lambda value: {"value": value},
        )
        self.assertEqual(hub.execute_tool("test_echo", {"value": "ok"}), {"value": "ok"})


if __name__ == "__main__":
    unittest.main()
