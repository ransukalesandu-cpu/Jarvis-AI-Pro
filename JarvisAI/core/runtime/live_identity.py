"""Voice ID enrollment/verification, owner PIN and the privacy lock.

Part of ``JarvisLive`` (JarvisAI/main.py), which inherits this mixin. The
methods were moved here verbatim; they run with ``self`` bound to the live
session object, so every attribute they use is set up in ``JarvisLive.__init__``.
"""


import asyncio
import numpy as np
import re
import secrets
import threading
import time
from core import failsoft, security, voice_id
from core.runtime.live_constants import SEND_SAMPLE_RATE


class OwnerIdentityMixin:
    """Voice ID enrollment/verification, owner PIN and the privacy lock."""

    @staticmethod
    def _voice_text_key(text: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", str(text or "").casefold()))

    def _voice_id_action(self, action: str) -> str:
        """UI callback for local Voice ID enrollment, toggle, and removal."""
        action = str(action or "").strip().lower()
        try:
            if action == "toggle":
                if voice_id.is_enabled():
                    voice_id.disable()
                    self._voice_id_enabled = False
                    self.ui.set_voice_id_enabled(False)
                    with self._voice_id_audio_lock:
                        self._voice_id_audio_chunks.clear()
                        self._voice_id_turn_audio = b""
                    return "Voice ID disabled. Sensitive actions will follow their normal confirmation policy."
                if not voice_id.is_enrolled():
                    return self._voice_id_action("enroll_owner")
                voice_id.enable()
                self._voice_id_enabled = True
                self.ui.set_voice_id_enabled(True)
                return "Voice ID enabled. Sensitive actions and spoken approvals will check your speaker profile."

            if action in ("enroll", "enroll_owner", "enroll_sister"):
                role = "sister" if action == "enroll_sister" else "owner"
                if not voice_id.backend_ready():
                    return ("Voice ID is unavailable. Install requirements-voice-id.txt, "
                            "and ensure your OS credential store is unlocked and available, "
                            "then restart JARVIS.")
                # The challenge is transcribed by the existing Live session.
                # A deliberate enrollment click may therefore wake a sleeping
                # session so the already-open mic can validate the sentence.
                self.wake(reason=f"Voice ID enrollment ({role})")
                challenge = secrets.choice((
                    "Copper leaves drift past the harbor before sunrise.",
                    "Please verify my voice before Jarvis changes anything.",
                    "A quiet silver train crosses the valley tonight.",
                    "Blue lanterns glow beside the old stone bridge.",
                ))
                with self._voice_id_enroll_lock:
                    self._voice_id_enroll_active = True
                    self._voice_id_enroll_role = role
                    self._voice_id_enroll_chunks = []
                    self._voice_id_enroll_samples = 0
                    self._voice_id_enroll_challenge = challenge
                    self._voice_id_enroll_matched = False
                    self._voice_id_enroll_transcript = ""
                    self._voice_id_enroll_candidate = None
                self.ui.show_content(
                    f"VOICE ID ENROLLMENT ({role.upper()})",
                    f"Read this sentence twice, clearly, after starting enrollment:\n\n{challenge}\n\n"
                    f"Keep the microphone close and JARVIS quiet until enrollment finishes for the {role}. "
                    "Only clear voiced audio is used; raw audio is discarded after the local profile is created. "
                    "The encryption key stays in this device's OS credential store.",
                )
                threading.Timer(
                    60.0, self._expire_voice_id_enrollment, args=(challenge,),
                ).start()
                return f"Enrollment started for {role}. Read the sentence twice, clearly: {challenge}"

            if action == "remove_sister":
                voice_id.remove_profile("sister")
                self._voice_id_enabled = voice_id.is_enabled()
                self.ui.set_voice_id_enabled(self._voice_id_enabled)
                return "Sister voice profile removed."

            if action == "remove":
                voice_id.remove_profile()
                self._voice_id_enabled = False
                self.ui.set_voice_id_enabled(False)
                with self._voice_id_audio_lock:
                    self._voice_id_audio_chunks.clear()
                    self._voice_id_turn_audio = b""
                return "Encrypted Voice ID profiles removed and speaker checks disabled."
        except Exception as exc:
            return f"Voice ID could not be updated: {type(exc).__name__}: {exc}"
        return "Unknown Voice ID action."

    def _expire_voice_id_enrollment(self, challenge: str) -> None:
        with self._voice_id_enroll_lock:
            if self._voice_id_enroll_challenge != challenge:
                return
            self._voice_id_enroll_active = False
            self._voice_id_enroll_chunks.clear()
            self._voice_id_enroll_samples = 0
            self._voice_id_enroll_candidate = None
            self._voice_id_enroll_challenge = ""
            self._voice_id_enroll_matched = False
            self._voice_id_enroll_transcript = ""
        self.ui.write_log("SEC: Voice ID enrollment expired; no profile was saved.")

    def _capture_voice_id_enrollment(self, indata, frames: int) -> None:
        """Collect clear, voiced mic chunks only; raw audio is discarded after embedding."""
        if self.ui.muted or self._phone_active:
            return
        with self._speaking_lock:
            if self._is_speaking:
                return
        data = indata.tobytes()
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if not samples.size:
            return
        rms = float(np.sqrt(np.mean(np.square(samples))))
        # Ignore silence and low-level room noise; count only useful speech
        # frames toward the enrollment duration.
        if rms < 0.0025:
            return
        ready_sample = None
        with self._voice_id_enroll_lock:
            if not self._voice_id_enroll_active:
                return
            self._voice_id_enroll_chunks.append(data)
            self._voice_id_enroll_samples += int(frames)
            # Five seconds of voiced audio gives ECAPA multiple phrases while
            # avoiding the silent tail of the recording.
            if self._voice_id_enroll_samples >= SEND_SAMPLE_RATE * 5:
                candidate = b"".join(self._voice_id_enroll_chunks)
                self._voice_id_enroll_chunks = []
                self._voice_id_enroll_samples = 0
                self._voice_id_enroll_active = False
                if self._voice_id_enroll_matched:
                    ready_sample = candidate
                    self._voice_id_enroll_challenge = ""
                    self._voice_id_enroll_matched = False
                    self._voice_id_enroll_transcript = ""
                else:
                    self._voice_id_enroll_candidate = (candidate, time.monotonic())
        if ready_sample is not None:
            self._begin_voice_id_save(ready_sample)

    def _accept_voice_id_transcript(self, transcript: str) -> None:
        normalized = self._voice_text_key(transcript)
        ready_sample = None
        with self._voice_id_enroll_lock:
            challenge = self._voice_id_enroll_challenge
            if not challenge:
                return
            self._voice_id_enroll_transcript = (
                f"{self._voice_id_enroll_transcript} {normalized}".strip()[-500:]
            )
            challenge_key = self._voice_text_key(challenge)
            if self._voice_id_enroll_transcript.count(challenge_key) >= 2:
                self._voice_id_enroll_matched = True
                candidate = self._voice_id_enroll_candidate
                if candidate and time.monotonic() - candidate[1] <= 30.0:
                    ready_sample = candidate[0]
                    self._voice_id_enroll_candidate = None
                    self._voice_id_enroll_challenge = ""
                    self._voice_id_enroll_matched = False
                    self._voice_id_enroll_transcript = ""
            elif (self._voice_id_enroll_candidate
                  and time.monotonic() - self._voice_id_enroll_candidate[1] > 30.0):
                self._voice_id_enroll_candidate = None
        if ready_sample is not None:
            self._begin_voice_id_save(ready_sample)

    def _begin_voice_id_save(self, pcm: bytes) -> None:
        with self._voice_id_enroll_lock:
            role = getattr(self, "_voice_id_enroll_role", "owner")
        def save_profile():
            try:
                voice_id.enroll(np.frombuffer(pcm, dtype=np.int16), role=role)
                self._voice_id_enabled = voice_id.is_enabled()
                self.ui.set_voice_id_enabled(self._voice_id_enabled)
                self.ui.write_log(f"SEC: Voice ID enrollment complete for {role}. Raw recording discarded; encrypted speaker profile stored locally.")
            except Exception as exc:
                self.ui.write_log(f"SEC: Voice ID enrollment failed for {role}: {type(exc).__name__}: {exc}")
        threading.Thread(target=save_profile, name="voice-id-enrollment", daemon=True).start()

    def _append_voice_id_audio(self, data: bytes) -> None:
        if not self._voice_id_enabled or not data:
            return
        samples = np.frombuffer(data, dtype=np.int16)
        if not samples.size:
            return
        rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float32) / 32768.0))))
        # Keep quiet placeholders in the ring so old speech expires by elapsed
        # microphone time instead of lingering indefinitely when the room goes
        # quiet. Only non-quiet chunks are joined into the verification sample.
        chunk = bytes(data) if rms >= 0.0025 else b""
        with self._voice_id_audio_lock:
            self._voice_id_audio_chunks.append((time.monotonic(), chunk))

    def _expire_voice_id_audio(self) -> None:
        """Advance the rolling audio window without retaining blocked audio."""
        if not self._voice_id_enabled:
            return
        with self._voice_id_audio_lock:
            self._voice_id_audio_chunks.append((time.monotonic(), b""))

    def _snapshot_voice_id_audio(self, *, new_turn: bool = False) -> None:
        if not self._voice_id_enabled:
            return
        with self._voice_id_audio_lock:
            recent = b"".join(
                chunk for _timestamp, chunk in self._voice_id_audio_chunks if chunk
            )
            self._voice_id_audio_chunks.clear()
            if new_turn:
                self._voice_id_turn_audio = recent
            elif recent:
                self._voice_id_turn_audio = (self._voice_id_turn_audio + recent)[-192000:]

    def _get_speaker_role_for_current_turn(self) -> str:
        if not self._voice_id_enabled or not voice_id.is_enabled():
            return "owner"
        with self._voice_id_audio_lock:
            pcm = self._voice_id_turn_audio
        if len(pcm) < int(SEND_SAMPLE_RATE * voice_id.MIN_AUDIO_SECONDS * 2):
            return "stranger"
        role, score = voice_id.identify_speaker(np.frombuffer(pcm, dtype=np.int16))
        return role

    def _verify_voice_id_for_current_turn(self) -> bool:
        """Require anti-spoof validation as well as the enrolled owner match."""
        manager = security.get_auth_manager()
        matched, _score, live = manager.verify_owner_voice(self._get_current_turn_audio())
        return matched is True and live is True

    def _get_current_turn_audio(self) -> bytes:
        if not hasattr(self, "_voice_id_audio_lock"):
            return b""
        with self._voice_id_audio_lock:
            return bytes(getattr(self, "_voice_id_turn_audio", b"") or b"")

    def _prompt_owner_pin(self) -> str | None:
        if hasattr(self.ui, "prompt_pin"):
            try:
                return self.ui.prompt_pin()
            except Exception as exc:
                print(f"[JARVIS] PIN prompt error: {exc}")
                return None
        return None

    def _queue_auth_state_broadcast(self) -> None:
        """Publish only non-sensitive auth state to already-paired dashboard clients."""
        try:
            manager = security.get_auth_manager()
            state = manager.get_state()
            payload = {
                "type": "auth_state",
                "state": "owner_verified" if manager.is_owner_access_allowed() else (
                    "privacy_lock" if manager.is_privacy_lock_active() else (
                        "pin_required" if manager.needs_pin() else "restricted"
                    )
                ),
                "owner_verified": manager.is_owner_access_allowed(),
                "pin_required": manager.needs_pin(),
                "privacy_lock_active": manager.is_privacy_lock_active(),
            }
            if self._dashboard is not None and self._loop is not None:
                asyncio.run_coroutine_threadsafe(self._dashboard.broadcast(payload), self._loop)
        except Exception:
            failsoft.suppress('main:JarvisLive._queue_auth_state_broadcast')

    def _handle_privacy_lock_activated(self, message: str) -> None:
        """Thread-safe callback invoked by AuthManager after it persists the lock."""
        loop = getattr(self, "_loop", None)
        if loop is None:
            try:
                self.ui.write_log("SEC: Privacy Lock activated; private output is blocked.")
            except Exception:
                failsoft.suppress('main:JarvisLive._handle_privacy_lock_activated')
            return
        try:
            asyncio.run_coroutine_threadsafe(self._publish_privacy_lock(message), loop)
        except Exception as exc:
            print(f"[Privacy Lock] Notification scheduling failed: {type(exc).__name__}")

    async def _publish_privacy_lock(self, message: str) -> None:
        self._interrupted = True
        # Stop the playback worker's private prebuffer as soon as the lock is
        # published, even if no further Live receiver event arrives.
        try:
            self._stop_playback_for_privacy_lock()
        except Exception:
            failsoft.suppress('main:JarvisLive._publish_privacy_lock')
        self._assistant_turn_pending = False
        try:
            from security.lockdown import teardown_audio_stream
            output_stream = getattr(self, "_output_stream", None)
            if output_stream is not None:
                teardown_audio_stream(output_stream)
        except Exception:
            failsoft.suppress('main:JarvisLive._publish_privacy_lock')
        phone_audio_queue = getattr(getattr(self, "_dashboard", None), "_phone_audio_queue", None)
        for queue in (getattr(self, "out_queue", None), getattr(self, "audio_in_queue", None), phone_audio_queue):
            if queue is not None:
                while True:
                    try:
                        queue.get_nowait()
                    except Exception:
                        break
        # Keep the locked UI state; playback cleanup above resets speaking
        # bookkeeping without changing the UI back to LISTENING.
        done_event = getattr(self, "_turn_done_event", None)
        if done_event is not None:
            done_event.set()
        try:
            self.ui.set_state("LOCKED")
            self.ui.write_log("SEC: Privacy Lock activated. Private audio and responses are suppressed.")
        except Exception:
            failsoft.suppress('main:JarvisLive._publish_privacy_lock')
        manager = security.get_auth_manager()
        duration = manager.cooldown_remaining()
        try:
            from notifications.alert_service import build_privacy_lock_alert, send_twilio_alert
            payload = build_privacy_lock_alert(duration, message=message)
            # Network I/O must not block the real-time voice/event loop.
            asyncio.create_task(asyncio.to_thread(send_twilio_alert, payload["message"]))
        except Exception as exc:
            print(f"[Privacy Lock] Optional SMS alert scheduling failed: {type(exc).__name__}")
            payload = {
                "event": "PRIVACY_LOCK",
                "duration": duration,
                "message": message,
                "type": "privacy_lock",
                "text": message,
                "cooldown_remaining": duration,
            }

        dashboard = getattr(self, "_dashboard", None)
        if dashboard is not None:
            try:
                # Send the privacy alert before revoking active companion sessions.
                await dashboard.broadcast(payload)
            except Exception as exc:
                print(f"[Privacy Lock] Connected-device notification failed: {type(exc).__name__}")
            finally:
                try:
                    dashboard.revoke_all_sessions()
                    sockets = list(getattr(dashboard, "_clients", ()))
                    phone_socket = getattr(dashboard, "_phone_audio_ws", None)
                    if phone_socket is not None:
                        sockets.append(phone_socket)
                    for ws in sockets:
                        try:
                            await ws.close(code=4003, reason="Privacy Lock is active")
                        except Exception:
                            failsoft.suppress('main:JarvisLive._publish_privacy_lock')
                    if hasattr(dashboard, "_clients"):
                        dashboard._clients.clear()
                    if getattr(dashboard, "_phone_audio_ws", None) is phone_socket:
                        dashboard._phone_audio_ws = None
                except Exception as exc:
                    print(f"[Privacy Lock] Session revocation failed: {type(exc).__name__}")
