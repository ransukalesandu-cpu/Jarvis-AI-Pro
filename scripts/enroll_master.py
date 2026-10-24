#!/usr/bin/env python3
"""
scripts/enroll_master.py — Master Voice Profile Enrollment Utility.

Records or accepts 3 audio calibration samples, extracts 192-dimensional speaker embeddings,
averages them into a master profile, and saves the result to `master_voice.emb`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
import numpy as np

# Adjust sys.path to import JarvisAI modules
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
JARVIS_DIR = ROOT_DIR / "JarvisAI"
if str(JARVIS_DIR) not in sys.path:
    sys.path.insert(0, str(JARVIS_DIR))

from security.voice_auth import SpeakerAuthenticator, EMBEDDING_DIM


def record_sample(sample_num: int, duration_sec: float = 3.0, sample_rate: int = 16000) -> np.ndarray:
    """Record an audio sample from microphone using sounddevice or fallback to synthetic prompt."""
    print(f"\n[Sample {sample_num}/3] Speak clearly into your microphone for {duration_sec} seconds...")
    try:
        import sounddevice as sd
        recording = sd.rec(int(duration_sec * sample_rate), samplerate=sample_rate, channels=1, dtype="float32")
        sd.wait()
        return recording.reshape(-1)
    except Exception as e:
        print(f"⚠️ Microphone access unavailable ({e}). Generating test speech calibration signal...")
        t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
        f0 = 150 + 10 * sample_num
        sig = 0.5 * np.sin(2 * np.pi * f0 * t) + 0.25 * np.sin(2 * np.pi * (f0 * 2) * t)
        return sig.astype(np.float32)


def enroll_master(out_path: Path | None = None, sample_files: list[str] | None = None) -> Path:
    """Record or process 3 calibration samples, compute average 192-D embedding, and save profile."""
    authenticator = SpeakerAuthenticator(emb_path=out_path)
    embeddings = []

    if sample_files and len(sample_files) >= 3:
        print(f"Processing 3 provided calibration audio files...")
        for i, fpath in enumerate(sample_files[:3], 1):
            p = Path(fpath)
            if not p.exists():
                raise FileNotFoundError(f"Audio calibration sample file not found: {fpath}")
            data = np.fromfile(str(p), dtype=np.float32)
            emb = authenticator.extract_embedding(data)
            embeddings.append(emb)
            print(f"  Sample {i}: 192-D vector extracted.")
    else:
        for i in range(1, 4):
            audio = record_sample(i)
            is_live, reason = authenticator.check_liveness(audio)
            if not is_live:
                print(f"  ⚠️ Warning for sample {i}: {reason}")
            emb = authenticator.extract_embedding(audio)
            embeddings.append(emb)
            print(f"  Sample {i}: 192-D embedding extracted successfully.")

    # Compute average embedding
    avg_emb = np.mean(embeddings, axis=0)
    norm = float(np.linalg.norm(avg_emb))
    if norm > 0:
        avg_emb = avg_emb / norm
    else:
        avg_emb = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        avg_emb[0] = 1.0

    target_file = authenticator.save_master_profile(avg_emb, filepath=out_path)
    print(f"\n✅ Master voice profile successfully generated and saved to: {target_file}")
    return target_file


def main():
    parser = argparse.ArgumentParser(description="Enroll Master Voice Profile for JARVIS AI")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output path for master_voice.emb")
    parser.add_argument("--files", "-f", nargs="+", help="Optional 3 audio sample file paths for offline calibration")
    args = parser.parse_args()

    out_p = Path(args.output) if args.output else None
    enroll_master(out_path=out_p, sample_files=args.files)


if __name__ == "__main__":
    main()
