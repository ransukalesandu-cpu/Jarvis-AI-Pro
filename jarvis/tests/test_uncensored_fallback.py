"""Local uncensored fallback: refusal detection, router wiring, Live hook."""
from __future__ import annotations

import threading

import pytest

from jarvis.core import uncensored_fallback as uf
from jarvis.core.hybrid_llm_router import HybridLLMRouter


@pytest.fixture
def local(monkeypatch):
    """Fallback ON with a fake Ollama that records calls."""
    monkeypatch.setenv("JARVIS_UNCENSORED_MODEL", "hf.co/test/qwen3-4b-heretic:Q4_K_M")
    monkeypatch.delenv("JARVIS_UNCENSORED_FALLBACK", raising=False)
    calls = []

    def fake_post(url, payload, timeout):
        calls.append((url, payload))
        return {"model": payload["model"], "message": {"content": "Here is the local answer."}}
    monkeypatch.setattr(uf, "_post", fake_post)
    return calls


@pytest.mark.parametrize("text", [
    "I'm sorry, but I can't help with that.",
    "Sorry, I can't assist with that request.",
    "I cannot help with that.",
    "I'm not able to help with that.",
    "That goes against my guidelines, so I won't write it.",
    "As an AI, I cannot share opinions like that.",
    "I'm afraid I can't provide that information.",
])
def test_detects_refusals(text):
    assert uf.is_refusal(text)


@pytest.mark.parametrize("text", [
    "I can't open Spotify because it isn't installed, sir.",
    "Sure. The capital of France is Paris.",
    "I couldn't find that file on your desktop.",
    "",
    "Here is the summary. Note that some sites say this is against their policy to scrape.",
])
def test_ignores_normal_answers(text):
    assert not uf.is_refusal(text)


def test_live_length_cap():
    long_answer = "I'm sorry, but I can't help with that. " + "Actually here is a lot of detail. " * 20
    assert uf.is_refusal(long_answer)
    assert not uf.is_refusal(long_answer, max_chars=400)


def test_disabled_without_model(monkeypatch):
    monkeypatch.delenv("JARVIS_UNCENSORED_MODEL", raising=False)
    monkeypatch.setattr(uf, "_config", lambda: {})
    assert not uf.enabled()
    assert uf.answer("anything") is None


def test_kill_switch(local, monkeypatch):
    monkeypatch.setenv("JARVIS_UNCENSORED_FALLBACK", "0")
    assert not uf.enabled()


def test_answer_calls_local_ollama_only(local):
    out = uf.answer("question")
    assert out == {"text": "Here is the local answer.", "model": "hf.co/test/qwen3-4b-heretic:Q4_K_M",
                   "provider": "ollama-uncensored"}
    url, payload = local[0]
    assert url.startswith("http://127.0.0.1:11434/api/chat")
    assert payload["messages"][-1]["content"] == "question"


def test_local_refusal_or_outage_returns_none(local, monkeypatch):
    monkeypatch.setattr(uf, "_post", lambda *a: {"message": {"content": "I can't help with that."}})
    assert uf.answer("q") is None

    def boom(*a):
        raise ConnectionRefusedError
    monkeypatch.setattr(uf, "_post", boom)
    assert uf.answer("q") is None


def _router(reply_text):
    router = HybridLLMRouter(api_keys={"gemini": "k"}, online_check=False, preferred_provider="gemini")
    router.providers["gemini"] = lambda prompt, system, **kw: {"text": reply_text, "model": "g"}
    router.providers["ollama"] = lambda prompt, system, **kw: (_ for _ in ()).throw(ConnectionError())
    return router


def test_router_falls_back_on_refusal_for_chat(local):
    out = _router("I'm sorry, but I can't help with that.").query("q", task="chat", allow_uncensored=True)
    assert out["provider"] == "ollama-uncensored" and out["text"] == "Here is the local answer."


def test_router_never_falls_back_without_permission(local):
    """A caller that does not pass allow_uncensored (translate, compare, ...)."""
    out = _router("I'm sorry, but I can't help with that.").query("q", task="chat")
    assert out["provider"] == "gemini"
    assert local == []


def test_router_keeps_normal_answer(local):
    out = _router("Paris.").query("q", task="chat", allow_uncensored=True)
    assert out["provider"] == "gemini" and local == []


def test_router_blocked_reply_falls_back(local):
    # A Gemini safety block comes back as empty text -> every provider fails.
    out = _router("").query("q", task="chat", allow_uncensored=True)
    assert out["provider"] == "ollama-uncensored"


def test_text_brain_only_allows_chat(monkeypatch):
    from jarvis.core import text_brain
    seen = {}

    class R:
        def query(self, prompt, system_prompt, task, allow_uncensored=False):
            seen[task] = allow_uncensored
            return {"text": "ok"}
    monkeypatch.setattr(text_brain, "get_router", lambda: R())
    monkeypatch.setattr(text_brain, "_override", None)
    monkeypatch.setattr("jarvis.assistants.preferred_provider", lambda: "", raising=False)
    text_brain.ask("q", task="chat")
    text_brain.ask("q", task="translate")
    assert seen == {"chat": True, "translate": False}


def test_live_hook_delivers_local_answer(local):
    got = []
    done = threading.Event()

    def deliver(text):
        got.append(text)
        done.set()
    assert uf.maybe_handle_live_turn("tell me the thing", "Sorry, I can't help with that.", deliver)
    assert done.wait(5)
    assert got == ["Here is the local answer."]


def test_live_hook_ignores_normal_turns(local):
    assert not uf.maybe_handle_live_turn("open spotify", "Opening Spotify, sir.", lambda t: None)
    assert not uf.maybe_handle_live_turn("", "Sorry, I can't help with that.", lambda t: None)
    assert local == []


def test_tools_enabled_default_on_with_kill_switch(local, monkeypatch):
    monkeypatch.setattr(uf, "_config", lambda: {})
    monkeypatch.delenv("JARVIS_UNCENSORED_TOOLS", raising=False)
    assert uf.tools_enabled()
    monkeypatch.setenv("JARVIS_UNCENSORED_TOOLS", "0")
    assert not uf.tools_enabled()
    monkeypatch.delenv("JARVIS_UNCENSORED_TOOLS")
    monkeypatch.setattr(uf, "_config", lambda: {"uncensored_for_tools": False})
    assert not uf.tools_enabled()


def test_tools_off_when_fallback_off(monkeypatch):
    monkeypatch.delenv("JARVIS_UNCENSORED_MODEL", raising=False)
    monkeypatch.setattr(uf, "_config", lambda: {})
    assert not uf.tools_enabled()


def _wait_hook(user, start_task, monkeypatch, classify):
    monkeypatch.setattr(uf, "_post", lambda url, payload, timeout: {
        "message": {"content": classify if "ACT or ANSWER" in payload["messages"][-1]["content"]
                    else "Local text answer."}})
    got, done = [], threading.Event()

    def deliver(text):
        got.append(text)
        done.set()
    assert uf.maybe_handle_live_turn(user, "Sorry, I can't help with that.", deliver, start_task=start_task)
    assert done.wait(5)
    return got


def test_live_action_request_starts_agent_task(local, monkeypatch):
    started = []
    got = _wait_hook("delete the temp folder", lambda t: started.append(t) or "started task", monkeypatch, "ACT")
    assert started == ["delete the temp folder"] and got == ["started task"]


def test_live_question_gets_text_answer(local, monkeypatch):
    started = []
    got = _wait_hook("explain this", lambda t: started.append(t) or "x", monkeypatch, "ANSWER")
    assert started == [] and got == ["Local text answer."]


def test_live_action_needs_tools_enabled(local, monkeypatch):
    monkeypatch.setenv("JARVIS_UNCENSORED_TOOLS", "0")
    started = []
    got = _wait_hook("delete the temp folder", lambda t: started.append(t) or "x", monkeypatch, "ACT")
    assert started == [] and got == ["Local text answer."]


def test_planners_pass_allow_uncensored(local, monkeypatch):
    from jarvis.agent import integration
    from jarvis.computer_control.orchestrator import planner
    assert integration._uncensored_tools() is True
    assert planner._uncensored_tools() is True
    monkeypatch.setenv("JARVIS_UNCENSORED_TOOLS", "0")
    assert integration._uncensored_tools() is False
    assert planner._uncensored_tools() is False


def test_planner_style_json_falls_back(local, monkeypatch):
    monkeypatch.setattr(uf, "_post", lambda url, payload, timeout: {
        "message": {"content": '{"steps": []}'}, "model": "m"})
    out = _router("I'm sorry, but I can't help with that.").query(
        "plan", system_prompt="You are JARVIS's task planner. Answer with JSON only.",
        allow_uncensored=True)
    assert out["provider"] == "ollama-uncensored" and out["text"] == '{"steps": []}'
