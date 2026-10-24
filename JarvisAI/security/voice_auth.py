"""
JarvisAI/security/voice_auth.py — Neural Speaker Verification & Anti-Spoofing Engine.

DISCLAIMER & SECURITY LIMITATIONS:
  Spectral liveness heuristics and speaker embedding comparisons provide speaker identity
  convenience verification, not hardware-backed biometric liveness or military-grade anti-spoofing.
  High-quality voice clones or studio replays may bypass acoustic checks. High-impact or destructive
  system operations must require PIN authentication or multi-factor verification.

Reuses repository's neural `core.voice_id` (SpeechBrain ECAPA-TDNN) for speaker verification when available and enrolled.
If neural verification is un-enrolled or dependencies are missing, verification fails closed to PIN challenge.
"""

from __future__ import annotations

import os
import sys
import math
from pathlib import Path
import numpy as np

try:
    from core import voice_id
    _VOICE_ID_MODULE_AVAILABLE = True
except ImportError:
    _VOICE_ID_MODULE_AVAILABLE = False

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
    """
    Neural Speaker Verification Engine.
    Leverages core.voice_id (SpeechBrain ECAPA-TDNN) for 192-D speaker embeddings.
    Fails closed to PIN when neural speaker models are un-enrolled or unavailable.
    """

    def __init__(self, emb_path: str | Path | None = None):
        self.emb_path = Path(emb_path) if emb_path else DEFAULT_EMB_PATH

    def extract_embedding(self, audio: np.ndarray | list | bytes, sample_rate: int = 16000) -> np.ndarray:
        """
        Extract a 192-dimensional speaker embedding vector using core.voice_id if available.
        Fails closed with zero vector if unavailable.
        """
        if isinstance(audio, bytes):
            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            samples = np.asarray(audio, dtype=np.float32).reshape(-1)

        if samples.dtype.kind in "iu":
            samples = samples.astype(np.float32) / 32768.0

        if len(samples) == 0:
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)

        # Use SpeechBrain via core.voice_id if backend ready
        if _VOICE_ID_MODULE_AVAILABLE and voice_id.backend_ready():
            try:
                # voice_id._embedding accepts waveform samples
                int16_audio = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
                emb = voice_id._embedding(int16_audio)
                if len(emb) == EMBEDDING_DIM:
                    return emb.astype(np.float32)
            except Exception as e:
                print(f"[SpeakerAuthenticator] SpeechBrain embedding extraction failed: {e}")

        # Fail closed: return zero vector if neural embedding model unavailable
        return np.zeros(EMBEDDING_DIM, dtype=np.float32)

    def check_liveness(self, audio: np.ndarray | list | bytes, sample_rate: int = 16000) -> tuple[bool, str]:
        """
        Spectral liveness/anti-spoofing heuristic check.
        NOTE: This is a basic spectral acoustic check, not proof against voice cloning or acoustic replays.
        """
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
        """Save a 192-dimensional vector to local `master_voice.emb` file."""
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
                        if len(vec) == EMBEDDING_DIM and float(np.linalg.norm(vec)) > 0:
                            return vec
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
        Real-time verification: compare live voice against enrolled master profile using cosine similarity.
        Fails closed (returns False) if un-enrolled or neural backend is unavailable.
        Returns: (is_master, similarity_score, is_live)
        """
        master_emb = self.load_master_profile(master_emb_path)
        is_live, _liveness_reason = self.check_liveness(audio, sample_rate=sample_rate)

        if master_emb is None:
            return False, 0.0, is_live

        live_emb = self.extract_embedding(audio, sample_rate=sample_rate)
        if float(np.linalg.norm(live_emb)) == 0.0:
            return False, 0.0, is_live

        similarity = compute_cosine_similarity(live_emb, master_emb)
        is_master = (similarity >= COSINE_THRESHOLD) and is_live

        return is_master, similarity, is_live
