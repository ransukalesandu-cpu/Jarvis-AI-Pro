"""Start the hub: ``python -m hub [--pair NAME[:agent]] [--no-live]``.

On start it prints a pairing URL and QR code for every device in devices.json
that has not been paired yet (and for each ``--pair``). Open the URL on that
device once; it receives its token and connects from then on.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

_JARVIS = Path(__file__).resolve().parent.parent
if str(_JARVIS) not in sys.path:
    sys.path.insert(0, str(_JARVIS))


def print_qr(url: str) -> None:
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception as exc:     # qrcode missing or a console without block glyphs
        print(f"(QR code unavailable: {exc})")


def announce_pairing(hub, device: str, role: str) -> str:
    code = hub.tokens.create_code(device, role)
    url = hub.pairing_url(code.code, device)
    minutes = int(hub.config.pairing_minutes)
    print(f"\n=== Pair '{device}' as {role} (code {code.code}, valid {minutes} min, one use) ===")
    if role == "agent":
        print(f"On {device}:  python -m laptop_agent pair {url}")
    else:
        print(f"Open on {device}: {url}")
        print_qr(url)
    return url


async def amain(args) -> None:
    from hub.config import load_config
    from hub.server import Hub

    config = load_config(live=False if args.no_live else None)
    hub = Hub(config)
    if config.live:
        try:
            from hub.live import attach_live
        except ImportError as exc:
            print(f"[Hub] Gemini session unavailable ({exc}); running devices only.")
        else:
            attach_live(hub)
    await hub.start()
    print("[Hub] Listening on: " + ", ".join(hub.urls))
    paired = hub.tokens.paired_devices()
    requests = [tuple((p.split(":") + ["client"])[:2]) for p in args.pair or []]
    for dev in hub.registry.snapshot():
        roles = paired.get(dev["name"], [])
        if dev["kind"] == "agent" and "agent" not in roles:
            requests.append((dev["name"], "agent"))
        device = hub.registry.get(dev["name"])
        if device and device.client and "client" not in roles:
            requests.append((dev["name"], "client"))
    for name, role in dict.fromkeys(requests):
        announce_pairing(hub, name, role)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass      # Windows: Ctrl+C raises KeyboardInterrupt instead
    try:
        await stop.wait()
    finally:
        await hub.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m hub")
    parser.add_argument("--pair", action="append", metavar="NAME[:agent]",
                        help="print a pairing code for this device (repeatable)")
    parser.add_argument("--no-live", action="store_true",
                        help="run without the Gemini session (setup and tests)")
    args = parser.parse_args()
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
