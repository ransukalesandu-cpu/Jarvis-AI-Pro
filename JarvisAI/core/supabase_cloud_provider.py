"""Authenticated Supabase Edge Function transport for hybrid LLM requests.

The desktop app stores only Supabase public configuration and its own Supabase
Auth credentials in environment variables. Provider API keys remain server-side
Supabase secrets and are never sent to this module.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

_AUTH_LOCK = threading.RLock()
_AUTH: dict[str, Any] = {"access_token": "", "refresh_token": "", "expires_at": 0.0}


def _request_json(url: str, *, method: str = "POST", headers: dict[str, str] | None = None,
                  body: dict[str, Any] | None = None, timeout: float = 20.0) -> dict[str, Any]:
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, headers=headers or {}, method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never include response bodies, headers, or credentials in raised errors/logs.
        raise RuntimeError(f"Supabase request failed with HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Supabase request failed ({type(exc).__name__})") from None
    if not isinstance(decoded, dict):
        raise RuntimeError("Supabase returned an invalid response")
    return decoded


def _get_access_token(base_url: str, public_key: str, timeout: float) -> str:
    now = time.monotonic()
    with _AUTH_LOCK:
        if _AUTH.get("access_token") and now < float(_AUTH.get("expires_at", 0)) - 60:
            return str(_AUTH["access_token"])

        headers = {
            "Content-Type": "application/json",
            "apikey": public_key,
        }
        refresh = str(_AUTH.get("refresh_token") or "").strip()
        auth_result: dict[str, Any] | None = None
        if refresh:
            try:
                auth_result = _request_json(
                    base_url + "/auth/v1/token?grant_type=refresh_token",
                    headers=headers, body={"refresh_token": refresh}, timeout=timeout,
                )
            except RuntimeError:
                auth_result = None

        if auth_result is None:
            email = os.getenv("SUPABASE_EMAIL", "").strip()
            password = os.getenv("SUPABASE_PASSWORD", "")
            if not email or not password:
                raise RuntimeError(
                    "Supabase Auth is not configured; set SUPABASE_EMAIL and SUPABASE_PASSWORD."
                )
            auth_result = _request_json(
                base_url + "/auth/v1/token?grant_type=password",
                headers=headers, body={"email": email, "password": password}, timeout=timeout,
            )

        access = str(auth_result.get("access_token") or "").strip()
        refresh_token = str(auth_result.get("refresh_token") or "").strip()
        expires_in = max(60, int(auth_result.get("expires_in") or 3600))
        if not access:
            raise RuntimeError("Supabase Auth did not return an access token")
        _AUTH.update({
            "access_token": access,
            "refresh_token": refresh_token,
            "expires_at": time.monotonic() + expires_in,
        })
        return access


def call_supabase_provider(*, provider: str, prompt: str, system_prompt: str,
                           timeout: float = 20.0, model: str | None = None) -> dict[str, str]:
    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    public_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not base_url or not public_key:
        raise RuntimeError("Supabase cloud configuration is incomplete")

    access_token = _get_access_token(base_url, public_key, timeout)
    payload: dict[str, Any] = {
        "provider": "anthropic" if provider == "claude" else provider,
        "prompt": prompt,
        "system_prompt": system_prompt,
    }
    if model:
        payload["model"] = model

    result = _request_json(
        base_url + "/functions/v1/jarvis-cloud-ai",
        headers={
            "Content-Type": "application/json",
            "apikey": public_key,
            "Authorization": "Bearer " + access_token,
        },
        body=payload,
        timeout=timeout,
    )
    text = result.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Supabase cloud provider returned no text")
    return {
        "text": text.strip(),
        "model": str(result.get("model") or ""),
    }
