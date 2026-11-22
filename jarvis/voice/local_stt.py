"""Optional offline speech-to-text with faster-whisper (Cherry Studio parity P11). See docs/LOCAL_STT.md.

Off unless the optional package is installed (``pip install -r requirements-stt.txt``).
The model is downloaded once into ``<data>/models/whisper`` and then runs fully offline
on the CPU (int8). Gemini Live stays the realtime voice path; this module is used for
dictation into any text box and for transcribing audio files without the cloud.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

SAMPLE_RATE = 16_000
DEFAULT_MODEL = "small"            # good accuracy on a 16 GB machine; "base" for low RAM, "medium" for best
MAX_DICTATION_S = 120

_model = None
_model_name = ""
_lock = threading.Lock()


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def model_dir() -> Path:
    from jarvis.core.user_data import user_data_dir
    d = user_data_dir() / "models" / "whisper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_model():
    global _model, _model_name
    name = os.environ.get("JARVIS_STT_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    with _lock:
        if _model is None or _model_name != name:
            from faster_whisper import WhisperModel
            _model = WhisperModel(name, device="cpu", compute_type="int8", download_root=str(model_dir()))
            _model_name = name
        return _model


def transcribe(source, *, language: str = "", model=None) -> dict:
    """Transcribe a file path or a float32/int16 numpy array at 16 kHz.

    Returns {'text', 'language', 'seconds'}. Raises RuntimeError when faster-whisper is missing.
    """
    if model is None and not available():
        raise RuntimeError("offline speech-to-text is not installed (pip install -r requirements-stt.txt)")
    m = model or _get_model()
    if hasattr(source, "dtype") and str(source.dtype) == "int16":
        source = source.astype("float32") / 32768.0
    if isinstance(source, (str, Path)):
        source = str(source)
    started = time.monotonic()
    segments, info = m.transcribe(source, language=(language or None), vad_filter=True, beam_size=1)
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": getattr(info, "language", language or ""),
            "seconds": round(time.monotonic() - started, 2)}


def record(seconds: float = 0.0, *, stop: Optional[threading.Event] = None, silence_s: float = 1.6,
           max_s: float = MAX_DICTATION_S, stream_factory: Optional[Callable] = None):
    """Record from the default microphone until ``stop`` is set, ``seconds`` pass, or the owner is
    silent for ``silence_s`` after speaking. Returns a float32 numpy array at 16 kHz."""
    import numpy as np
    chunks: list = []
    spoke = False
    quiet_since = None
    started = time.monotonic()
    limit = min(seconds or max_s, max_s)
    if stream_factory is None:
        import sounddevice as sd

        def stream_factory():
            return sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=1600)
    with stream_factory() as stream:
        while time.monotonic() - started < limit and not (stop and stop.is_set()):
            block, _ = stream.read(1600)
            block = np.asarray(block, dtype="float32").reshape(-1)
            chunks.append(block)
            level = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
            if level > 0.015:
                spoke, quiet_since = True, None
            elif spoke:
                quiet_since = quiet_since or time.monotonic()
                if not seconds and time.monotonic() - quiet_since >= silence_s:
                    break
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype="float32")


def type_text(text: str, clip=None) -> None:
    """Insert text at the cursor of the focused app (clipboard paste, clipboard restored)."""
    from jarvis.quick import replace_selection
    replace_selection(text, clip)
