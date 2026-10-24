"""
Jarvis AI Pro - Model Context Protocol (MCP) Standard Plugin Engine
Enables dynamic tool discovery and execution conforming to the standard MCP schema.
"""

import logging
from typing import Any, Callable, Dict

import psutil

logger = logging.getLogger("Jarvis.MCP")


class MCPPluginHub:
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable,
    ) -> None:
        """Register a tool handler under a schema-compatible tool name."""
        if not name or not callable(handler):
            raise ValueError("A non-empty tool name and callable handler are required.")
        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "handler": handler,
        }
        logger.info("[MCP] Registered capability: %s", name)

    def get_tool_schemas(self):
        """Return JSON schema definitions for function calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in self._tools.values()
        ]

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if tool_name not in self._tools:
            return {"error": f"Tool '{tool_name}' is not recognized."}

        logger.info("[MCP] Executing '%s'", tool_name)
        try:
            handler = self._tools[tool_name]["handler"]
            return handler(**arguments)
        except Exception as exc:
            logger.error("[MCP] Execution failed for '%s': %s", tool_name, exc)
            return {"error": str(exc)}


# Global instance for Jarvis to import.
mcp_hub = MCPPluginHub()


def _get_battery_and_system_specs() -> Dict[str, Any]:
    """Return a small snapshot of live system metrics for the built-in tool."""
    try:
        battery = psutil.sensors_battery()
    except (AttributeError, OSError, RuntimeError):
        battery = None

    return {
        "cpu_percent": psutil.cpu_percent(),
        "ram_percent": psutil.virtual_memory().percent,
        "battery": battery.percent if battery is not None else "No battery/Desktop",
    }


# Register this as an ordinary callable, rather than decorating a function with
# the return value of register_tool (which previously was None and crashed plugin
# discovery with "'NoneType' object is not callable").
mcp_hub.register_tool(
    name="get_battery_and_system_specs",
    description="Returns live battery level, CPU usage %, and RAM metrics.",
    parameters={"type": "object", "properties": {}},
    handler=_get_battery_and_system_specs,
)
