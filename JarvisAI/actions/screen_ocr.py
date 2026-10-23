"""Local OCR helpers for JARVIS desktop control.

Requires pytesseract plus the separately installed Tesseract OCR executable.
Captured screenshots are processed locally and are not uploaded by this module.
"""
from __future__ import annotations

import platform
import re
import shutil
from pathlib import Path


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _configure_tesseract(pytesseract) -> None:
    """Use PATH normally, but support the standard installer path on each OS."""
    if shutil.which("tesseract"):
        return

    if platform.system() == "Windows":
        candidates = (
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        )
    elif platform.system() == "Darwin":
        candidates = (Path("/opt/homebrew/bin/tesseract"), Path("/usr/local/bin/tesseract"))
    else:
        candidates = (Path("/usr/bin/tesseract"), Path("/usr/local/bin/tesseract"))

    for executable in candidates:
        if executable.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(executable)
            return


def read_screen_words() -> list[dict]:
    try:
        import mss
        import pytesseract
        from PIL import Image
        from pytesseract import Output
    except ImportError as exc:
        raise RuntimeError(
            "OCR dependencies are missing. Install mss, Pillow and pytesseract in JARVIS's Python environment."
        ) from exc

    _configure_tesseract(pytesseract)

    with mss.mss() as capture:
        monitor = capture.monitors[1] if len(capture.monitors) > 1 else capture.monitors[0]
        shot = capture.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        offset_x, offset_y = int(monitor.get("left", 0)), int(monitor.get("top", 0))

    try:
        data = pytesseract.image_to_data(image, output_type=Output.DICT, config="--psm 11")
    except Exception as exc:
        if "tesseract" in str(exc).lower() or "not found" in str(exc).lower():
            raise RuntimeError(
                "Tesseract OCR engine is not installed or could not be found. Install the Tesseract desktop engine "
                "or add its install folder to PATH, then restart JARVIS. Installing pytesseract alone is not enough."
            ) from exc
        raise RuntimeError(f"OCR failed: {type(exc).__name__}: {exc}") from exc

    words = []
    for i, raw in enumerate(data.get("text", [])):
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][i])
            x, y = int(data["left"][i]), int(data["top"][i])
            w, h = int(data["width"][i]), int(data["height"][i])
            line = (
                data.get("block_num", [0] * len(data["text"]))[i],
                data.get("par_num", [0] * len(data["text"]))[i],
                data.get("line_num", [0] * len(data["text"]))[i],
            )
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if confidence < 35 or w <= 0 or h <= 0:
            continue
        words.append({
            "text": text, "confidence": confidence,
            "x": x + offset_x, "y": y + offset_y, "w": w, "h": h, "line": line,
        })
    return words


def find_text_matches(label: str, words: list[dict]) -> list[dict]:
    """Find exact phrases on an OCR line and return their screen-centre coordinates."""
    target = _normalise(label)
    if not target:
        return []
    by_line = {}
    for word in words:
        by_line.setdefault(word["line"], []).append(word)
    matches = []
    for line_words in by_line.values():
        line_words.sort(key=lambda item: item["x"])
        for start in range(len(line_words)):
            selected = []
            phrase = ""
            for end in range(start, min(len(line_words), start + 8)):
                token = _normalise(line_words[end]["text"])
                if not token:
                    continue
                selected.append(line_words[end])
                phrase = (phrase + " " + token).strip()
                if phrase == target:
                    left = min(w["x"] for w in selected)
                    top = min(w["y"] for w in selected)
                    right = max(w["x"] + w["w"] for w in selected)
                    bottom = max(w["y"] + w["h"] for w in selected)
                    matches.append({
                        "x": (left + right) // 2, "y": (top + bottom) // 2,
                        "text": " ".join(w["text"] for w in selected),
                        "confidence": sum(w["confidence"] for w in selected) / len(selected),
                    })
                    break
                if not target.startswith(phrase + " "):
                    break
    unique = []
    for match in matches:
        if not any(abs(match["x"] - old["x"]) < 12 and abs(match["y"] - old["y"]) < 12 for old in unique):
            unique.append(match)
    return unique
