"""Hybrid Phase 2: task-based provider routing. No network: fake providers."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import task_router
from jarvis.core.hybrid_llm_router import HybridLLMRouter


def _router(keys, routing=None, preferred="gemini"):
    r = HybridLLMRouter(preferred, api_keys=keys, online_check=False, task_routing=routing)
    r._supabase_enabled = False
    calls = []

    def fake(name):
        def call(prompt, system_prompt, **kw):
            calls.append(name)
            return {"text": f"from {name}", "model": name}
        return call
    r.providers = {name: fake(name) for name in r.providers}
    return r, calls


class ClassifyTests(unittest.TestCase):
    CASES = {
        "fix this python function that throws a KeyError": "coding",
        "plan my week: gym, study and a trip to Kandy": "planning",
        "draft an email to my landlord about the rent": "writing",
        "explain why the sky is blue": "reasoning",
        "generate an image of a red dragon logo": "image_generation",
        "what is on my screen right now": "screen",
        "turn on the camera and tell me what you see": "camera",
        "look at this and tell me what it is": "vision",
        "what time is it": "simple",
        "": "simple",
    }

    def test_every_category(self):
        for text, want in self.CASES.items():
            self.assertEqual(task_router.classify(text), want, text)


class TableTests(unittest.TestCase):
    def test_defaults(self):
        table = task_router.routing_from_config({"task_routing": {}})
        for cat in ("voice", "vision", "screen", "camera", "simple"):
            self.assertEqual(task_router.provider_for(cat, table), "gemini", cat)
        for cat in ("coding", "planning", "reasoning", "writing"):
            self.assertEqual(task_router.provider_for(cat, table), "claude", cat)
        self.assertEqual(task_router.provider_for("image_generation", table, {"openai": True}), "openai")
        self.assertEqual(task_router.provider_for("image_generation", table, {"openai": False}), "gemini")
        self.assertEqual(task_router.provider_for("nonsense", table), "gemini")

    def test_overrides_and_bad_values(self):
        table = task_router.routing_from_config({"task_routing": {
            "coding": "openai", "writing": "anthropic", "simple": "teleport", "dance": "claude"}})
        self.assertEqual(table["coding"], "openai")
        self.assertEqual(table["writing"], "claude")     # anthropic is normalised
        self.assertEqual(table["simple"], "gemini")      # unknown provider ignored
        self.assertNotIn("dance", table)

    def test_absent_setting_means_no_routing(self):
        self.assertIsNone(task_router.routing_from_config({}))
        self.assertIsNone(task_router.routing_from_config({"task_routing": "claude"}))
        self.assertIsNone(task_router.routing_from_config(None))


class RouterTests(unittest.TestCase):
    TABLE = task_router.routing_from_config({"task_routing": {}})

    def test_task_goes_to_its_provider(self):
        r, calls = _router({"gemini": "g", "claude": "c"}, self.TABLE)
        self.assertEqual(r.query("x", task="coding")["provider"], "claude")
        self.assertEqual(r.query("x", task="simple")["provider"], "gemini")
        self.assertEqual(calls, ["claude", "gemini"])

    def test_missing_key_falls_back_through_the_ladder(self):
        r, calls = _router({"gemini": "g"}, self.TABLE)       # no Claude key
        out = r.query("x", task="coding")
        self.assertEqual(out["provider"], "gemini")
        self.assertNotIn("claude", calls)

    def test_image_generation_without_openai_goes_to_gemini(self):
        r, calls = _router({"gemini": "g", "claude": "c"}, self.TABLE)
        self.assertEqual(r.query("x", task="image_generation")["provider"], "gemini")

    def test_legacy_behaviour_is_unchanged(self):
        # No table: the task hint is ignored and the preferred provider leads.
        r, calls = _router({"gemini": "g", "claude": "c"}, None, preferred="gemini")
        self.assertEqual(r.query("x", task="coding")["provider"], "gemini")
        self.assertEqual(r.query("x")["provider"], "gemini")
        r2, _ = _router({"gemini": "g", "claude": "c"}, None, preferred="claude")
        self.assertEqual(r2.query("x")["provider"], "claude")

    def test_model_override_stays_with_the_first_provider(self):
        r, _ = _router({"gemini": "g", "claude": "c"}, self.TABLE)
        seen = {}

        def claude(prompt, system_prompt, **kw):
            seen["claude"] = kw.get("model")
            raise RuntimeError("down")

        def gemini(prompt, system_prompt, **kw):
            seen["gemini"] = kw.get("model")
            return {"text": "ok", "model": "g"}
        r.providers["claude"], r.providers["gemini"] = claude, gemini
        r.query("x", task="coding", model="my-model")
        self.assertEqual(seen, {"claude": "my-model", "gemini": None})


class CallerTests(unittest.TestCase):
    def _config(self, data):
        d = tempfile.mkdtemp()
        path = Path(d) / "api_keys.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_text_fallback_routes_only_when_configured(self):
        from jarvis.core.provider_fallback import query_text_fallback
        made = []

        class FakeRouter:
            def __init__(self, **kw):
                made.append(kw)
                self.queries = []

            def configured_key_status(self):
                return {"claude": True}

            def query(self, text, **kw):
                made.append(kw)
                return {"text": "ok"}

        legacy = self._config({"anthropic_api_key": "c"})
        query_text_fallback("fix my python bug", config_path=legacy, base_system_prompt="s",
                            router_factory=FakeRouter)
        self.assertNotIn("task_routing", made[0])
        self.assertNotIn("task", made[1])
        made.clear()
        routed = self._config({"anthropic_api_key": "c", "task_routing": {}})
        query_text_fallback("fix my python bug", config_path=routed, base_system_prompt="s",
                            router_factory=FakeRouter)
        self.assertEqual(made[0]["task_routing"]["coding"], "claude")
        self.assertEqual(made[1]["task"], "coding")

    def test_intent_router_preference(self):
        import jarvis.core.smart_intent_router as sir
        with mock.patch.object(sir, "API_CONFIG_PATH", self._config({"ai_provider": "openai"})):
            self.assertEqual(sir._configured_preferred_provider(), "openai")     # legacy
        with mock.patch.object(sir, "API_CONFIG_PATH", self._config(
                {"ai_provider": "openai", "task_routing": {"simple": "claude"}})):
            self.assertEqual(sir._configured_preferred_provider(), "claude")


if __name__ == "__main__":
    unittest.main()
