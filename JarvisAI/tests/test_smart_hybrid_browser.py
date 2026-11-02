import unittest
from unittest.mock import Mock, patch
import socket

from core.browser_automation import BrowserAutomation, BrowserAutomationError, validate_public_url
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

    def test_intent_classifier_does_not_force_gemini_model_on_other_provider(self):
        router = Mock()
        router.query.return_value = {
            "text": '{"intent":"BROWSER","reason":"explicit navigation"}'
        }
        classifier = SmartIntentRouter(router_factory=Mock(return_value=router))
        with patch("core.smart_intent_router._configured_preferred_provider", return_value="openai"), \
             patch("core.smart_intent_router._configured_keys", return_value={"openai": "test-key"}):
            result = classifier.route("open https://example.com")

        self.assertEqual(result["intent"], "BROWSER")
        self.assertNotIn("model", router.query.call_args.kwargs)

    def test_empty_request_rejected(self):
        with self.assertRaises(ValueError):
            SmartIntentRouter().route(" ")

    def test_public_url_validation(self):
        with patch("core.browser_automation.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 0))
        ]):
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

    def test_chat_route_uses_brain_engine_with_existing_hybrid_router(self):
        intent = Mock()
        intent.route.return_value = {"intent": "CHAT", "reason": "question"}
        router = Mock()
        router.configured_key_status.return_value = {"gemini": True, "ollama": False}
        router.query.return_value = {"text": "hello", "provider": "gemini", "model": "test"}
        assistant = SmartHybridAssistant(intent_router=intent, chat_router_factory=Mock(return_value=router))
        with patch("memory.config_manager.get_memory_provider_access_enabled", return_value=False):
            result = assistant.dispatch("hello")
        router.query.assert_called_once()
        prompt = router.query.call_args.args[0]
        self.assertIn("[CURRENT USER REQUEST]", prompt)
        self.assertIn("hello", prompt)
        self.assertIn("[JARVIS BRAIN PROTOCOL v1]", router.query.call_args.kwargs["system_prompt"])
        self.assertEqual(result["intent"], "CHAT")
        self.assertEqual(result["result"]["text"], "hello")

    def test_click_link_navigates_only_a_validated_href_without_click_handlers(self):
        browser = BrowserAutomation()
        browser._page = Mock()
        browser._page.url = "https://example.com/start"
        browser._page.get_by_role.return_value.first.get_attribute.return_value = "/help"
        browser.navigate = Mock(return_value={"title": "Help"})
        self.assertEqual(browser.click_link("Help"), {"title": "Help"})
        browser._page.get_by_role.assert_called_once_with("link", name="Help", exact=False)
        browser.navigate.assert_called_once_with("https://example.com/help")
        browser._page.get_by_text.assert_not_called()
        browser._page.get_by_role.return_value.first.click.assert_not_called()

    def test_invalid_navigation_does_not_open_browser(self):
        browser = BrowserAutomation()
        browser.open = Mock()
        with self.assertRaises(BrowserAutomationError):
            browser.navigate("javascript:alert(1)")
        browser.open.assert_not_called()

    def test_legacy_loopback_hosts_are_rejected_after_resolution(self):
        # These forms are rejected by ipaddress but resolved as loopback by libc.
        for host in ('127.1', '2130706433', '0x7f.0.0.1'):
            with self.subTest(host=host), self.assertRaises(BrowserAutomationError):
                validate_public_url('http://' + host)

    def test_private_and_mixed_dns_results_are_rejected_in_request_guard(self):
        for addresses in (['192.168.1.2'], ['93.184.216.34', '10.0.0.1'], ['::1']):
            infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 0)) for ip in addresses]
            with self.subTest(addresses=addresses), \
                 patch('core.browser_automation.socket.getaddrinfo', return_value=infos):
                route = Mock()
                route.request.url = 'https://public-looking.example/path'
                BrowserAutomation._guard_request(route)
                route.abort.assert_called_once_with()
                route.continue_.assert_not_called()

    def test_dns_failure_fails_closed(self):
        with patch('core.browser_automation.socket.getaddrinfo', side_effect=socket.gaierror('unresolved')):
            with self.assertRaises(BrowserAutomationError):
                validate_public_url('https://unresolved.example')

    def test_browser_request_guard_rejects_write_methods(self):
        route = Mock()
        route.request.method = "POST"
        route.request.url = "https://public.example/submit"
        with patch("core.browser_automation.validate_public_url") as validate:
            BrowserAutomation._guard_request(route)
        route.abort.assert_called_once_with()
        route.continue_.assert_not_called()
        validate.assert_not_called()

    def test_new_browser_worker_restores_last_public_url_without_profile_state(self):
        page = Mock()
        context = Mock()
        context.new_page.return_value = page
        browser_instance = Mock()
        browser_instance.new_context.return_value = context
        playwright = Mock()
        playwright.chromium.launch.return_value = browser_instance
        manager = Mock()
        manager.start.return_value = playwright
        browser = BrowserAutomation()
        browser._last_url = "https://example.com/previous"

        with patch("playwright.sync_api.sync_playwright", return_value=manager), \
             patch("core.browser_automation.validate_public_url", return_value=browser._last_url):
            browser.open()

        page.goto.assert_called_once_with(
            "https://example.com/previous",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        browser.close()


    def test_cdp_guard_validates_redirect_before_continuing(self):
        browser = BrowserAutomation()
        browser._cdp = Mock()
        event = {
            "requestId": "redirect-1",
            "request": {"url": "https://public.example/start", "method": "GET"},
            "redirectUrl": "https://public.example/final",
        }
        with patch("core.browser_automation.validate_public_url", side_effect=lambda value: value):
            browser._guard_cdp_request(event)
        browser._cdp.send.assert_called_once_with(
            "Fetch.continueRequest", {"requestId": "redirect-1"}
        )

    def test_cdp_guard_blocks_private_redirect_before_continuing(self):
        browser = BrowserAutomation()
        browser._cdp = Mock()
        event = {
            "requestId": "redirect-2",
            "request": {"url": "https://public.example/start", "method": "GET"},
            "redirectUrl": "http://127.0.0.1/admin",
        }
        def validate(value):
            if "127.0.0.1" in value:
                raise BrowserAutomationError("Private destination")
            return value
        with patch("core.browser_automation.validate_public_url", side_effect=validate):
            browser._guard_cdp_request(event)
        browser._cdp.send.assert_called_once_with(
            "Fetch.failRequest",
            {"requestId": "redirect-2", "errorReason": "BlockedByClient"},
        )

    def test_navigation_persists_final_validated_url(self):
        browser = BrowserAutomation()
        browser._page = Mock()
        browser._page.url = "https://public.example/final"
        browser.open = Mock()
        browser.read_page = Mock(return_value={"title": "Final"})
        with patch("core.browser_automation.validate_public_url", side_effect=lambda value: value):
            result = browser.navigate("https://public.example/start")
        self.assertEqual(result, {"title": "Final"})
        self.assertEqual(browser._last_url, "https://public.example/final")


if __name__ == "__main__":
    unittest.main()
