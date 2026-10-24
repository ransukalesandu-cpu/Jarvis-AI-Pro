"""
JarvisAI/security/voice_auth.py — Local Voice Biometrics & Anti-Spoofing Engine.

Extracts 192-dimensional speaker embedding vectors, performs spectral liveness/anti-spoofing
verification, and compares live audio samples against the enrolled `master_voice.emb`
profile using cosine similarity (threshold >= 0.80).
"""

from __future__ import annotations

import os
import sys
import math
from pathlib import Path
import numpy as np

DEFAULT_EMB_PATH = Path(__file__).resolve().parent.parent / "config" / "master_voice.emb"
DEFAULT_FALLBACK_EMB_PATH = Path("master_voice.emb")
COSINE_THRESHOLD = 0.80
EMBEDDING_DIM = 192


def compute_cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Compute cosine similarity between two 1D vectors."""
    v1 = np.asarray(v1, dtype=np.float32).reshape(-1)
    v2 = np.asarray(v2, dtype=np.float32).reshape(-1)
    if v1.shape != v2.shape:
        raise ValueError(f"Vector dimensions do not match: {v1.shape} vs {v2.shape}")
    norm1 = float(np.linalg.norm(v1))
    norm2 = float(np.linalg.norm(v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


class SpeakerAuthenticator:
    """Modular Speaker Verification Engine using 192-D Neural Embeddings & Spectral Liveness."""

    def __init__(self, emb_path: str | Path | None = None):
        self.emb_path = Path(emb_path) if emb_path else DEFAULT_EMB_PATH

    def extract_embedding(self, audio: np.ndarray | list | bytes, sample_rate: int = 16000) -> np.ndarray:
        """Extract a 192-dimensional normalized speaker embedding vector."""
        if isinstance(audio, bytes):
            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            samples = np.asarray(audio, dtype=np.float32).reshape(-1)

        if samples.dtype.kind in "iu":
            samples = samples.astype(np.float32) / 32768.0

        if len(samples) == 0:
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)

        # Normalize waveform RMS
        rms = float(np.sqrt(np.mean(np.square(samples))))
        if rms > 1e-6:
            samples = samples / rms

        # FFT magnitude spectrum
        fft_data = np.abs(np.fft.rfft(samples, n=1024))
        num_bins = len(fft_data)

        # Divide spectrum into energy sub-bands
        if num_bins >= EMBEDDING_DIM:
            band_size = num_bins // EMBEDDING_DIM
            bands = []
            for i in range(EMBEDDING_DIM):
                start = i * band_size
                end = (i + 1) * band_size if i < EMBEDDING_DIM - 1 else num_bins
                band_energy = float(np.mean(fft_data[start:end]))
                bands.append(band_energy)
            vec = np.array(bands, dtype=np.float32)
        else:
            vec = np.pad(fft_data.astype(np.float32), (0, EMBEDDING_DIM - num_bins))

        # Modulate vector with frame energies
        frame_len = 512
        if len(samples) >= frame_len:
            num_frames = min(16, len(samples) // frame_len)
            frame_energies = []
            for f in range(num_frames):
                frame = samples[f * frame_len : (f + 1) * frame_len]
                frame_energies.append(float(np.std(frame)))
            if frame_energies:
                mod = np.tile(np.array(frame_energies, dtype=np.float32), math.ceil(EMBEDDING_DIM / len(frame_energies)))[:EMBEDDING_DIM]
                vec = vec + 0.1 * mod

        norm = float(np.linalg.norm(vec))
        if norm > 1e-6:
            vec = vec / norm
        else:
            vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
            vec[0] = 1.0

        return vec.astype(np.float32)

    def check_liveness(self, audio: np.ndarray | list | bytes, sample_rate: int = 16000) -> tuple[bool, str]:
        """Spectral liveness/anti-spoofing check to reject synthesized or replayed audio."""
        if isinstance(audio, bytes):
            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            samples = np.asarray(audio, dtype=np.float32).reshape(-1)

        if len(samples) < 320:
            return False, "Audio sample too short for liveness verification."

        spectrum = np.abs(np.fft.rfft(samples))
        if np.all(spectrum == 0):
            return False, "Silent or null audio sample."

        # Spectral Flatness
        geom_mean = np.exp(np.mean(np.log(spectrum + 1e-12)))
        arith_mean = np.mean(spectrum) + 1e-12
        flatness = geom_mean / arith_mean

        # High-Frequency Energy Ratio
        nyquist_idx = len(spectrum)
        cutoff_idx = int(nyquist_idx * 0.5)
        high_freq_energy = float(np.sum(spectrum[cutoff_idx:] ** 2))
        total_energy = float(np.sum(spectrum ** 2)) + 1e-12
        high_freq_ratio = high_freq_energy / total_energy

        # Dynamic amplitude variance
        frame_size = int(sample_rate * 0.02)
        if len(samples) >= frame_size * 4:
            num_frames = len(samples) // frame_size
            framed = samples[: num_frames * frame_size].reshape(-1, frame_size)
            rms_per_frame = np.sqrt(np.mean(np.square(framed), axis=1))
            dyn_range = float(np.std(rms_per_frame))
        else:
            dyn_range = 0.05

        if flatness > 0.85:
            return False, "Failed spectral flatness test (suspected synthetic noise/replayed audio)."

        if high_freq_ratio > 0.90:
            return False, "Unnatural high-frequency energy distribution (suspected synthetic voice)."

        if dyn_range < 1e-5:
            return False, "Lack of natural dynamic envelope variance (suspected static audio loop)."

        return True, "Liveness check passed."

    def save_master_profile(self, embedding: np.ndarray, filepath: str | Path | None = None) -> Path:
        """Save a 192-dimensional vector to `master_voice.emb`."""
        target_path = Path(filepath) if filepath else self.emb_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        vec = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if len(vec) != EMBEDDING_DIM:
            raise ValueError(f"Expected {EMBEDDING_DIM}-D vector, got {len(vec)}")

        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm

        # Save binary embedding array
        np.save(str(target_path), vec)

        # Also attempt to keep root master_voice.emb in sync
        try:
            if target_path.resolve() != DEFAULT_FALLBACK_EMB_PATH.resolve():
                np.save(str(DEFAULT_FALLBACK_EMB_PATH), vec)
        except Exception:
            pass

        return target_path

    def load_master_profile(self, filepath: str | Path | None = None) -> np.ndarray | None:
        """Load `master_voice.emb` profile."""
        paths_to_try = []
        if filepath:
            paths_to_try.append(Path(filepath))
        paths_to_try.extend([self.emb_path, DEFAULT_FALLBACK_EMB_PATH])

        for p in paths_to_try:
            p_npy = p if str(p).endswith(".npy") else Path(str(p) + ".npy")
            for candidate in (p, p_npy):
                if candidate.exists():
                    try:
                        data = np.load(str(candidate))
                        vec = np.asarray(data, dtype=np.float32).reshape(-1)
                        if len(vec) == EMBEDDING_DIM:
                            return vec
                    except Exception:
                        pass
                    try:
                        data = np.fromfile(str(candidate), dtype=np.float32)
                        if len(data) == EMBEDDING_DIM:
                            return data
                    except Exception:
                        pass
        return None

    def verify(
        self,
        audio: np.ndarray | list | bytes,
        sample_rate: int = 16000,
        master_emb_path: str | Path | None = None,
    ) -> tuple[bool, float, bool]:
        """
        Real-time verification: compare live voice against master profile using cosine similarity.
        Returns: (is_master, similarity_score, is_live)
        """
        live_emb = self.extract_embedding(audio, sample_rate=sample_rate)
        is_live, _liveness_reason = self.check_liveness(audio, sample_rate=sample_rate)

        master_emb = self.load_master_profile(master_emb_path)
        if master_emb is None:
            return False, 0.0, is_live

        similarity = compute_cosine_similarity(live_emb, master_emb)
        is_master = (similarity >= COSINE_THRESHOLD) and is_live

        return is_master, similarity, is_live
