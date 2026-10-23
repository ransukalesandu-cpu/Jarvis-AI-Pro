"""Regression tests for web-search provider failures; no network calls are made."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from actions import web_search as ws


class WebSearchFallbackTests(unittest.TestCase):
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
