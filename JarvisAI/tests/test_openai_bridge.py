"""Tests for the OpenAI-compatible bridge used by the Jarvis Web UI."""
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import openai_bridge
from dashboard.openai_bridge import messages_to_prompt, register_openai_routes


def _client(key="secret-key", ask=None):
    app = FastAPI()
    calls = []

    def fake_ask(system_prompt, prompt):
        calls.append((system_prompt, prompt))
        return "Hello from JARVIS, sir."

    register_openai_routes(app, ask=ask or fake_ask, api_key_getter=lambda: key)
    return TestClient(app), calls


AUTH = {"Authorization": "Bearer secret-key"}


class OpenAIBridgeTests(unittest.TestCase):
    def test_disabled_without_configured_key(self):
        client, calls = _client(key="")
        resp = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(calls, [])

    def test_rejects_wrong_key(self):
        client, calls = _client()
        resp = client.get("/v1/models", headers={"Authorization": "Bearer nope"})
        self.assertEqual(resp.status_code, 401)
        resp = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(calls, [])

    def test_lists_jarvis_model(self):
        client, _ = _client()
        resp = client.get("/v1/models", headers=AUTH)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([m["id"] for m in resp.json()["data"]], ["jarvis"])

    def test_non_stream_completion(self):
        client, calls = _client()
        resp = client.post("/v1/chat/completions", headers=AUTH, json={
            "model": "jarvis",
            "messages": [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "Hello"},
            ],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["object"], "chat.completion")
        self.assertEqual(body["choices"][0]["message"]["content"], "Hello from JARVIS, sir.")
        system_prompt, prompt = calls[0]
        self.assertIn("Be brief.", system_prompt)
        self.assertEqual(prompt, "Hello")

    def test_stream_completion_reassembles_text(self):
        client, _ = _client()
        resp = client.post("/v1/chat/completions", headers=AUTH, json={
            "stream": True,
            "messages": [{"role": "user", "content": "Hello"}],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/event-stream"))
        lines = [l[len("data: "):] for l in resp.text.splitlines() if l.startswith("data: ")]
        self.assertEqual(lines[-1], "[DONE]")
        text = "".join(
            json.loads(l)["choices"][0]["delta"].get("content", "") for l in lines[:-1]
        )
        self.assertEqual(text, "Hello from JARVIS, sir.")

    def test_brain_failure_returns_502_without_leaking_details(self):
        def boom(system_prompt, prompt):
            raise RuntimeError("key sk-secret leaked")

        client, _ = _client(ask=boom)
        resp = client.post("/v1/chat/completions", headers=AUTH,
                           json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(resp.status_code, 502)
        self.assertNotIn("sk-secret", resp.text)

    def test_bad_requests(self):
        client, _ = _client()
        self.assertEqual(client.post("/v1/chat/completions", headers=AUTH, json={}).status_code, 400)
        resp = client.post("/v1/chat/completions", headers=AUTH,
                           json={"messages": [{"role": "system", "content": "only system"}]})
        self.assertEqual(resp.status_code, 400)

    def test_multi_turn_and_multimodal_flattening(self):
        system_prompt, prompt = messages_to_prompt([
            {"role": "user", "content": [{"type": "text", "text": "What is this?"},
                                         {"type": "image_url", "image_url": {"url": "data:x"}}]},
            {"role": "assistant", "content": "A cat."},
            {"role": "user", "content": "Thanks"},
        ])
        self.assertIn("You are JARVIS", system_prompt)
        self.assertIn("User: What is this?", prompt)
        self.assertIn("JARVIS: A cat.", prompt)
        self.assertTrue(prompt.endswith("User: Thanks\n\nJARVIS:"))

    def test_env_key_overrides_config(self):
        with patch.dict(openai_bridge.os.environ, {"JARVIS_WEB_API_KEY": "env-key"}):
            self.assertEqual(openai_bridge.configured_api_key({"web_chat_api_key": "cfg"}), "env-key")
        with patch.dict(openai_bridge.os.environ, {"JARVIS_WEB_API_KEY": ""}):
            self.assertEqual(openai_bridge.configured_api_key({"web_chat_api_key": "cfg"}), "cfg")

    def test_dashboard_mounts_bridge(self):
        from dashboard.server import DashboardServer

        paths = {getattr(r, "path", "") for r in DashboardServer().app.routes}
        self.assertIn("/v1/chat/completions", paths)
        self.assertIn("/v1/models", paths)


if __name__ == "__main__":
    unittest.main()
