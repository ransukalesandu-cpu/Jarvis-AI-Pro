#!/usr/bin/env python3
"""Enroll JARVIS owner voice through the existing encrypted core.voice_id store.

No synthetic fallback samples and no plaintext master_voice.emb.npy are created.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for item in (ROOT_DIR, JARVIS_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))


def _record_three_samples() -> list[np.ndarray]:
    try:
        import sounddevice as sd
    except Exception as exc:
        raise RuntimeError("Microphone capture requires the sounddevice/PortAudio dependency.") from exc

    result = []
    for idx in range(1, 4):
        print(f"Voice enrollment sample {idx}/3: speak naturally for 3 seconds.")
        try:
            recording = sd.rec(3 * 16000, samplerate=16000, channels=1, dtype="float32")
            sd.wait()
        except Exception as exc:
            raise RuntimeError("Microphone capture failed; no synthetic fallback is allowed.") from exc
        samples = np.asarray(recording, dtype=np.float32).reshape(-1)
        if samples.size < int(16000 * 1.5) or not np.isfinite(samples).all():
            raise RuntimeError("The microphone sample was too short or invalid. No profile was saved.")
        result.append(samples)
    return result


def enroll_master(sample_files: list[str] | None = None) -> Path:
    from core import voice_id

    if not voice_id.backend_ready():
        raise RuntimeError(
            "The optional local Voice ID model or secure platform key store is unavailable. "
            "Install the optional SpeechBrain/Torch and platform key-store dependencies first."
        )

    if sample_files:
        if len(sample_files) < 3:
            raise ValueError("Provide at least three raw float32 PCM sample files, or omit --files to record from the microphone.")
        samples = []
        for name in sample_files[:3]:
            path = Path(name)
            if not path.is_file():
                raise FileNotFoundError(f"Audio sample not found: {path}")
            audio = np.fromfile(str(path), dtype=np.float32)
            if audio.size < int(16000 * 1.5) or not np.isfinite(audio).all():
                raise ValueError(f"Audio sample is too short or invalid: {path}")
            samples.append(audio)
    else:
        samples = _record_three_samples()

    voice_id.enroll(np.concatenate(samples).astype(np.float32), role="owner")
    return voice_id.PROFILE_FILE


def main() -> int:
    parser = argparse.ArgumentParser(description="Enroll owner Voice ID using the encrypted local profile.")
    parser.add_argument("--files", "-f", nargs="+", help="Three or more raw float32 PCM sample files recorded at 16 kHz.")
    parser.add_argument("--output", "-o", help="Deprecated; plaintext profile output is no longer supported.")
    args = parser.parse_args()
    if args.output:
        parser.error("--output is disabled because owner voice profiles must remain encrypted.")
    try:
        enroll_master(args.files)
    except Exception as exc:
        print(f"Voice enrollment failed: {type(exc).__name__}: {exc}")
        return 1
    print("Encrypted owner Voice ID profile saved locally.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
