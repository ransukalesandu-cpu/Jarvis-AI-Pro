"""
Screen & webcam capture for JARVIS vision.

Provides the two capture entry points main.py uses — `_capture_screen()` and
`_capture_camera()` — plus their helpers (compression, camera auto-detection,
config access). main.py grabs a frame here on demand, then injects it into the
main Gemini Live session; there is no separate vision session here.
"""
from __future__ import annotations

import io
import json
import platform
import sys
from pathlib import Path

import numpy as np

# OpenCV is the heaviest import in this module and the camera is the only thing
# that needs it: screen capture runs through mss. Importing it with the module
# charged every launch for a feature most sessions never use, so it is loaded on
# the first camera call instead (the same pattern security/face_auth.py uses).
cv2 = None
_CV2 = False
_CV2_LOAD_ATTEMPTED = False


def _load_cv2() -> bool:
    """Import OpenCV on first use. Returns True when it is usable."""
    global cv2, _CV2, _CV2_LOAD_ATTEMPTED
    if _CV2_LOAD_ATTEMPTED:
        return _CV2
    _CV2_LOAD_ATTEMPTED = True
    try:
        import cv2 as _cv2
    except ImportError:
        return False
    cv2 = _cv2
    _CV2 = True
    return True

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    import PIL.Image
    _PIL = True
except ImportError:
    _PIL = False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE        = _base_dir()
_CONFIG_PATH = _BASE / "config" / "api_keys.json"


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config_key(key: str, value) -> None:
    try:
        cfg = _load_config()
        cfg[key] = value
        from memory.config_manager import write_api_config
        write_api_config(cfg)
    except Exception as e:
        print(f"[Vision] ⚠️  Could not save config key '{key}': {e}")


def _get_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), "linux"
    )


_IMG_MAX_W = 1280
_IMG_MAX_H = 720
_JPEG_Q    = 82


def _compress(img_bytes: bytes, source_format: str = "PNG") -> tuple[bytes, str]:
    if not _PIL:
        return img_bytes, f"image/{source_format.lower()}"

    try:
        img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q, optimize=False)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"[Vision] ⚠️  Image compress failed: {e}")
        return img_bytes, f"image/{source_format.lower()}"


def _encode_rgb(rgb: bytes, size) -> tuple[bytes, str]:
    """Turn raw RGB pixels into the JPEG that is actually sent.

    The bytes come straight from the screen grab, so there is no reason to
    encode them to PNG and immediately decode them again: on a 1920x1080 screen
    that intermediate PNG is several megabytes of allocation plus a full
    deflate/inflate cycle, on a laptop with 4 GB of RAM, on every screenshot.
    """
    img = PIL.Image.frombytes("RGB", size, rgb)
    img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_Q, optimize=False)
    return buf.getvalue(), "image/jpeg"


def _capture_screen() -> tuple[bytes, str]:

    if not _MSS:
        raise RuntimeError(
            "mss is not installed. From the JarvisAI folder, run: "
            f'"{sys.executable}" -m pip install -r requirements.txt'
        )

    with mss.mss() as sct:
        monitors = sct.monitors          # [0] = all combined, [1..n] = real screens
        target   = monitors[1] if len(monitors) > 1 else monitors[0]
        shot     = sct.grab(target)

        if _PIL:
            try:
                return _encode_rgb(shot.rgb, shot.size)
            except Exception as e:
                # Never lose a frame over an encoding optimisation: fall back to
                # the PNG path and let _compress() do the same job.
                print(f"[Vision] ⚠️  Direct RGB encode failed ({e}); using PNG path.")

        png = mss.tools.to_png(shot.rgb, shot.size)

    return _compress(png, "PNG")


def _cv2_backend() -> int:
    """Return the best OpenCV camera backend for the current OS."""
    if not _load_cv2():
        return 0
    os_name = _get_os()
    if os_name == "windows":
        return cv2.CAP_DSHOW
    if os_name == "mac":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


def _probe_camera(index: int, backend: int, warmup: int = 5) -> bool:

    if not _load_cv2():
        return False
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        return False
    for _ in range(warmup):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return False
    return bool(np.mean(frame) > 8)


def _detect_camera_index() -> int:

    backend = _cv2_backend()
    print("[Vision] 🔍 Auto-detecting camera...")
    for idx in range(6):
        if _probe_camera(idx, backend):
            print(f"[Vision] ✅ Camera found at index {idx}")
            _save_config_key("camera_index", idx)
            return idx
        print(f"[Vision] ⚠️  Camera index {idx}: no usable frame")

    print("[Vision] ⚠️  No camera found — defaulting to index 0")
    _save_config_key("camera_index", 0)
    return 0


def _get_camera_index() -> int:
    cfg = _load_config()
    if "camera_index" in cfg:
        return int(cfg["camera_index"])
    return _detect_camera_index()


def _capture_camera() -> tuple[bytes, str]:
    if not _load_cv2():
        raise RuntimeError(
            "OpenCV (cv2) is not installed. From the JarvisAI folder, run: "
            f'"{sys.executable}" -m pip install -r requirements.txt'
        )

    index   = _get_camera_index()
    backend = _cv2_backend()
    cap     = cv2.VideoCapture(index, backend)

    if not cap.isOpened():
        raise RuntimeError(f"Camera index {index} could not be opened.")

    for _ in range(10):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError("Camera returned no frame.")

    if _PIL:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q)
        return buf.getvalue(), "image/jpeg"

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_Q])
    return buf.tobytes(), "image/jpeg"
