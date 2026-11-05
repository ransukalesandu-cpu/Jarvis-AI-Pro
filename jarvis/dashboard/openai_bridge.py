"""OpenAI-compatible chat API that exposes the JARVIS text brain.

The Jarvis Web UI (``web/``, built on NextChat) talks to OpenAI-style
``/v1/chat/completions`` endpoints. Mounting this bridge on the dashboard lets
that UI use JARVIS's own hybrid router (Gemini → Groq → OpenAI → Claude →
local Ollama failover) as the ``jarvis`` model, alongside every other provider
the Web UI supports natively.

Access is disabled until the owner sets an API key, either in the
``JARVIS_WEB_API_KEY`` environment variable or as ``web_chat_api_key`` in
``config/api_keys.json``. The Web UI sends that key as its OpenAI API key.
"""
# No `from __future__ import annotations`: FastAPI must resolve the locally
# imported `Request` annotation on the route handlers at definition time.
import asyncio
import hmac
import json
import os
import time
import uuid
from typing import Any, Callable

JARVIS_MODEL = "jarvis"
JARVIS_SYSTEM_PROMPT = (
    "You are JARVIS, a capable, concise and friendly personal AI assistant. "
    "Answer in the language the user writes in. Use Markdown when it helps."
)
_MAX_MESSAGES = 40
_MAX_PROMPT_CHARS = 60_000


def _load_config() -> dict:
    try:
        from jarvis.memory.config_manager import load_api_keys

        return load_api_keys() or {}
    except Exception:
        return {}


def configured_api_key(config: dict | None = None) -> str:
    """Return the Web UI API key, preferring the environment."""
    env = os.environ.get("JARVIS_WEB_API_KEY", "").strip()
    if env:
        return env
    cfg = config if config is not None else _load_config()
    return str(cfg.get("web_chat_api_key") or "").strip()


def _text_of(content: Any) -> str:
    """Flatten OpenAI message content (string or multimodal parts) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif isinstance(part, dict) and part.get("type") == "image_url":
                parts.append("[image attached — not supported by the jarvis model]")
        return "\n".join(p for p in parts if p)
    return ""


def messages_to_prompt(messages: list[dict]) -> tuple[str, str]:
    """Convert an OpenAI chat history into (system_prompt, prompt) for the router."""
    system_parts = [JARVIS_SYSTEM_PROMPT]
    turns: list[tuple[str, str]] = []
    for msg in messages[-_MAX_MESSAGES:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").lower()
        text = _text_of(msg.get("content")).strip()
        if not text:
            continue
        if role in ("system", "developer"):
            system_parts.append(text)
        else:
            turns.append(("JARVIS" if role == "assistant" else "User", text))

    if not turns:
        return "\n\n".join(system_parts), ""
    if len(turns) == 1 and turns[0][0] == "User":
        prompt = turns[0][1]
    else:
        history = "\n\n".join(f"{who}: {text}" for who, text in turns)
        prompt = (
            "Continue this conversation. Reply only as JARVIS to the last User "
            "message.\n\n" + history + "\n\nJARVIS:"
        )
    return "\n\n".join(system_parts), prompt[-_MAX_PROMPT_CHARS:]


def _default_ask(system_prompt: str, prompt: str) -> str:
    from jarvis.core.hybrid_llm_router import HybridLLMRouter, resolve_preferred_provider

    config = _load_config()
    router = HybridLLMRouter(
        resolve_preferred_provider(config),
        api_keys=config,
        timeout=60.0,
        online_check=False,
    )
    result = router.query(prompt, system_prompt=system_prompt, task="chat")
    return str(result.get("text") or "")


def register_openai_routes(
    app: Any,
    *,
    ask: Callable[[str, str], str] | None = None,
    api_key_getter: Callable[[], str] = configured_api_key,
) -> None:
    """Mount ``/v1/models`` and ``/v1/chat/completions`` on a FastAPI app."""
    from fastapi import Request
    from fastapi.responses import JSONResponse, StreamingResponse

    ask_fn = ask or _default_ask

    def _error(message: str, status: int, kind: str = "invalid_request_error"):
        return JSONResponse({"error": {"message": message, "type": kind}}, status_code=status)

    def _check(req: Request):
        expected = api_key_getter()
        if not expected:
            return _error(
                "Jarvis Web API is disabled. Set JARVIS_WEB_API_KEY or "
                "web_chat_api_key in config/api_keys.json.",
                503,
                "service_unavailable",
            )
        supplied = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
            return _error("Invalid API key.", 401, "authentication_error")
        return None

    @app.get("/v1/models")
    async def list_models(req: Request):
        denied = _check(req)
        if denied is not None:
            return denied
        return JSONResponse({
            "object": "list",
            "data": [{
                "id": JARVIS_MODEL,
                "object": "model",
                "created": 0,
                "owned_by": "jarvis",
            }],
        })

    @app.post("/v1/chat/completions")
    async def chat_completions(req: Request):
        denied = _check(req)
        if denied is not None:
            return denied
        try:
            body = await req.json()
        except Exception:
            return _error("Request body must be JSON.", 400)
        messages = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(messages, list) or not messages:
            return _error("'messages' must be a non-empty list.", 400)

        system_prompt, prompt = messages_to_prompt(messages)
        if not prompt:
            return _error("No user message with text content was provided.", 400)

        model = str(body.get("model") or JARVIS_MODEL)
        created = int(time.time())
        completion_id = "chatcmpl-" + uuid.uuid4().hex
        try:
            text = await asyncio.to_thread(ask_fn, system_prompt, prompt)
        except Exception as exc:
            print(f"[Jarvis Web API] Brain request failed: {type(exc).__name__}")
            return _error(
                "JARVIS could not answer: no configured AI provider responded. "
                "Check your provider keys or start Ollama.",
                502,
                "api_error",
            )

        if not body.get("stream"):
            return JSONResponse({
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })

        def _chunk(delta: dict, finish: str | None = None) -> str:
            payload = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

        async def _events():
            yield _chunk({"role": "assistant", "content": ""})
            # The router returns whole replies; emit them in small pieces so the
            # Web UI renders progressively like a normal streaming model.
            step = 48
            for i in range(0, len(text), step):
                yield _chunk({"content": text[i:i + step]})
            yield _chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
