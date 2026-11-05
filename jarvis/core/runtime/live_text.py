"""Typed commands, hybrid text fallback, agent routing and spoken-language memory.

Part of ``JarvisLive`` (jarvis/main.py), which inherits this mixin. The
methods were moved here verbatim; they run with ``self`` bound to the live
session object, so every attribute they use is set up in ``JarvisLive.__init__``.
"""


import asyncio
import re
from jarvis.core import failsoft, security
from jarvis.memory.config_manager import get_memory_provider_access_enabled
from jarvis.memory.memory_manager import load_memory, update_memory


class TextCommandMixin:
    """Typed commands, hybrid text fallback, agent routing and spoken-language memory."""

    def _on_text_command(self, text: str):
        # Owner PIN/password input is intercepted locally and is never sent to
        # Gemini, added to conversation history, or written to logs.
        manager = security.get_auth_manager()
        if manager.is_privacy_lock_active():
            return
        from jarvis.core.guest_session import get_guest_service
        guest = get_guest_service().handle_typed_text(text, manager.needs_pin())
        if guest is not None:
            ok, message = guest
            self._interrupted = False if ok else self._interrupted
            try:
                self.ui.write_log("SEC: Owner signed in." if ok else "SEC: Owner credential was not accepted.")
                if ok and message:
                    self.__dict__.setdefault("_announcements", __import__("collections").deque(maxlen=20)).append(f"[{message}] Tell the owner briefly.")
            except Exception:
                failsoft.suppress('main:JarvisLive._on_text_command')
            return
        if manager.needs_pin():
            accepted = manager.verify_pin(str(text or "").strip())
            if accepted:
                self._interrupted = False
                self._queue_auth_state_broadcast()
                try:
                    self.ui.write_log("SEC: Owner credential verified.")
                except Exception:
                    failsoft.suppress('main:JarvisLive._on_text_command')
            elif not manager.is_privacy_lock_active():
                try:
                    self.ui.write_log("SEC: Owner credential was not accepted.")
                except Exception:
                    failsoft.suppress('main:JarvisLive._on_text_command')
            return
        if manager.is_silent():
            return
        # Respect wake-word sleep before either the Live path or text fallback.
        # A disconnected Live session must not bypass the existing wake/security gates.
        if not self._awake:
            wake_hint = "clap twice or tap WAKE NOW"
            if self._wake_enabled:
                wake_hint = "say 'Hey Jarvis', " + wake_hint
            self.ui.write_log(f"SYS: I'm asleep — {wake_hint} first.")
            return
        # Autonomous-task commands (start / stop / pause / resume / status /
        # report) are answered locally so they keep working while Live is busy,
        # rate-limited or disconnected. Anything unrelated returns None and the
        # sentence continues to the model unchanged.
        agent_reply = self._route_agent_text(str(text or "").strip())
        if agent_reply is not None:
            self._interrupted = False
            try:
                self.ui.write_log(f"JARVIS: {agent_reply}")
            except Exception:
                failsoft.suppress("main:_on_text_command")
            if self._loop and self.session:
                self.speak(agent_reply)
            return
        if not self._loop or not self.session:
            self._start_hybrid_text_fallback(str(text or "").strip())
            return
        self._interrupted = False
        security.mark_user_turn_started(voice_verified=True)
        with self._voice_id_audio_lock:
            self._voice_id_turn_audio = b""
            self._voice_id_audio_chunks.clear()
            self._voice_id_audio_turn_active = False
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def _route_agent_text(self, text: str) -> str | None:
        """Answer an autonomous-task command locally; None if it is not one."""
        if not text:
            return None
        try:
            from jarvis.agent.integration import get_service

            service = get_service()
        except Exception:
            return None
        try:
            from jarvis.agent.voice import VoiceCommandRouter

            command = VoiceCommandRouter().parse(text)
            if command is None:
                return None
            # Only intercept clearly agent-shaped sentences. A running task makes
            # stop/pause/resume/status/report meaningful even without a prefix.
            if command.action == "run" and service.runner.active_task is not None:
                return ("I'm already working on a task. Say stop if you want me "
                        "to switch.")
            return service.handle_voice(text)
        except Exception as exc:
            try:
                self.ui.write_log(f"AGENT: local command failed: {type(exc).__name__}")
            except Exception:
                failsoft.suppress("main:_route_agent_text")
            return None

    @staticmethod
    def _normalize_briefing_language(value: str) -> str:
        text = str(value or "").strip().casefold()
        return "Sinhala" if "sinh" in text or "සිංහල" in text else "English"

    def _load_last_spoken_language(self) -> str:
        if not get_memory_provider_access_enabled():
            return "Sinhala"
        memory = load_memory()
        preferences = memory.get("preferences", {})
        preferences = preferences if isinstance(preferences, dict) else {}
        remembered = preferences.get("last_spoken_language", {})
        if isinstance(remembered, dict):
            remembered = remembered.get("value", "")
        if remembered:
            return self._normalize_briefing_language(remembered)

        identity = memory.get("identity", {})
        identity = identity if isinstance(identity, dict) else {}
        language = identity.get("language", {})
        if isinstance(language, dict):
            language = language.get("value", "")
        if language:
            return self._normalize_briefing_language(language)

        sessions = memory.get("sessions", [])
        if isinstance(sessions, list) and sessions:
            return self._normalize_briefing_language(sessions[-1].get("language", "Sinhala"))
        return "Sinhala"

    def _remember_spoken_language(self, text: str) -> None:
        """Persist a briefing-language preference only after an explicit request."""
        spoken = str(text or "").strip()
        if not spoken:
            return
        explicit_request = bool(re.search(
            r"\b(?:speak|talk|reply|answer|respond|use|switch|change|keep)\b"
            r".{0,48}\b(?:in\s+)?(?:sinhala|english|singlish)\b",
            spoken,
            re.IGNORECASE,
        )) or bool(re.search(
            r"(?:සිංහලෙන්|ඉංග්‍රීසියෙන්).{0,48}(?:කතා කරන්න|පිළිතුරු දෙන්න|උත්තර දෙන්න|භාවිතා කරන්න)",
            spoken,
        ))
        if not explicit_request:
            return
        if re.search(r"\bsinglish\b", spoken, re.IGNORECASE):
            language = "Sinhala"
        else:
            sinhala_count = len(re.findall(r"[\u0D80-\u0DFF]", spoken))
            latin_count = len(re.findall(r"[A-Za-z]", spoken))
            if sinhala_count >= max(2, latin_count * 0.35):
                language = "Sinhala"
            elif latin_count >= max(3, sinhala_count * 1.5):
                language = "English"
            else:
                return
        if language == self._last_spoken_language:
            return
        self._last_spoken_language = language
        update_memory({"preferences": {"last_spoken_language": {"value": language}}})
        print(f"[Memory] Explicit briefing language preference saved: {language}")

    def _route_holo_news_voice(self, text: str) -> bool:
        """Route explicit publisher/Holo open requests to the native Holo stage."""
        spoken = re.sub(r"\s+", " ", str(text or "").casefold()).strip()
        if not re.search(r"\b(open|show|pull up)\b", spoken):
            return False
        source = ""
        if re.search(r"\b(news\s*first|newsfirst)\b", spoken):
            source = "newsfirst"
        elif re.search(r"\b(ada\s*derana|adaderana)\b", spoken):
            source = "adaderana"
        else:
            holo_open = bool(re.search(
                r"\b(open|show|pull up)\s+(it|that|this|the (?:article|story|headline))\b",
                spoken,
            ))
            if not holo_open or not getattr(self.ui, "holo_is_fullscreen", False):
                return False
        try:
            self.ui.open_latest_holo_news(source)
            self.ui.write_log("SYS: Opening the requested news page in the Holo display.")
            return True
        except Exception as exc:
            print(f"[Holo] Could not route the spoken news request: {exc}")
            return False
