#!/usr/bin/env python3
"""Enroll owner Face ID template through encrypted face_auth profile vault.

Disclaimers: Biometric face recognition may be spoofed by high-resolution photographs
or realistic masks. Use OpenCV camera captures with liveness detection enabled.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for item in (ROOT_DIR, JARVIS_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))


def main() -> int:
    parser = argparse.ArgumentParser(description="Enroll owner Face ID using webcam capture.")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default 0)")
    args = parser.parse_args()

    from security import face_auth

    if not face_auth.backend_ready():
        print("Error: OpenCV (cv2) is required for face enrollment.")
        return 1

    import cv2

    print("Opening webcam for face enrollment... Look directly into the camera.")
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"Error: Could not open camera {args.camera}.")
        return 1

    try:
        frame = None
        for _ in range(10):
            ret, frame = cap.read()
            if ret and frame is not None:
                break
            time.sleep(0.1)

        if frame is None:
            print("Error: Failed to capture frame from camera.")
            return 1

        ok, msg = face_auth.enroll_frame(frame, role="owner")
        if ok:
            print("Success:", msg)
            print("Notice: Face profiles are encrypted locally using OS key vaults (DPAPI/Keychain/SecretService).")
            print("Biometric Disclaimer: Face ID uses liveness checks, but simple facial recognition may still be vulnerable to physical spoofs or identical twins.")
            return 0
        else:
            print("Enrollment failed:", msg)
            return 1
    finally:
        cap.release()


if __name__ == "__main__":
    sys.exit(main())
