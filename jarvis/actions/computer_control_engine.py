"""Computer Control Engine tools (jarvis/computer_control/), registered here.

Every tool is a ``ToolSpec`` converted to the ordinary ``TOOL`` declaration
format, so the action registry, the Tool Catalog, the planner and Gemini Live
see them like any other action. They are hidden (``available`` returns False)
until the owner opts in with ``JARVIS_COMPUTER_CONTROL=1``.
"""
from jarvis.computer_control.tools import build_registry

TOOLS = build_registry().declarations()
