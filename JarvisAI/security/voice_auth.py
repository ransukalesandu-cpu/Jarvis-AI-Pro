"""
JarvisAI Security — Voice Auth

Voice embedding verification module for biometric speaker authorization.
"""

from typing import Optional


class VoiceAuthenticator:
    """Provides voice biometric authorization checks."""

    def __init__(self):
        self._enrolled_embedding = None

    def verify_embedding(self, embedding: list[float], threshold: float = 0.75) -> bool:
        """Verify candidate speaker embedding against enrolled profile."""
        if self._enrolled_embedding is None or not embedding:
            return False
        # Cosine similarity check or L2 distance
        try:
            dot = sum(a * b for a, b in zip(self._enrolled_embedding, embedding))
            norm_a = sum(a * a for a in self._enrolled_embedding) ** 0.5
            norm_b = sum(b * b for b in embedding) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return False
            sim = dot / (norm_a * norm_b)
            return sim >= threshold
        except Exception:
            return False

    def enroll_embedding(self, embedding: list[float]) -> None:
        """Set active speaker profile embedding."""
        self._enrolled_embedding = list(embedding)
