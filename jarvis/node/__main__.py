"""Command line for the worker node (see jarvis/node/__init__.py)."""
from __future__ import annotations

import argparse
import asyncio
import re
import sys

_DEVICE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def _device(value: str) -> str:
    value = value.strip().lower()
    if not _DEVICE_RE.match(value):
        raise argparse.ArgumentTypeError("device names are lowercase letters, digits or '-' (max 32)")
    return value


def issue_token(tokens, device: str) -> str:
    from jarvis.node.service import CONTROLLER_ROLE
    code = tokens.create_code(device, CONTROLLER_ROLE)
    token, _info = tokens.redeem(code.code, device)
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jarvis.node", description="JARVIS worker node")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the node")
    for name, text in (("token", "issue a token for a device"), ("rotate", "revoke, then issue a new token"),
                       ("revoke", "revoke every token of a device")):
        sub.add_parser(name, help=text).add_argument("device", type=_device)
    sub.add_parser("list", help="paired devices")
    args = parser.parse_args(argv)

    from jarvis.node.config import load_config
    from jarvis.node.server import make_token_store
    config = load_config()
    tokens = make_token_store(config)

    if args.command == "serve":
        from jarvis.node.server import serve
        try:
            asyncio.run(serve(config))
        except KeyboardInterrupt:
            pass
        return 0
    if args.command == "list":
        devices = tokens.paired_devices()
        print("\n".join(f"{d}: {', '.join(r)}" for d, r in sorted(devices.items())) or "No paired devices.")
        return 0
    if args.command in ("revoke", "rotate"):
        removed = tokens.revoke(args.device)
        print(f"Revoked {removed} token(s) for {args.device}. A running node refuses them from the next request.")
        if args.command == "revoke":
            return 0
    token = issue_token(tokens, args.device)
    # Shown once, on the owner's own terminal; the node keeps only its SHA-256 hash.
    print(f"Token for {args.device} (shown once; the node stores only a hash):\n\n    {token}\n")
    print("On that device, store it in a user environment variable, for example on Windows:\n"
          "    setx JARVIS_NODE_TOKEN \"<token>\"\n"
          "and name that variable in mcp_servers.json as \"bearer_env\". Never paste it into chat or a file in the repo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
