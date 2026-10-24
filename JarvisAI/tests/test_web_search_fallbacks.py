"""Regression tests for web-search provider failures; no network calls are made."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from actions import web_search as ws
from core import gemini as gm


class WebSearchFallbackTests(unittest.TestCase):
    def test_remote_protocol_disconnect_is_classified_as_transient(self):
        error_type = type("RemoteProtocolError", (Exception,), {})
        error = error_type("Server disconnected without sending a response")
        self.assertTrue(gm._is_transient_transport_error(error))

    def test_model_404_is_not_classified_as_transient_transport(self):
        error_type = type("ClientError", (Exception,), {})
        error = error_type("404 NOT_FOUND: model unavailable")
        self.assertFalse(gm._is_transient_transport_error(error))

    def test_grounded_call_retries_remote_protocol_error_with_fresh_client(self):
        error_type = type("RemoteProtocolError", (Exception,), {})
        first_client = SimpleNamespace(models=Mock())
        first_client.models.generate_content.side_effect = error_type(
            "Server disconnected without sending a response"
        )
        expected_response = object()
        second_client = SimpleNamespace(models=Mock())
        second_client.models.generate_content.return_value = expected_response

        with patch.object(gm, "_resolve_ladder", return_value=("gemini-3.5-flash-lite",)), \
                patch.object(gm, "_FREE_TIER", False), \
                patch.object(gm, "_cooling", return_value=False), \
                patch.object(gm, "api_key", return_value="test-key"), \
                patch.object(gm, "client", side_effect=[first_client, second_client]) as client_factory:
            response = gm.call("find current headlines", tier=gm.SEARCH)

        self.assertIs(response, expected_response)
        self.assertEqual(client_factory.call_count, 2)
        first_client.models.generate_content.assert_called_once()
        second_client.models.generate_content.assert_called_once()

    def test_free_search_ladder_uses_current_model_ids(self):
        with patch.object(gm, "_FREE_TIER", True):
            ladder = gm._resolve_ladder(gm.SEARCH)
        self.assertEqual(
            ladder,
            ("gemini-3.5-flash-lite", "gemini-3.8-flash"),
        )
        self.assertNotIn("gemini-2.5-flash-lite", ladder)
        self.assertNotIn("gemini-2.5-flash", ladder)

    def test_paid_search_ladder_keeps_current_model_ids(self):
        with patch.object(gm, "_FREE_TIER", False):
            ladder = gm._resolve_ladder(gm.SEARCH)
        self.assertEqual(
            ladder,
            ("gemini-3.8-flash", "gemini-3.5-flash-lite"),
        )

    @staticmethod
    def _run_bounded_inline(fn, timeout, label="task"):
        # These tests exercise fallback selection, not Python's thread scheduler.
        # Inline execution keeps the provider calls deterministic and offline.
        try:
            return fn()
        except Exception:
            return None

    def test_sri_lanka_news_uses_grounded_fallback_after_publisher_timeout(self):
        no_headlines = (
            "No Sri Lankan headlines were found from Newsfirst or Ada Derana right now."
        )
        grounded = (
            "Sri Lankan headlines verified from Google Search. "
            "Newsfirst reported a current update with publication date and source URL. "
            "Ada Derana also published a separate current update with its source URL."
        )
        with patch.object(ws, "_run_bounded", side_effect=self._run_bounded_inline), \
                patch.object(ws, "_sri_lanka_news", return_value=no_headlines), \
                patch.object(ws, "_gemini_search", return_value=grounded) as gemini:
            result = ws._news(
                "Sri Lankan local news from Newsfirst and Ada Derana in Sinhala and English"
            )
        self.assertEqual(result, grounded)
        gemini.assert_called_once()
        self.assertIn("Google Search", gemini.call_args.args[0])
        self.assertIn("Newsfirst", gemini.call_args.args[0])

    def test_direct_publisher_fallback_works_without_gemini_search(self):
        no_headlines = (
            "No Sri Lankan headlines were found from Newsfirst or Ada Derana right now."
        )
        direct_news = (
            "Sri Lankan local news — direct publisher pages\n\n"
            "Newsfirst — English\n• Verified headline from publisher"
        )
        with patch.object(ws, "_run_bounded", side_effect=self._run_bounded_inline), \
                patch.object(ws, "_sri_lanka_news", return_value=no_headlines), \
                patch.object(ws, "_direct_sri_lanka_news", return_value=direct_news), \
                patch.object(ws, "_gemini_search") as gemini:
            result = ws._news("Sri Lankan local news")
        self.assertEqual(result, direct_news)
        gemini.assert_not_called()

    def test_direct_publisher_fallback_extracts_only_allowlisted_https_links(self):
        def fake_get(url, **_kwargs):
            host = ws.urlparse(url).hostname or ""
            page_title = host.replace(".", " ").title()
            html = (
                "<html><body><article><h2><a href='https://"
                + host
                + "/news/example-headline'>"
                + page_title
                + " verified current headline with enough title text</a></h2>"
                "<p>Short publisher summary.</p></article>"
                "<article><h2><a href='https://external.example/fake'>"
                "External fake headline should be rejected by the allowlist"
                "</a></h2></article></body></html>"
            )
            return SimpleNamespace(
                url=url,
                text=html,
                raise_for_status=lambda: None,
            )

        with patch("requests.get", side_effect=fake_get):
            result = ws._direct_sri_lanka_news()
        self.assertIn("verified current headline", result)
        self.assertIn("https://www.newsfirst.lk/news/example-headline", result)
        self.assertNotIn("external.example", result)

    def test_sri_lanka_news_returns_clear_message_if_grounded_fallback_fails(self):
        no_headlines = (
            "No Sri Lankan headlines were found from Newsfirst or Ada Derana right now."
        )
        with patch.object(ws, "_run_bounded", side_effect=self._run_bounded_inline), \
                patch.object(ws, "_sri_lanka_news", return_value=no_headlines), \
                patch.object(ws, "_gemini_search", side_effect=RuntimeError("quota exhausted")):
            result = ws._news("Sri Lankan local news")
        self.assertIn("could not be fetched right now", result)
        self.assertIn("providers timed out", result)

    def test_ddg_news_can_skip_duplicate_text_fallback(self):
        class FakeDDGS:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def news(self, *_args, **_kwargs):
                raise TimeoutError("provider timed out")

        with patch.object(ws, "_get_ddgs", return_value=FakeDDGS), \
                patch.object(ws, "_ddg_search") as text_fallback:
            self.assertEqual(ws._ddg_news("test query", fallback_to_text=False), [])
        text_fallback.assert_not_called()

    def test_image_search_returns_empty_gallery_when_provider_fails(self):
        with patch.object(ws, "_get_ddgs", side_effect=RuntimeError("network down")):
            self.assertEqual(ws._ddg_images("test query"), [])

    def test_research_returns_actionable_message_when_both_providers_fail(self):
        with patch.object(ws, "_gemini_search", side_effect=RuntimeError("quota exhausted")), \
                patch.object(ws, "_ddg_search", side_effect=RuntimeError("provider blocked")):
            result = ws._research("test topic")
        self.assertIn("temporarily unavailable", result)
        self.assertIn("test topic", result)
        self.assertIn("internet access", result)

    def test_price_lookup_returns_actionable_message_when_both_providers_fail(self):
        with patch.object(ws, "_gemini_search", side_effect=RuntimeError("quota exhausted")), \
                patch.object(ws, "_ddg_search", side_effect=RuntimeError("provider blocked")):
            result = ws._price("test product")
        self.assertIn("temporarily unavailable", result)
        self.assertIn("test product", result)
        self.assertIn("API quota", result)

    def test_handler_records_unexpected_error_without_exposing_secret(self):
        with patch.object(ws, "_search", side_effect=RuntimeError("api_key=super-secret")):
            with patch.object(ws.self_repair, "record_error", wraps=ws.self_repair.record_error) as record:
                result = ws.web_search({"query": "test"})
            self.assertIn("Search failed:", result)
            self.assertNotIn("super-secret", result)
            record.assert_called_once()

    def test_gemini_headlines_handles_empty_candidates(self):
        with patch("core.gemini.call", return_value=SimpleNamespace(candidates=[])):
            self.assertEqual(ws._gemini_headlines(), ([], ""))

    def test_gemini_headlines_handles_missing_content(self):
        with patch("core.gemini.call", return_value=SimpleNamespace(candidates=[SimpleNamespace(content=None)])):
            self.assertEqual(ws._gemini_headlines(), ([], ""))


if __name__ == "__main__":
    unittest.main()
