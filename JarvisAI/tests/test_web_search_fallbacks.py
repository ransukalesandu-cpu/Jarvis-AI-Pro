"""Regression tests for web-search provider failures; no network calls are made."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from actions import web_search as ws


class WebSearchFallbackTests(unittest.TestCase):
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
