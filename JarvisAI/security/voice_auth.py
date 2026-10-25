"""
Voice verification adapter for the existing encrypted JARVIS Voice ID profile.

The amplitude/RMS check below is only an audio-quality filter. It is not
anti-spoofing and cannot distinguish a live speaker from a replay or cloned
voice. Sensitive owner verification therefore requires an explicitly supplied
anti-spoof verifier. Without one, verification fails closed.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

EMBEDDING_DIM = 192
COSINE_THRESHOLD = 0.35
AntiSpoofVerifier = Callable[[np.ndarray, int], bool]


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
    """Encrypted Voice ID adapter with fail-closed anti-spoof verification.

    `anti_spoof_verifier` must be a separately implemented and validated
    detector that evaluates replay/synthetic-voice risk. The built-in acoustic
    check is intentionally not accepted as a substitute.
    """

    def __init__(self, emb_path=None, anti_spoof_verifier: AntiSpoofVerifier | None = None):
        self.emb_path = emb_path
        self._anti_spoof_verifier = anti_spoof_verifier

    def check_liveness(self, audio, sample_rate: int = 16000) -> tuple[bool, str]:
        """Check basic signal quality only; this is NOT proof of live speech."""
        samples = self._float_audio(audio)
        if sample_rate <= 0:
            return False, "Invalid sample rate."
        if not np.isfinite(samples).all():
            return False, "Audio contains invalid samples."
        if len(samples) < max(320, int(sample_rate * 0.25)):
            return False, "Audio sample too short."
        if float(np.max(np.abs(samples))) < 0.003:
            return False, "Silent audio sample."
        frame = max(1, int(sample_rate * 0.02))
        usable = (len(samples) // frame) * frame
        if usable < frame * 4:
            return False, "Audio sample too short."
        framed = samples[:usable].reshape(-1, frame)
        rms = np.sqrt(np.mean(np.square(framed), axis=1))
        if float(np.std(rms)) < 1e-5:
            return False, "No amplitude variation detected."
        return True, "Basic audio-quality check passed; liveness is unverified."

    @staticmethod
    def _float_audio(audio):
        if isinstance(audio, bytes):
            if len(audio) % 2:
                return np.array([], dtype=np.float32)
            return np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        samples = np.asarray(audio).reshape(-1)
        if samples.dtype.kind in "iu":
            samples = samples.astype(np.float32) / 32768.0
        else:
            samples = samples.astype(np.float32)
        return samples

    def _passes_anti_spoof(self, samples: np.ndarray, sample_rate: int) -> bool:
        detector = self._anti_spoof_verifier
        if not callable(detector):
            return False
        try:
            # A detector failure or exception must never grant owner access.
            return detector(samples.copy(), sample_rate) is True
        except Exception:
            return False

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
        """Return (match, score, verified_live); fail closed without anti-spoofing."""
        try:
            from core import voice_id
            samples = self._float_audio(audio)
            quality_ok, _reason = self.check_liveness(samples, sample_rate=sample_rate)
            if not quality_ok or not self._passes_anti_spoof(samples, sample_rate):
                return False, 0.0, False
            if not voice_id.is_enabled() or not voice_id.backend_ready():
                return False, 0.0, False
            match, score = voice_id.verify(samples, role="owner")
            return bool(match), float(score), True
        except Exception:
            return False, 0.0, False
