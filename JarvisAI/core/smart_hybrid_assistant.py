"""Small orchestration layer for JARVIS Smart Hybrid chat/browser routing."""
from __future__ import annotations

from typing import Any

from core.brain_engine import BrainEngine
from core.browser_automation import BrowserAutomation
from core.hybrid_llm_router import HybridLLMRouter
from core.smart_intent_router import SmartIntentRouter


class SmartHybridAssistant:
    """Dispatch a request without changing the Gemini Live audio pipeline.

    Browser commands are deliberately explicit: 'search the web for ...',
    'open https://...', or 'click ...'. General chat is handled by the existing
    HybridLLMRouter. A caller/UI should run dispatch off the Qt/audio thread.
    """

    def __init__(
        self,
        *,
        intent_router: Any | None = None,
        chat_router_factory: Any = HybridLLMRouter,
        brain_engine_factory: Any = BrainEngine,
        browser_factory: Any = BrowserAutomation,
    ):
        self.intent_router = intent_router or SmartIntentRouter()
        self.chat_router_factory = chat_router_factory
        self.brain_engine_factory = brain_engine_factory
        self.browser_factory = browser_factory
        self._browser = None
        self._chat_history: list[dict[str, str]] = []

    def dispatch(self, user_text: str) -> dict[str, Any]:
        request = str(user_text or "").strip()
        if not request:
            raise ValueError("A non-empty user request is required")
        route = self.intent_router.route(request)
        if route["intent"] != "BROWSER":
            try:
                from memory.config_manager import get_memory_provider_access_enabled
                memory_enabled = bool(get_memory_provider_access_enabled())
            except Exception:
                memory_enabled = False
            brain = self.brain_engine_factory(
                router_factory=self.chat_router_factory,
                memory_enabled=memory_enabled,
            )
            result = brain.respond(
                request,
                conversation_history=self._chat_history,
                memory_enabled=memory_enabled,
            )
            answer = str(result.get("text") or "").strip()
            if answer:
                self._chat_history.extend([
                    {"role": "user", "content": request},
                    {"role": "assistant", "content": answer},
                ])
                self._chat_history = self._chat_history[-12:]
            return {"intent": "CHAT", "result": result}

        lowered = request.lower()
        browser = self._get_browser()
        if lowered.startswith("search the web for "):
            result = browser.search_web(request[len("search the web for "):])
        elif lowered.startswith("open "):
            result = browser.navigate(request[5:].strip())
        elif lowered.startswith("click "):
            result = browser.click_link(request[6:].strip())
        else:
            return {
                "intent": "BROWSER",
                "needs_clarification": True,
                "message": "Please say: 'search the web for ...', 'open https://...', or 'click ...'.",
            }
        return {"intent": "BROWSER", "result": result}

    def _get_browser(self):
        if self._browser is None:
            self._browser = self.browser_factory()
        return self._browser

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
