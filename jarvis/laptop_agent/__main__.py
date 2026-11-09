"""``python -m laptop_agent`` — run, pair, or helper commands.

    python -m laptop_agent pair URL        exchange the hub's pairing URL for a token
    python -m laptop_agent                 connect to the hub and run tools
    python -m laptop_agent adb-pair HOST:PORT CODE   pair a phone's wireless debugging
    python -m laptop_agent device-report   Android version, RAM, storage of each device
    python -m laptop_agent install-startup start the agent when Windows starts
    python -m laptop_agent scan            (internal) print tool declarations as JSON
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_JARVIS = Path(__file__).resolve().parent.parent
if str(_JARVIS) not in sys.path:
    sys.path.insert(0, str(_JARVIS))


def cmd_scan() -> int:
    from jarvis.laptop_agent.genai_shim import install
    install()
    from jarvis.laptop_agent.tool_host import scan
    rows = scan()
    print(json.dumps(rows))
    return 0


def cmd_pair(url: str) -> int:
    from jarvis.laptop_agent.config import load_agent_config
    parts = urlparse(url)
    query = parse_qs(parts.query)
    body = json.dumps({"code": query.get("code", [""])[0], "device": query.get("device", [""])[0]}).encode()
    api = f"{parts.scheme}://{parts.netloc}/api/pair"
    req = urllib.request.Request(api, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            reply = json.loads(resp.read())
    except Exception as exc:
        print(f"Pairing failed: {exc}")
        return 1
    if reply.get("role") != "agent":
        print("That code pairs a web client, not an agent. Ask the hub for an agent code.")
        return 1
    cfg = load_agent_config()
    cfg.token = reply["token"]
    cfg.device = reply["device"]
    cfg.hub_url = ("wss" if parts.scheme == "https" else "ws") + "://" + parts.netloc
    cfg.save()
    print(f"Paired as '{cfg.device}'. Settings saved to {cfg.path}")
    return 0


def cmd_adb_pair(address: str, code: str) -> int:
    from jarvis.laptop_agent.devices.android import Adb, AdbError
    adb = Adb()
    try:
        print(adb.run("pair", address, code, timeout=30).strip())
        host = address.rsplit(":", 1)[0]
        print("Now run: adb connect", host + ":<port shown under Wireless debugging>")
        return 0
    except AdbError as exc:
        print(f"adb pair failed: {exc}")
        return 1


def cmd_device_report() -> int:
    from jarvis.laptop_agent.devices.android import Adb, AndroidDevice, AndroidTarget
    adb = Adb()
    for row in adb.devices():
        dev = AndroidDevice(AndroidTarget(name=row["serial"], serial=row["serial"]), adb)
        try:
            print(json.dumps({"serial": row["serial"], **dev.info()}))
        except Exception as exc:
            print(json.dumps({"serial": row["serial"], "error": str(exc)}))
    return 0


def startup_script(exe: Path) -> str:
    """Windows Startup-folder script: run the agent from the repository root."""
    return f'@echo off\r\ncd /d "{_JARVIS.parent}"\r\nstart "" "{exe}" -m jarvis.laptop_agent\r\n'


def cmd_install_startup() -> int:
    if os.name != "nt":
        print("Startup entries are only created on Windows; use your OS's autostart on others.")
        return 1
    folder = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    script = folder / "JARVIS laptop agent.cmd"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    script.write_text(startup_script(exe), encoding="utf-8")
    print(f"Created {script}")
    return 0


def cmd_run() -> int:
    from jarvis.laptop_agent.runner import run_agent
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m laptop_agent")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("pair")
    p.add_argument("url")
    a = sub.add_parser("adb-pair")
    a.add_argument("address")
    a.add_argument("code")
    sub.add_parser("scan")
    sub.add_parser("device-report")
    sub.add_parser("install-startup")
    sub.add_parser("run")
    args = parser.parse_args()
    if args.cmd == "scan":
        return cmd_scan()
    if args.cmd == "pair":
        return cmd_pair(args.url)
    if args.cmd == "adb-pair":
        return cmd_adb_pair(args.address, args.code)
    if args.cmd == "device-report":
        return cmd_device_report()
    if args.cmd == "install-startup":
        return cmd_install_startup()
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
