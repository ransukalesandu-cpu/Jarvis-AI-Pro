"""Regression tests for web-search provider failures; no network calls are made."""
from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()
