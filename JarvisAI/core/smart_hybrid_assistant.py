"""Small orchestration layer for JARVIS Smart Hybrid chat/browser routing."""
from __future__ import annotations

from typing import Any

from core.browser_automation import BrowserAutomation
from core.hybrid_llm_router import HybridLLMRouter
from core.smart_intent_router import SmartIntentRouter, _configured_keys


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
        browser_factory: Any = BrowserAutomation,
    ):
        self.intent_router = intent_router or SmartIntentRouter()
        self.chat_router_factory = chat_router_factory
        self.browser_factory = browser_factory
        self._browser = None

    def dispatch(self, user_text: str) -> dict[str, Any]:
        request = str(user_text or "").strip()
        if not request:
            raise ValueError("A non-empty user request is required")
        route = self.intent_router.route(request)
        if route["intent"] != "BROWSER":
            router = self.chat_router_factory(
                preferred_provider="gemini",
                api_keys=_configured_keys(),
                online_check=False,
            )
            result = router.query(request)
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
