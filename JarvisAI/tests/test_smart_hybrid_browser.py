import unittest
from unittest.mock import Mock

from core.browser_automation import BrowserAutomationError, validate_public_url
from core.smart_intent_router import SmartIntentRouter, _extract_json
from core.smart_hybrid_assistant import SmartHybridAssistant


class SmartHybridBrowserTests(unittest.TestCase):
    def test_json_classifier_accepts_json_fence(self):
        self.assertEqual(_extract_json('```json\n{"intent":"BROWSER"}\n```'), {"intent": "BROWSER"})

    def test_invalid_intent_falls_back_to_chat(self):
        router = Mock()
        router.query.return_value = {"text": '{"intent":"DELETE","reason":"bad"}'}
        classifier = SmartIntentRouter(router_factory=Mock(return_value=router))
        result = classifier.route("open a website")
        self.assertEqual(result["intent"], "CHAT")

    def test_empty_request_rejected(self):
        with self.assertRaises(ValueError):
            SmartIntentRouter().route(" ")

    def test_public_url_validation(self):
        self.assertEqual(validate_public_url("https://example.com"), "https://example.com")
        for url in ("file:///etc/passwd", "http://localhost", "http://127.0.0.1", "https://user:pass@example.com"):
            with self.subTest(url=url), self.assertRaises(BrowserAutomationError):
                validate_public_url(url)

    def test_browser_route_calls_search_tool(self):
        intent = Mock()
        intent.route.return_value = {"intent": "BROWSER", "reason": "search"}
        browser = Mock()
        browser.search_web.return_value = {"title": "Search", "text": "results"}
        assistant = SmartHybridAssistant(intent_router=intent, browser_factory=Mock(return_value=browser))
        result = assistant.dispatch("search the web for Python")
        browser.search_web.assert_called_once_with("Python")
        self.assertEqual(result["intent"], "BROWSER")

    def test_chat_route_uses_existing_hybrid_router(self):
        intent = Mock()
        intent.route.return_value = {"intent": "CHAT", "reason": "question"}
        router = Mock()
        router.query.return_value = {"text": "hello", "provider": "gemini"}
        assistant = SmartHybridAssistant(intent_router=intent, chat_router_factory=Mock(return_value=router))
        result = assistant.dispatch("hello")
        router.query.assert_called_once_with("hello")
        self.assertEqual(result["intent"], "CHAT")


if __name__ == "__main__":
    unittest.main()
