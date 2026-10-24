"""
Jarvis AI Pro - Model Context Protocol (MCP) Standard Plugin Engine
Enables dynamic tool discovery and execution conforming to the standard MCP schema.
"""

import json
import logging
from typing import Dict, Any, Callable

logger = logging.getLogger("Jarvis.MCP")


class MCPPluginHub:
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, name: str, description: str, parameters: Dict[str, Any], handler: Callable):
        """Registers a tool using standard OpenAI/Claude/MCP schema."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "handler": handler
        }
        logger.info(f"[MCP] Registered capability: {name}")

    def get_tool_schemas(self):
        """Returns JSON schema definitions for function calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"]
                }
            }
            for tool in self._tools.values()
        ]

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if tool_name not in self._tools:
            return {"error": f"Tool '{tool_name}' is not recognized."}

        logger.info(f"[MCP] Executing '{tool_name}' with {arguments}")
        try:
            handler = self._tools[tool_name]["handler"]
            return handler(**arguments)
        except Exception as e:
            logger.error(f"[MCP] Execution failed: {e}")
            return {"error": str(e)}


# Global instance for Jarvis to import
mcp_hub = MCPPluginHub()

# Default built-in system tools
@mcp_hub.register_tool(
    name="get_battery_and_system_specs",
    description="Returns live battery level, CPU usage %, and RAM metrics.",
    parameters={"type": "object", "properties": {}},
    handler=lambda: {
        "cpu_percent": psutil.cpu_percent(),
        "ram_percent": psutil.virtual_memory().percent,
        "battery": psutil.sensors_battery().percent if psutil.sensors_battery() else "No battery/Desktop"
    }
)
def _noop():
    pass
