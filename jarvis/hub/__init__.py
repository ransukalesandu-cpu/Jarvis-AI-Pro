"""JARVIS hub: one Gemini session, the tool registry and the device network.

The hub is a small asyncio service that can run anywhere — on the laptop today,
later on an always-on host (a cloud VM or a Raspberry Pi). It serves the web
client, accepts paired clients (tablet, phone, a laptop browser) and the laptop
agent over WebSockets, owns the Gemini Live session, and routes every tool call
to the device named in its ``device`` argument.

Nothing in this package assumes Windows or the owner's laptop: settings come
from environment variables or a JSON config file (hub/config.py).

Run it with ``python -m hub`` (see README "Multi-device setup").
"""
