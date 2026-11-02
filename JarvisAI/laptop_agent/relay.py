"""localhost relay for the USB tablet once the hub has moved off the laptop.

The tablet reaches JARVIS at http://localhost:8765 through `adb reverse`,
which points at the *laptop's* localhost. While the hub runs on the laptop
that is the hub itself. After the hub moves to another host, set
``"relay_port": 8765`` in agent.json: the agent then listens on
127.0.0.1:8765 (localhost only) and forwards each connection to the hub over
Tailscale (TLS when the hub URL is wss://). The tablet keeps using
localhost, so the microphone still works without a certificate on the tablet
side and without Wi-Fi.
"""
from __future__ import annotations

import asyncio
import ssl
from urllib.parse import urlparse


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except ConnectionError as exc:
        print(f"[Relay] connection ended: {exc}")
    finally:
        try:
            writer.close()
        except Exception as exc:
            print(f"[Relay] close: {exc}")


async def start_relay(hub_url: str, port: int, *, host: str = "127.0.0.1") -> asyncio.base_events.Server:
    target = urlparse(hub_url)
    tls = target.scheme in ("wss", "https")
    remote_host = target.hostname or "localhost"
    remote_port = target.port or (443 if tls else 80)
    ctx = ssl.create_default_context() if tls else None

    async def handle(reader, writer):
        try:
            r_reader, r_writer = await asyncio.open_connection(remote_host, remote_port, ssl=ctx,
                                                               server_hostname=remote_host if tls else None)
        except OSError as exc:
            print(f"[Relay] hub unreachable: {exc}")
            writer.close()
            return
        await asyncio.gather(_pipe(reader, r_writer), _pipe(r_reader, writer))

    server = await asyncio.start_server(handle, host, port)
    print(f"[Relay] localhost:{port} -> {remote_host}:{remote_port}{' (TLS)' if tls else ''}")
    return server
