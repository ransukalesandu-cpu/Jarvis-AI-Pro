#!/usr/bin/env python3
"""Local owner administration for JARVIS Security V2.

PINs and the recovery code are typed here (getpass) and never pass through voice
or any cloud service.

    python scripts/security_owners.py init              first owner (primary administrator)
    python scripts/security_owners.py list
    python scripts/security_owners.py add               add an owner (administrator only)
    python scripts/security_owners.py revoke <owner_id>
    python scripts/security_owners.py promote|demote <owner_id>
    python scripts/security_owners.py change-pin
    python scripts/security_owners.py enroll-voice      record this owner's own voice profile
    python scripts/security_owners.py recover           use the one-time recovery code
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Callable

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from jarvis.core import identity  # noqa: E402
from jarvis.core.owner_registry import OwnerError, OwnerRegistry  # noqa: E402


def _ask_new_pin(ask: Callable[[str], str]) -> str:
    first, second = ask("New PIN/password (4-64 characters): "), ask("Repeat it: ")
    if first != second:
        raise OwnerError("the two entries did not match; nothing was changed")
    return first


def _admin_session(reg: OwnerRegistry, ask: Callable[[str], str], who: str = ""):
    manager = identity.IdentityManager()
    pin = ask("Your PIN/password: ")
    proof = reg.authenticate_pin(pin, who)
    manager.begin_owner_auth()
    if proof is None:
        raise OwnerError("PIN not accepted")
    reg.login(manager, proof)
    reg.confirm_step_up(manager, ask("Confirm your PIN/password again: "))
    return manager


def run(argv: list[str], *, registry: OwnerRegistry | None = None, ask: Callable[[str], str] = getpass.getpass,
        out: Callable[[str], None] = print, record: Callable[[], object] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS owner administration")
    parser.add_argument("command", choices=["init", "list", "add", "revoke", "promote", "demote",
                                            "change-pin", "enroll-voice", "recover"])
    parser.add_argument("owner_id", nargs="?", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--admin", action="store_true", help="make the new owner an administrator")
    args = parser.parse_args(argv)
    reg = registry or OwnerRegistry()
    name = lambda: args.name or input("Display name: ").strip()  # noqa: E731
    try:
        if args.command == "init":
            owner, code = reg.bootstrap_first_owner(name(), _ask_new_pin(ask))
            out(f"Primary administrator created: {owner['display_name']} ({owner['owner_id']})")
            out("RECOVERY CODE (shown once, write it down and keep it offline):")
            out(f"    {code}")
        elif args.command == "list":
            for o in reg.list_owners():
                flags = ("admin " if o["is_admin"] else "") + ("voice " if o["voice_enrolled"] else "")
                out(f"{o['owner_id']}  {o['display_name']}  [{o['status']}] {flags}".rstrip())
        elif args.command == "add":
            manager = _admin_session(reg, ask)
            owner = reg.add_owner(manager, name(), _ask_new_pin(ask), admin=args.admin)
            out(f"Owner added: {owner['display_name']} ({owner['owner_id']})")
        elif args.command in ("revoke", "promote", "demote"):
            if not args.owner_id:
                raise OwnerError("give the owner id (see: list)")
            manager = _admin_session(reg, ask)
            if args.command == "revoke":
                reg.revoke_owner(manager, args.owner_id)
            else:
                reg.set_admin(manager, args.owner_id, args.command == "promote")
            out(f"{args.command} done.")
        elif args.command == "change-pin":
            if not args.owner_id:
                raise OwnerError("give your owner id (see: list)")
            reg.change_pin(args.owner_id, ask("Current PIN/password: "), _ask_new_pin(ask))
            out("PIN changed.")
        elif args.command == "enroll-voice":
            if not args.owner_id:
                raise OwnerError("give your owner id (see: list)")
            if reg.authenticate_pin(ask("Your PIN/password: "), args.owner_id) is None:
                raise OwnerError("PIN not accepted")
            audio = (record or _record_three_samples)()
            reg.enroll_voice(args.owner_id, audio)
            out("Your voice profile was created. The recording was not saved.")
        elif args.command == "recover":
            owner, code = reg.recover_admin(ask("Recovery code: "), _ask_new_pin(ask), owner_id=args.owner_id)
            out(f"Administrator restored: {owner['display_name']}. NEW RECOVERY CODE (the old one no longer works):")
            out(f"    {code}")
    except OwnerError as exc:
        out(f"Not done: {exc}")
        return 2
    return 0


def _record_three_samples():
    import numpy as np
    import sounddevice as sd
    parts = []
    for i in range(1, 4):
        print(f"Sample {i}/3: speak naturally for 3 seconds.")
        rec = sd.rec(3 * 16000, samplerate=16000, channels=1, dtype="float32")
        sd.wait()
        parts.append(rec.reshape(-1))
    return np.concatenate(parts).astype(np.float32)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
