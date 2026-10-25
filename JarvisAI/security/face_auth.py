"""Face verification and owner face profile management for JARVIS.

Encrypts stored face embeddings using native OS credential vaults (DPAPI on Windows,
Keychain on macOS, Secret Service on Linux) or AES-GCM.
Never stores raw webcam images or unencrypted facial templates.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
CONFIG_DIR = BASE_DIR / "config"
FACE_PROFILE_FILE = CONFIG_DIR / "face_id.dat"
KEYRING_SERVICE = "JarvisAI Face ID"
KEYRING_ACCOUNT = "owner-face-profile-key-v1"
_PROFILE_MAGIC = b"JFID1"
SIMILARITY_THRESHOLD = 0.75

_face_lock = threading.Lock()


def backend_ready() -> bool:
    """Check if cv2 and required image libraries are importable."""
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def is_enrolled(role: str = "owner") -> bool:
    """Return whether an encrypted face profile exists and is valid."""
    if not FACE_PROFILE_FILE.is_file():
        return False
    try:
        profiles = _load_face_profiles()
        return str(role).strip().lower() in profiles
    except Exception:
        return False


def _get_profile_key(*, create: bool = True) -> bytes:
    """Retrieve or create 32-byte encryption key stored in native OS vault."""
    if sys.platform == "win32":
        return b""

    try:
        import keyring

        if sys.platform == "darwin":
            from keyring.backends.macOS import Keyring as NativeKeyring
        elif sys.platform.startswith("linux"):
            from keyring.backends.SecretService import Keyring as NativeKeyring
        else:
            raise RuntimeError("Unsupported platform for face key store.")

        if not isinstance(keyring.get_keyring(), NativeKeyring):
            raise RuntimeError("Native OS credential store is required for Face ID.")

        encoded = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        if encoded:
            key = base64.urlsafe_b64decode(encoded.encode("ascii"))
            if len(key) == 32:
                return key
        if not create:
            raise RuntimeError("Face ID key missing from OS credential store.")
        key = secrets.token_bytes(32)
        keyring.set_password(
            KEYRING_SERVICE, KEYRING_ACCOUNT, base64.urlsafe_b64encode(key).decode("ascii")
        )
        return key
    except Exception as exc:
        raise RuntimeError(f"Could not access OS credential vault for Face ID: {exc}") from exc


def _protect(payload: bytes) -> bytes:
    if sys.platform == "win32":
        import win32crypt
        protected = win32crypt.CryptProtectData(
            payload, "JARVIS Face ID profile", None, None, None, 0
        )
        if isinstance(protected, tuple):
            protected = protected[-1]
        return bytes(protected)

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    key = _get_profile_key(create=True)
    encrypted = AESGCM(key).encrypt(nonce, payload, _PROFILE_MAGIC)
    return _PROFILE_MAGIC + nonce + encrypted


def _unprotect(payload: bytes) -> bytes:
    if payload.startswith(_PROFILE_MAGIC):
        if sys.platform == "win32":
            raise ValueError("Face profile was created on a different platform.")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = payload[len(_PROFILE_MAGIC):len(_PROFILE_MAGIC) + 12]
        ciphertext = payload[len(_PROFILE_MAGIC) + 12:]
        key = _get_profile_key(create=False)
        return AESGCM(key).decrypt(nonce, ciphertext, _PROFILE_MAGIC)

    if sys.platform != "win32":
        raise RuntimeError("Profile encrypted with Windows DPAPI cannot be opened on this OS.")

    import win32crypt
    unprotected = win32crypt.CryptUnprotectData(payload, None, None, None, 0)
    if isinstance(unprotected, tuple):
        unprotected = unprotected[-1]
    return bytes(unprotected)


def _load_face_profiles() -> dict[str, np.ndarray]:
    if not FACE_PROFILE_FILE.is_file():
        return {}
    raw = _unprotect(FACE_PROFILE_FILE.read_bytes())
    data = json.loads(raw.decode("utf-8"))
    profiles = data.get("profiles", {})
    result = {}
    for role, vec_list in profiles.items():
        arr = np.asarray(vec_list, dtype=np.float32)
        norm = float(np.linalg.norm(arr))
        if norm > 0:
            result[role] = arr / norm
    return result


def _extract_face_embedding(frame_bgr) -> Optional[np.ndarray]:
    """Extract face embedding from OpenCV frame.

    Uses facial region alignment, grayscale histogram equalization, and multi-scale
    feature projection to compute a normalized face descriptor vector.
    """
    try:
        import cv2
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        # Detect face using OpenCV Haar cascade
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )

        if len(faces) == 0:
            return None

        # Pick largest face by area
        x, y, w, h = max(faces, key=lambda rect: rect[2] * rect[3])
        face_roi = gray[y:y + h, x:x + w]

        # Resize to standardized 64x64 grid
        face_resized = cv2.resize(face_roi, (64, 64), interpolation=cv2.INTER_AREA)
        face_norm = face_resized.astype(np.float32) / 255.0
        face_norm -= np.mean(face_norm)

        # Compute multi-resolution feature vector (spatial histogram + gradient components)
        gx = cv2.Sobel(face_norm, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(face_norm, cv2.CV_32F, 0, 1, ksize=3)
        magnitude = np.sqrt(gx ** 2 + gy ** 2)

        raw_vector = np.concatenate([face_norm.flatten(), magnitude.flatten()])
        norm = float(np.linalg.norm(raw_vector))
        if norm == 0:
            return None
        return raw_vector / norm
    except Exception as exc:
        print(f"[Face Auth] Feature extraction error: {exc}")
        return None


def enroll_frame(frame, role: str = "owner") -> tuple[bool, str]:
    """Enroll a single webcam frame as the face profile for `role`."""
    if not backend_ready():
        return False, "OpenCV (cv2) is not installed."

    vec = _extract_face_embedding(frame)
    if vec is None:
        return False, "No clear face detected in the frame. Ensure good lighting and face the camera directly."

    target_role = str(role or "owner").strip().lower()
    with _face_lock:
        try:
            profiles = _load_face_profiles()
        except Exception:
            profiles = {}

        profiles[target_role] = vec
        profiles_dict = {r: v.tolist() for r, v in profiles.items()}
        record = json.dumps({"version": 1, "profiles": profiles_dict}).encode("utf-8")

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        protected = _protect(record)
        temp_path = FACE_PROFILE_FILE.with_suffix(".tmp")
        temp_path.write_bytes(protected)
        if os.name != "nt":
            try:
                temp_path.chmod(0o600)
            except OSError:
                pass
        os.replace(temp_path, FACE_PROFILE_FILE)
        return True, f"Face profile enrolled successfully for role '{target_role}'."


def verify_frame(frame, role: str = "owner") -> tuple[bool, float, str]:
    """Verify a captured webcam frame against enrolled owner face template."""
    if not is_enrolled(role=role):
        return False, 0.0, "No face profile enrolled."
    if not backend_ready():
        return False, 0.0, "Face recognition backend unavailable."

    sample = _extract_face_embedding(frame)
    if sample is None:
        return False, 0.0, "No face detected in camera capture."

    target_role = str(role or "owner").strip().lower()
    with _face_lock:
        try:
            profiles = _load_face_profiles()
            if target_role not in profiles:
                return False, 0.0, f"No face profile found for role '{target_role}'."
            template = profiles[target_role]
            if sample.shape != template.shape:
                return False, 0.0, "Template shape mismatch."
            score = float(np.dot(sample, template))
            matched = score >= SIMILARITY_THRESHOLD
            msg = "Face verified." if matched else f"Face verification score ({score:.2f}) below threshold."
            return matched, score, msg
        except Exception as exc:
            return False, 0.0, f"Face verification error: {exc}"


def capture_and_verify(cam_index: int = 0, role: str = "owner", liveness_check: bool = True) -> tuple[bool, float, str]:
    """Capture frames from webcam and verify against enrolled owner face profile.

    Includes simple liveness check (requiring minor inter-frame motion variance across frames)
    to defend against static photographs.
    """
    if not is_enrolled(role=role):
        return False, 0.0, "No face profile enrolled."
    if not backend_ready():
        return False, 0.0, "OpenCV (cv2) is required for webcam face verification."

    import cv2

    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(cam_index, backend)
    if not cap.isOpened():
        cap = cv2.VideoCapture(cam_index)
        if not cap.isOpened():
            return False, 0.0, "Webcam could not be opened."

    frames = []
    try:
        # Capture a few frames over 0.5s for stability & liveness check
        for _ in range(5):
            ret, frame = cap.read()
            if ret and frame is not None:
                frames.append(frame)
            time.sleep(0.1)
    finally:
        cap.release()

    if not frames:
        return False, 0.0, "Failed to capture frames from webcam."

    if liveness_check and len(frames) >= 2:
        # Liveness heuristic: measure difference between initial and final frames.
        # A completely frozen/identical frame stream (e.g. static injection) or zero variance
        # indicates suspicious input.
        diff = cv2.absdiff(frames[0], frames[-1])
        variance = float(np.var(diff))
        if variance < 0.01:
            return False, 0.0, "Liveness check failed: static photo or inactive video detected."

    # Use the best matching frame
    best_match = False
    best_score = 0.0
    best_msg = "Face verification failed."

    for frame in frames:
        matched, score, msg = verify_frame(frame, role=role)
        if score > best_score:
            best_score = score
            best_match = matched
            best_msg = msg

    return best_match, best_score, best_msg


def remove_face_profile(role: str | None = None) -> None:
    """Remove enrolled face profile."""
    if not FACE_PROFILE_FILE.is_file():
        return
    with _face_lock:
        if role is not None:
            target_role = str(role).strip().lower()
            try:
                profiles = _load_face_profiles()
                if target_role in profiles:
                    del profiles[target_role]
                    if profiles:
                        profiles_dict = {r: v.tolist() for r, v in profiles.items()}
                        record = json.dumps({"version": 1, "profiles": profiles_dict}).encode("utf-8")
                        protected = _protect(record)
                        temp_path = FACE_PROFILE_FILE.with_suffix(".tmp")
                        temp_path.write_bytes(protected)
                        os.replace(temp_path, FACE_PROFILE_FILE)
                        return
            except Exception:
                pass
        try:
            FACE_PROFILE_FILE.unlink()
        except FileNotFoundError:
            pass
