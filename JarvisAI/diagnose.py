"""Preflight diagnostics for JARVIS AI.

Run from the JarvisAI directory:
    python diagnose.py

Checks Python imports, the external Tesseract OCR executable, and audio devices.
It never prints API keys or modifies configuration.
"""
from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path

MODULES = {
    "PyQt6 (desktop UI)": "PyQt6",
    "PyQt6 WebEngine (embedded browser/HUD)": "PyQt6.QtWebEngineWidgets",
    "sounddevice (microphone/speakers)": "sounddevice",
    "numpy": "numpy",
    "Gemini SDK": "google.genai",
    "OpenCV (camera)": "cv2",
    "mss (screen capture)": "mss",
    "Pillow (image processing)": "PIL",
    "DuckDuckGo search": "ddgs",
    "Edge TTS (default speech engine)": "edge_tts",
    "miniaudio (speech playback decoder)": "miniaudio",
    "pytesseract (OCR Python bridge)": "pytesseract",
    "PyAutoGUI (mouse/keyboard control)": "pyautogui",
}
if platform.system() == "Windows":
    MODULES["pywinauto (Windows UI Automation)"] = "pywinauto"
if sys.version_info >= (3, 13):
    MODULES["audioop compatibility (Python 3.13+)"] = "audioop"


def _available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _find_tesseract() -> Path | None:
    """Find Tesseract on PATH or at common installer locations."""
    on_path = shutil.which("tesseract")
    if on_path:
        return Path(on_path)

    if platform.system() == "Windows":
        candidates = (
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        )
    elif platform.system() == "Darwin":
        candidates = (Path("/opt/homebrew/bin/tesseract"), Path("/usr/local/bin/tesseract"))
    else:
        candidates = (Path("/usr/bin/tesseract"), Path("/usr/local/bin/tesseract"))

    return next((path for path in candidates if path.is_file()), None)


def _print_audio_diagnostics() -> bool:
    """Print discovered audio endpoints. Return True if both directions exist."""
    print("\nAudio devices:")
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        inputs = []
        outputs = []
        for index, device in enumerate(devices):
            name = device.get("name", "Unknown")
            if device.get("max_input_channels", 0):
                inputs.append((index, name))
            if device.get("max_output_channels", 0):
                outputs.append((index, name))

        for index, name in inputs:
            print(f"  [MIC]     {index}: {name}")
        for index, name in outputs:
            print(f"  [SPEAKER] {index}: {name}")

        try:
            default_input, default_output = sd.default.device
            print(f"  Default input device:  {default_input}")
            print(f"  Default output device: {default_output}")
        except Exception as exc:
            print(f"  [WARN] Could not read default audio devices: {type(exc).__name__}: {exc}")

        if not inputs:
            print("[WARN] No microphone/input device reported by PortAudio.")
        if not outputs:
            print("[WARN] No speaker/output device reported by PortAudio.")
        return bool(inputs and outputs)
    except Exception as exc:
        print(f"[WARN] Audio device query failed: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    version = sys.version_info
    print("JARVIS AI — runtime preflight")
    print(f"OS: {platform.platform()}")
    print(f"Python: {version.major}.{version.minor}.{version.micro}")
    if version < (3, 11) or version >= (3, 14):
        print("WARN: This project targets Python 3.11–3.13.")
    print()

    missing_python = []
    for label, module in MODULES.items():
        ok = _available(module)
        print(f"[{'OK' if ok else 'MISSING'}] {label}")
        if not ok:
            missing_python.append(label)

    tesseract = _find_tesseract()
    if tesseract:
        try:
            result = subprocess.run(
                [str(tesseract), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            version_line = (result.stdout or result.stderr).splitlines()
            if result.returncode == 0 and version_line:
                print(f"[OK] Tesseract OCR engine: {version_line[0]} ({tesseract})")
            else:
                print(f"[WARN] Tesseract was found but version check failed: {tesseract}")
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"[WARN] Tesseract was found but could not run: {type(exc).__name__}: {exc}")
    else:
        print("[MISSING] Tesseract OCR engine (separate desktop install required)")
        print("  Windows installer: https://github.com/UB-Mannheim/tesseract/wiki")

    _print_audio_diagnostics()

    print("\nAPI configuration:")
    try:
        from memory.config_manager import get_gemini_key
        if get_gemini_key():
            print("[OK] Gemini API key is configured (value hidden).")
        else:
            print("[WARN] Gemini API key is not configured (value hidden).")
    except Exception as exc:
        print(f"[WARN] Could not read API configuration: {type(exc).__name__}: {exc}")

    if missing_python:
        print("\nMissing Python packages detected.")
        print("From this directory, install them into the same Python environment JARVIS uses:")
        print(f'  "{sys.executable}" -m pip install -r requirements.txt')
    if not tesseract:
        print("\nTesseract is not a pip package. Install the desktop engine separately,")
        print("then reopen CMD/JARVIS so the updated PATH is picked up.")

    if missing_python or not tesseract:
        return 1

    print("\nPreflight dependency checks passed. If audio warnings appeared, choose a valid")
    print("microphone/speaker in Windows sound settings or JARVIS audio settings.")
    print("This does not replace testing live microphone capture, playback, API access, or web search.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
