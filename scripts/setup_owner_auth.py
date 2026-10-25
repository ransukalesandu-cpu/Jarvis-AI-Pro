#!/usr/bin/env python3
"""Local first-run setup for JARVIS owner PIN. No PIN is saved in plaintext."""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for item in (ROOT_DIR, JARVIS_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from security.auth_manager import AuthManager


def main() -> int:
    parser = argparse.ArgumentParser(description="Enroll the local JARVIS owner PIN/password.")
    parser.add_argument("--voice", action="store_true", help="Also enroll an owner voice profile (requires optional Voice ID dependencies and a working microphone).")
    args = parser.parse_args()

    manager = AuthManager()
    if manager.is_pin_enrolled():
        print("An owner PIN is already enrolled. This setup command will not overwrite it.")
        print("Use the authenticated owner settings/reset flow to change credentials.")
        return 2

    first = getpass.getpass("Create JARVIS owner PIN/password (4–64 characters): ").strip()
    second = getpass.getpass("Re-enter the PIN/password: ").strip()
    if first != second:
        print("The entries did not match. Nothing was enrolled.")
        return 2
    try:
        manager.set_master_pin(first)
    except Exception as exc:
        print(f"Could not enroll the owner credential: {type(exc).__name__}: {exc}")
        return 1
    print("Owner PIN/password enrolled in the protected local vault.")

    if args.voice:
        try:
            import numpy as np
            import sounddevice as sd
            from core import voice_id

            if not voice_id.backend_ready():
                raise RuntimeError("Voice ID model/key-store dependencies are unavailable. Install the optional Voice ID dependencies, then run scripts/enroll_master.py.")
            samples = []
            for idx in range(1, 4):
                print(f"Voice enrollment sample {idx}/3: speak naturally for 3 seconds.")
                recording = sd.rec(3 * 16000, samplerate=16000, channels=1, dtype="float32")
                sd.wait()
                samples.append(recording.reshape(-1))
            voice_id.enroll(np.concatenate(samples).astype(np.float32), role="owner")
            print("Encrypted local owner Voice ID profile enrolled.")
        except Exception as exc:
            print(f"PIN enrollment succeeded, but voice enrollment did not: {type(exc).__name__}: {exc}")
            print("Use scripts/enroll_master.py after checking the optional Voice ID dependencies and microphone.")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
