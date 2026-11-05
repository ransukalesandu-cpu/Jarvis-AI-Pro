"""One webcam frame, captured in a short-lived child process.

OpenCV is the only dependable way to read a webcam on Windows without extra
drivers, but importing it costs the main process tens of megabytes that are
never returned. So the capture runs in a separate Python process:

    python -m jarvis.core.camera_snapshot [camera_index]   ->  JPEG bytes on stdout

The child opens the camera, reads one frame after a short warm-up, releases
the camera and exits; its memory goes with it. The JARVIS process never
imports cv2 for ``see_camera``. A frozen build (no separate interpreter) falls
back to capturing in-process.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_JARVIS_DIR = Path(__file__).resolve().parent.parent
MAX_SIDE = 1280


def _configured_index() -> int | None:
    try:
        from jarvis.actions.screen_processor import _load_config
        cfg = _load_config()
        return int(cfg["camera_index"]) if "camera_index" in cfg else None
    except Exception:
        return None


def capture_frame(index: int | None = None, timeout: float = 20.0) -> bytes:
    """Return one JPEG frame from the webcam; raises RuntimeError with a reason."""
    if index is None:
        index = _configured_index()
    if getattr(sys, "frozen", False):
        from jarvis.actions.screen_processor import _capture_camera
        data, _mime = _capture_camera()
        return data
    argv = [sys.executable, "-m", "jarvis.core.camera_snapshot"]
    if index is not None:
        argv.append(str(index))
    env = dict(os.environ, PYTHONPATH=str(_JARVIS_DIR.parent) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    try:
        proc = subprocess.run(argv, cwd=str(_JARVIS_DIR), capture_output=True,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("the camera did not return a frame in time") from exc
    if proc.returncode != 0 or not proc.stdout.startswith(b"\xff\xd8"):
        reason = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(reason[-1] if reason else "the camera returned no image")
    return proc.stdout


def _main(argv: list[str]) -> int:
    import cv2

    from jarvis.actions.screen_processor import _cv2_backend, _detect_camera_index

    index = int(argv[0]) if argv else _detect_camera_index()
    cap = cv2.VideoCapture(index, _cv2_backend())
    try:
        if not cap.isOpened():
            print(f"camera {index} could not be opened", file=sys.stderr)
            return 2
        frame = None
        ok = False
        for _ in range(8):          # let exposure settle
            ok, frame = cap.read()
        if not ok or frame is None:
            print("camera returned no frame", file=sys.stderr)
            return 3
    finally:
        cap.release()
    h, w = frame.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        print("could not encode the frame", file=sys.stderr)
        return 4
    sys.stdout.buffer.write(buf.tobytes())
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
