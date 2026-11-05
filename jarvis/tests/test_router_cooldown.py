"""Provider cooldown: a repeatedly failing provider is skipped for a while."""
from __future__ import annotations

import unittest

from jarvis.core.hybrid_llm_router import HybridLLMRouter


class CooldownTests(unittest.TestCase):
    def make(self):
        router = HybridLLMRouter(api_keys={"gemini": "k", "groq": "k"}, online_check=False,
                                 preferred_provider="gemini")
        self.now = [1000.0]
        router._clock = lambda: self.now[0]
        self.calls: list[str] = []
        self.gemini_ok = False

        def gemini(prompt, system, **kw):
            self.calls.append("gemini")
            if not self.gemini_ok:
                raise RuntimeError("down")
            return {"text": "from gemini", "model": "g"}

        def groq(prompt, system, **kw):
            self.calls.append("groq")
            return {"text": "from groq", "model": "q"}

        router.providers = {**router.providers, "gemini": gemini, "groq": groq}
        router._online = lambda: True
        return router

    def ask(self, router):
        return router.query("hello")["text"]

    def test_provider_is_skipped_after_three_failures_then_retried(self):
        router = self.make()
        for _ in range(3):
            self.assertEqual(self.ask(router), "from groq")
        self.assertEqual(self.calls.count("gemini"), 3)
        self.calls.clear()
        self.assertEqual(self.ask(router), "from groq")
        self.assertEqual(self.calls, ["groq"])               # gemini skipped during cooldown
        self.now[0] += router.COOLDOWN_SECONDS + 1
        self.gemini_ok = True
        self.calls.clear()
        self.assertEqual(self.ask(router), "from gemini")    # cooldown over, healthy again
        self.assertEqual(self.ask(router), "from gemini")

    def test_never_leaves_an_empty_ladder(self):
        router = self.make()
        router.COOLDOWN_SECONDS = 1e9
        for p in ("gemini", "groq", "openai", "claude", "ollama"):
            router._cooldown_until[p] = self.now[0] + 1e9
        self.gemini_ok = True
        self.assertEqual(self.ask(router), "from gemini")    # all cooling: still tries


if __name__ == "__main__":
    unittest.main()
