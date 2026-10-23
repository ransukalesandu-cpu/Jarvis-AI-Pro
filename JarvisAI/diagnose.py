"""Preflight diagnostics for JARVIS AI.

Run from the JarvisAI directory:
    python diagnose.py

This script does not print API keys or modify configuration. It checks the
runtime imports used by the main voice, web-search, and screen-capture paths.
"""
from __future__ import annotations

import importlib.util
import platform
import sys

MODULES = {
    "PyQt6": "PyQt6",
    "sounddevice (microphone/speakers)": "sounddevice",
    "numpy": "numpy",
    "Gemini SDK": "google.genai",
    "OpenCV (camera)": "cv2",
    "mss (screen capture)": "mss",
    "Pillow (image processing)": "PIL",
    "DuckDuckGo search": "ddgs",
    "Edge TTS (default speech engine)": "edge_tts",
    "miniaudio (speech playback decoder)": "miniaudio",
}
if sys.version_info >= (3, 13):
    MODULES["audioop compatibility (Python 3.13+)"] = "audioop"


def _available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def main() -> int:
    version = sys.version_info
    print("JARVIS AI — runtime preflight")
    print(f"OS: {platform.platform()}")
    print(f"Python: {version.major}.{version.minor}.{version.micro}")
    if version < (3, 11) or version >= (3, 14):
        print("WARN: This project targets Python 3.11–3.13.")
    print()

    missing = []
    for label, module in MODULES.items():
        ok = _available(module)
        print(f"[{'OK' if ok else 'MISSING'}] {label}")
        if not ok:
            missing.append(label)

    print("\nAudio devices:")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        if len(devices) == 0:
            print("[WARN] No audio devices reported by PortAudio.")
        else:
            for index, device in enumerate(devices):
                channels = []
                if device.get("max_input_channels", 0):
                    channels.append("mic")
                if device.get("max_output_channels", 0):
                    channels.append("speaker")
                if channels:
                    print(f"  {index}: {device.get('name', 'Unknown')} ({', '.join(channels)})")
    except Exception as exc:
        print(f"[WARN] Audio device query failed: {type(exc).__name__}: {exc}")

    print("\nAPI configuration:")
    try:
        from memory.config_manager import get_gemini_key
        if get_gemini_key():
            print("[OK] Gemini API key is configured (value hidden).")
        else:
            print("[WARN] Gemini API key is not configured (value hidden).")
    except Exception as exc:
        print(f"[WARN] Could not read API configuration: {type(exc).__name__}: {exc}")

    if missing:
        print("\nMissing runtime packages detected.")
        print("From this directory, run:")
        print(f'  "{sys.executable}" -m pip install -r requirements.txt')
        return 1

    print("\nPreflight imports passed. This does not replace testing the microphone,")
    print("speaker playback, live API connection, or web access on this computer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
