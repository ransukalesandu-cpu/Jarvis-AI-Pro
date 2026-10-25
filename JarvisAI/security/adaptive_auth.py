"""Adaptive Authentication Manager for JARVIS.

Orchestrates the step-up adaptive authentication sequence for sensitive commands:
1. Voice verification against enrolled owner voice profile.
2. Face verification via webcam capture against enrolled owner face profile (if voice fails/uncertain).
3. Owner PIN / password verification (if face fails/uncertain).
4. Rejection and fail-closed locking if all steps fail.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional, Tuple

from core import voice_id
from security import face_auth
from security.auth_manager import AuthManager, FULL_ACCESS_MODE, RESTRICTED_MODE, CHALLENGE_MODE, PRIVACY_LOCK


class AdaptiveAuthManager:
    """Coordinates step-up verification across Voice ID, Face ID, and PIN."""

    def __init__(self, auth_manager: AuthManager):
        self.auth_manager = auth_manager
        self._lock = threading.RLock()

    def authenticate_sensitive_command(
        self,
        audio_sample=None,
        cam_index: int = 0,
        pin: Optional[str] = None,
        pin_prompt_callback: Optional[Callable[[], Optional[str]]] = None,
    ) -> Tuple[bool, str, str]:
        """Execute step-up authentication sequence for a sensitive command.

        Returns (success: bool, method_used: str, message: str)
        """
        if self.auth_manager.is_owner_access_allowed():
            method = self.auth_manager.get_auth_method() or "session"
            return True, method, f"Session already authenticated as owner via {method}."

        if self.auth_manager.is_privacy_lock_active():
            return False, "none", "Privacy Lock is active. Sensitive operations are blocked."

        # Step 1: Voice verification
        if audio_sample is not None and voice_id.is_enrolled("owner"):
            try:
                verified, score = voice_id.verify(audio_sample, role="owner")
                if verified:
                    self.auth_manager.grant_owner_access("voice")
                    return True, "voice", f"Voice verification succeeded (score: {score:.2f})."
            except Exception as exc:
                print(f"[AdaptiveAuth] Voice verification error: {exc}")

        # Step 2: Face verification (disabled as authorization method until reliable verification is available)
        if face_auth.is_authorization_enabled() and face_auth.is_enrolled("owner"):
            try:
                face_matched, face_score, face_msg = face_auth.capture_and_verify(
                    cam_index=cam_index, role="owner", liveness_check=True
                )
                if face_matched:
                    self.auth_manager.grant_owner_access("face")
                    return True, "face", f"Face verification succeeded (score: {face_score:.2f})."
            except Exception as exc:
                print(f"[AdaptiveAuth] Face verification error: {exc}")

        # Step 3: PIN / password verification
        if self.auth_manager.is_pin_enrolled():
            trial_pin = pin
            if trial_pin is None and pin_prompt_callback is not None:
                try:
                    trial_pin = pin_prompt_callback()
                except Exception as exc:
                    print(f"[AdaptiveAuth] PIN prompt callback failed: {exc}")

            if trial_pin is not None:
                pin_valid = self.auth_manager.verify_pin(trial_pin)
                if pin_valid:
                    return True, "pin", "PIN verification succeeded."
                else:
                    return False, "pin", "Incorrect PIN entered."

        # Step 4: Fallback rejection
        self.auth_manager.set_state(RESTRICTED_MODE)
        return False, "none", "Step-up authentication failed across all available methods. Sensitive command locked."
