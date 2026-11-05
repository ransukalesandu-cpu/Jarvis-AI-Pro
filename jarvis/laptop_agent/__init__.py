"""The laptop agent: runs the laptop's tools for the hub.

A small process on the laptop that opens an outbound WebSocket to the hub
(localhost while the hub runs on the laptop, Tailscale once it moves),
authenticates with its device token, announces the tools it can run, and runs
the calls the hub sends. It also drives the tablet and phone over ADB
(laptop_agent/devices/android.py), because the tablet's USB cable is plugged
into the laptop.

The Phase 1 laptop tools run here unchanged: the same actions/ modules,
executed by the same ActionRegistry. Only the callbacks a tool receives
(`player`, `speak`, `show_image`) are forwarded to the hub, and Gemini calls a
tool makes go through the hub, so API keys never leave it.

Run it with ``python -m laptop_agent`` (pair first: ``python -m laptop_agent pair URL``).
"""
