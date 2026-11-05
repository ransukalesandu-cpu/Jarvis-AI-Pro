"""Optional embedding layer: cache, scoring, fail-soft, retrieval integration."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.memory import vector_index as vi

WORDS = ["invoice", "billing", "payment", "pizza", "dinner"]


def fake_embed(texts):
    """Tiny deterministic 'semantic' space: billing words share a direction."""
    out = []
    for t in texts:
        low = t.lower()
        money = sum(w in low for w in ("invoice", "billing", "payment", "pay"))
        food = sum(w in low for w in ("pizza", "dinner", "eat"))
        out.append([float(money), float(food), 0.1])
    return out


class VectorIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "v.sqlite3"

    def test_cosine_basics(self):
        self.assertAlmostEqual(vi.cosine([1, 0], [1, 0]), 1.0)
        self.assertEqual(vi.cosine([1, 0], [0, 1]), 0.0)
        self.assertEqual(vi.cosine([], [1]), 0.0)
        self.assertEqual(vi.cosine([0, 0], [0, 0]), 0.0)

    def test_backfill_caches_and_does_not_reembed(self):
        calls = []
        def emb(texts):
            calls.append(list(texts)); return fake_embed(texts)
        self.assertEqual(vi.backfill(["pay the invoice", "pizza dinner"], embedder=emb, path=self.path), 2)
        self.assertEqual(vi.backfill(["pay the invoice", "pizza dinner"], embedder=emb, path=self.path), 0)
        self.assertEqual(len(calls), 1)

    def test_scores_rank_by_meaning_not_words(self):
        texts = {"a": "billing deadline is Friday", "b": "pizza for dinner"}
        vi.backfill(list(texts.values()), embedder=fake_embed, path=self.path)
        scores = vi.score_candidates("when do I pay the invoice", texts, embedder=fake_embed, path=self.path)
        self.assertGreater(scores["a"], vi.VECTOR_ONLY_THRESHOLD)
        self.assertLess(scores["b"], 0.3)

    def test_disabled_without_flag_sends_nothing(self):
        def boom(_):
            raise AssertionError("must not embed when disabled")
        with patch.dict(os.environ, {"JARVIS_MEMORY_EMBEDDINGS": ""}):
            self.assertEqual(vi.score_candidates("q", {"a": "text"}, path=self.path), {})
            self.assertFalse(vi.enabled())
        with patch.dict(os.environ, {"JARVIS_MEMORY_EMBEDDINGS": "1"}):
            self.assertTrue(vi.enabled())

    def test_embedder_failure_falls_back_to_empty(self):
        def broken(_):
            raise RuntimeError("network down")
        self.assertEqual(vi.score_candidates("q", {"a": "t"}, embedder=broken, path=self.path), {})
        self.assertEqual(vi.backfill(["x"], embedder=broken, path=self.path), 0)

    def test_uncached_memories_are_skipped_not_embedded_inline(self):
        calls = []
        def emb(texts):
            calls.append(list(texts)); return fake_embed(texts)
        scores = vi.score_candidates("invoice", {"a": "never cached billing"}, embedder=emb, path=self.path)
        self.assertEqual(scores, {})
        self.assertEqual(calls, [["invoice"]])          # only the query was embedded


class RetrievalIntegrationTests(unittest.TestCase):
    def test_vector_only_hit_surfaces_and_flag_off_is_unchanged(self):
        from jarvis.memory import retrieval_engine as re_
        mem = {"memories": [
            {"id": "m1", "type": "semantic", "content": "billing deadline is Friday", "status": "active",
             "privacy_class": "personal", "confidence": .9, "importance": .8, "source": "user_stated",
             "verification_status": "user_confirmed"},
            {"id": "m2", "type": "semantic", "content": "pizza for dinner", "status": "active",
             "privacy_class": "personal", "confidence": .9, "importance": .8, "source": "user_stated",
             "verification_status": "user_confirmed"}], "memory_links": []}
        common = dict(log_usage=False, min_relevance=0.0)
        with patch.object(re_, "load_memory", return_value=mem), \
             patch("jarvis.memory.memory_lifecycle.expire_due"), \
             patch("jarvis.memory.memory_store.fts_candidates", return_value=[]):
            with patch("jarvis.memory.vector_index.score_candidates", return_value={}):
                base = [r["id"] for r in re_.retrieve("when do I pay the invoice", **common)]
            with patch("jarvis.memory.vector_index.score_candidates", return_value={"m1": 0.9, "m2": 0.1}):
                boosted = [r["id"] for r in re_.retrieve("when do I pay the invoice", **common)]
        self.assertNotIn("m1", base)
        self.assertEqual(boosted[0], "m1")
        self.assertNotIn("m2", boosted)


if __name__ == "__main__":
    unittest.main()
