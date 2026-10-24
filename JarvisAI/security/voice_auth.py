"""
Voice verification adapter for the existing encrypted JARVIS Voice ID profile.

The acoustic liveness test is a heuristic only; it is not proof against replay or
voice cloning. The owner profile itself is managed by core.voice_id and is never
written as a plaintext embedding by this module.
"""
from __future__ import annotations

import numpy as np

EMBEDDING_DIM = 192
COSINE_THRESHOLD = 0.35


def compute_cosine_similarity(v1, v2) -> float:
    a = np.asarray(v1, dtype=np.float32).reshape(-1)
    b = np.asarray(v2, dtype=np.float32).reshape(-1)
    if a.shape != b.shape:
        raise ValueError(f"Vector dimensions do not match: {a.shape} vs {b.shape}")
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class SpeakerAuthenticator:
    """Thin wrapper around core.voice_id; does not store separate plaintext voice embeddings."""

    def __init__(self, emb_path=None):
        self.emb_path = emb_path

    def check_liveness(self, audio, sample_rate: int = 16000) -> tuple[bool, str]:
        samples = self._float_audio(audio)
        if len(samples) < max(320, int(sample_rate * 0.25)):
            return False, "Audio sample too short."
        if not np.isfinite(samples).all() or float(np.max(np.abs(samples))) < 0.003:
            return False, "Silent or invalid audio sample."
        frame = max(1, int(sample_rate * 0.02))
        usable = (len(samples) // frame) * frame
        if usable < frame * 4:
            return False, "Audio sample too short."
        framed = samples[:usable].reshape(-1, frame)
        rms = np.sqrt(np.mean(np.square(framed), axis=1))
        if float(np.std(rms)) < 1e-5:
            return False, "No natural amplitude variation detected."
        # This weak check only rejects obvious silence/static samples. It does not
        # establish liveness against replay or synthetic voice.
        return True, "Basic acoustic check passed."

    @staticmethod
    def _float_audio(audio):
        if isinstance(audio, bytes):
            return np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        samples = np.asarray(audio).reshape(-1)
        if samples.dtype.kind in "iu":
            samples = samples.astype(np.float32) / 32768.0
        else:
            samples = samples.astype(np.float32)
        return samples

    def extract_embedding(self, audio, sample_rate: int = 16000):
        try:
            from core import voice_id
            if not voice_id.backend_ready():
                return np.zeros(EMBEDDING_DIM, dtype=np.float32)
            samples = self._float_audio(audio)
            return voice_id._embedding(samples)
        except Exception:
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)

    def save_master_profile(self, embedding, filepath=None):
        raise RuntimeError(
            "Plaintext voice embeddings are disabled. Enroll using core.voice_id.enroll() "
            "or scripts/enroll_master.py, which stores the profile encrypted."
        )

    def load_master_profile(self, filepath=None):
        return None

    def verify(self, audio, sample_rate: int = 16000, master_emb_path=None):
        """Return (match, score, basic_liveness); fail closed unless encrypted Voice ID is enabled."""
        try:
            from core import voice_id
            live, _reason = self.check_liveness(audio, sample_rate=sample_rate)
            if not live or not voice_id.is_enabled() or not voice_id.backend_ready():
                return False, 0.0, live
            match, score = voice_id.verify(self._float_audio(audio), role="owner")
            return bool(match and live), float(score), bool(live)
        except Exception:
            return False, 0.0, False
