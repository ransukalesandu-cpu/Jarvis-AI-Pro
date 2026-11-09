"""JARVIS worker node: a headless service for the dedicated always-on device.

The laptop keeps voice, the HUD, approvals and computer control (desktop mode). The
node runs background and (from Phase 3) engineering jobs so the laptop does not have
to. It is an MCP server over streamable HTTP; the laptop reaches it through the
remote-node entry in ``mcp_servers.json`` (``"role": "worker"``).

    python -m jarvis.node serve              run the node
    python -m jarvis.node token laptop       issue a token for a device (printed once)
    python -m jarvis.node rotate laptop      revoke and issue a new one
    python -m jarvis.node revoke laptop      revoke (a lost or retired device)
    python -m jarvis.node list               paired devices

See docs/architecture/MULTI_DEVICE.md.
"""
