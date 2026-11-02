"""Hybrid text-LLM routing with explicit provider configuration and safe fallback.

The Gemini Live audio session remains JARVIS's primary real-time voice/vision/tool
path. This router is a resilient text-only fallback for periods when Live is not
connected; it does not replace Live or bypass the action/security dispatcher.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import time
import threading
import urllib.request
from typing import Any

from core.provider_protocol import ProviderResult, TextProvider

logger = logging.getLogger("Jarvis.LLMRouter")


def resolve_preferred_provider(config: dict[str, Any]) -> str:
    """Resolve the hybrid router preference without reusing llm_client settings.

    `llm_provider` belongs to core.llm_client and selects Ollama or an
    OpenAI-compatible local server. The hybrid route has its own
    `hybrid_provider` setting; absent that, the UI's `ai_provider` is used.
    """
    selected = str(
        config.get("hybrid_provider") or config.get("ai_provider") or "gemini"
    ).strip().lower()
    if selected == "anthropic":
        selected = "claude"
    return selected if selected in _PROVIDER_ORDER else "gemini"

_PROVIDER_ORDER = ("gemini", "groq", "openai", "claude", "ollama")
_KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}


class HybridLLMRouter:
    """Route a text prompt through configured providers, then local Ollama.

    Cloud providers are attempted only when their API key is configured. This
    avoids silently sending prompts to a provider the owner did not configure.
    The Ollama endpoint is local by default and can be customized via env vars.
    """

    def __init__(
        self,
        preferred_provider: str = "gemini",
        *,
        api_keys: dict[str, str] | None = None,
        timeout: float = 20.0,
        online_check: bool = True,
    ) -> None:
        preferred = str(preferred_provider or "gemini").strip().lower()
        self.preferred_provider = preferred if preferred in _PROVIDER_ORDER else "gemini"
        self.api_keys = {
            str(key).strip().lower(): str(value).strip()
            for key, value in (api_keys or {}).items()
            if str(value or "").strip()
        }
        self.timeout = max(1.0, min(float(timeout), 120.0))
        self.online_check = bool(online_check)
        # Anonymous Supabase Auth does not require or collect an email/password.
        self._supabase_enabled = all(
            os.getenv(name, "").strip()
            for name in ("SUPABASE_URL", "SUPABASE_ANON_KEY")
        )
        self.ollama_endpoint = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        self.local_model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        self.providers: dict[str, TextProvider] = {
            "gemini": self._call_gemini,
            "groq": self._call_groq,
            "openai": self._call_openai,
            "claude": self._call_claude,
            "ollama": self._call_ollama,
        }
        self._health_lock = threading.Lock()
        self._provider_health: dict[str, dict[str, float | int]] = {
            name: {"latency_ms": 0.0, "successes": 0, "failures": 0}
            for name in _PROVIDER_ORDER
        }

    def _record_provider_success(self, provider: str, latency_ms: float) -> None:
        with self._health_lock:
            state = self._provider_health[provider]
            previous = float(state["latency_ms"])
            state["latency_ms"] = (
                max(0.0, float(latency_ms)) if not state["successes"]
                else previous * 0.7 + max(0.0, float(latency_ms)) * 0.3
            )
            state["successes"] = int(state["successes"]) + 1
            state["failures"] = 0

    def _record_provider_failure(self, provider: str) -> None:
        with self._health_lock:
            state = self._provider_health[provider]
            state["failures"] = int(state["failures"]) + 1

    def provider_health(self) -> dict[str, dict[str, float | int]]:
        """Return aggregate provider timings only; never expose prompts or keys."""
        with self._health_lock:
            return {name: dict(values) for name, values in self._provider_health.items()}

    def _rank_fallbacks(self, providers: list[str]) -> list[str]:
        with self._health_lock:
            snapshot = {name: dict(values) for name, values in self._provider_health.items()}
        original_order = {name: index for index, name in enumerate(_PROVIDER_ORDER)}

        def score(name: str) -> tuple[float, int]:
            state = snapshot[name]
            latency = float(state["latency_ms"]) if state["successes"] else 1000.0
            # One recent failure is enough to prefer a healthy alternative.
            return (int(state["failures"]) * 10000.0 + latency,
                    original_order[name])

        return sorted(providers, key=score)

    def _key(self, provider: str) -> str:
        return self.api_keys.get(provider, "") or os.getenv(_KEY_ENV.get(provider, ""), "").strip()

    def configured_key_status(self) -> dict[str, bool]:
        """Report credential presence only; never return credential contents."""
        status = {
            provider: bool(self._key(provider))
            for provider in ("gemini", "groq", "openai", "claude")
        }
        status["supabase_cloud"] = self._supabase_enabled
        return status

    @staticmethod
    def is_online(host: str = "1.1.1.1", port: int = 443, timeout: float = 1.0) -> bool:
        """Check outbound TCP connectivity on HTTPS port 443.

        DNS port 53 is commonly blocked on managed, school, and public networks,
        which can incorrectly force the router into local-only mode despite
        working internet access. Port 443 is a more representative reachability
        probe for the cloud APIs used by this router. This is only a heuristic;
        provider requests still handle their own connection failures.
        """
        try:
            with socket.create_connection((host, port), timeout=max(0.1, float(timeout))):
                return True
        except (OSError, ValueError, TypeError):
            return False

    @staticmethod
    def _validate_result(result: Any, provider: str) -> ProviderResult:
        if not isinstance(result, dict):
            raise RuntimeError(f"{provider} returned an invalid response object")
        text = result.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError(f"{provider} returned an empty response")
        # Do not let provider-specific objects leak into UI or logs.
        return {key: value for key, value in result.items() if key in {"text", "model"}}

    def query(
        self,
        prompt: str,
        system_prompt: str = "You are JARVIS, a capable personal AI assistant.",
        **kwargs: Any,
    ) -> ProviderResult:
        """Query configured providers in priority order with bounded failover."""
        prompt = str(prompt or "").strip()
        system_prompt = str(system_prompt or "").strip()
        if not prompt:
            raise ValueError("A non-empty prompt is required")
        if not system_prompt:
            system_prompt = "You are JARVIS, a capable personal AI assistant."

        started = time.monotonic()
        online = not self.online_check or self.is_online()
        fallback = [
            provider for provider in _PROVIDER_ORDER
            if provider != self.preferred_provider
        ]
        fallback = self._rank_fallbacks(fallback)
        order = [self.preferred_provider] + fallback
        if not online:
            # Connectivity probes can be false negatives on restricted networks.
            # Prefer local Ollama when offline, then use health-ranked configured
            # cloud providers if the local service is unavailable.
            order = ["ollama"] + self._rank_fallbacks([
                provider for provider in _PROVIDER_ORDER if provider != "ollama"
            ])

        failures: list[str] = []
        for provider in order:
            if provider != "ollama" and not self._supabase_enabled and not self._key(provider):
                continue
            # A generic model override belongs to the preferred provider only.
            # Reusing (for example) a Gemini model name during Groq/OpenAI/Claude
            # failover makes otherwise healthy fallback providers reject requests.
            provider_kwargs = dict(kwargs)
            if provider != self.preferred_provider:
                provider_kwargs.pop("model", None)
            provider_started = time.monotonic()
            try:
                result = self._validate_result(
                    self.providers[provider](prompt, system_prompt, **provider_kwargs), provider
                )
                provider_latency = (time.monotonic() - provider_started) * 1000.0
                self._record_provider_success(provider, provider_latency)
                result.update({
                    "provider": provider,
                    "mode": "local-offline" if provider == "ollama" and not online
                            else ("local" if provider == "ollama" else "cloud"),
                    "latency_ms": round((time.monotonic() - started) * 1000, 2),
                })
                logger.info(
                    "Hybrid text response completed via %s mode=%s latency_ms=%.2f",
                    provider, result["mode"], result["latency_ms"],
                )
                return result
            except Exception as exc:
                self._record_provider_failure(provider)
                # Exception text can contain request details; log only the type.
                failures.append(f"{provider}:{type(exc).__name__}")
                logger.warning("Provider %s failed (%s); trying configured fallback",
                               provider, type(exc).__name__)

        if not failures:
            failures.append("no-provider-configured")
        raise RuntimeError(
            "No configured LLM provider could answer the request ("
            + ", ".join(failures)
            + "). Configure a provider API key or start local Ollama."
        )

    def _call_gemini(self, prompt: str, system_prompt: str, **kwargs: Any) -> ProviderResult:
        if self._supabase_enabled:
            from core.supabase_cloud_provider import call_supabase_provider
            return call_supabase_provider(
                provider="gemini", prompt=prompt, system_prompt=system_prompt,
                timeout=self.timeout, model=kwargs.get("model"),
            )
        from google import genai
        client = genai.Client(
            api_key=self._key("gemini"),
            http_options={"timeout": int(self.timeout * 1000)},
        )
        model = str(kwargs.get("model") or "gemini-2.5-flash")
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"system_instruction": system_prompt},
        )
        return {"text": response.text or "", "model": model}

    def _call_groq(self, prompt: str, system_prompt: str, **kwargs: Any) -> ProviderResult:
        if self._supabase_enabled:
            from core.supabase_cloud_provider import call_supabase_provider
            return call_supabase_provider(
                provider="groq", prompt=prompt, system_prompt=system_prompt,
                timeout=self.timeout, model=kwargs.get("model"),
            )
        """Call Groq's OpenAI-compatible chat-completions API without an extra SDK."""
        model = str(kwargs.get("groq_model") or kwargs.get("model") or
                    os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
        }
        request = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self._key("groq"),
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        choices = data.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        return {"text": str(message.get("content") or "").strip(),
                "model": str((data.get("model") or model))}

    def _call_openai(self, prompt: str, system_prompt: str, **kwargs: Any) -> ProviderResult:
        if self._supabase_enabled:
            from core.supabase_cloud_provider import call_supabase_provider
            return call_supabase_provider(
                provider="openai", prompt=prompt, system_prompt=system_prompt,
                timeout=self.timeout, model=kwargs.get("model"),
            )
        from openai import OpenAI
        model = str(kwargs.get("model") or "gpt-4o-mini")
        client = OpenAI(api_key=self._key("openai"), timeout=self.timeout, max_retries=0)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        return {"text": response.choices[0].message.content or "", "model": model}

    def _call_claude(self, prompt: str, system_prompt: str, **kwargs: Any) -> ProviderResult:
        if self._supabase_enabled:
            from core.supabase_cloud_provider import call_supabase_provider
            return call_supabase_provider(
                provider="claude", prompt=prompt, system_prompt=system_prompt,
                timeout=self.timeout, model=kwargs.get("model"),
            )
        import anthropic
        model = str(kwargs.get("model") or "claude-3-5-sonnet-latest")
        client = anthropic.Anthropic(
            api_key=self._key("claude"), timeout=self.timeout, max_retries=0
        )
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        return {"text": text, "model": model}

    def _call_ollama(self, prompt: str, system_prompt: str, **kwargs: Any) -> ProviderResult:
        payload = {
            "model": str(kwargs.get("local_model") or self.local_model),
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
        }
        request = urllib.request.Request(
            self.ollama_endpoint + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return {"text": str(data.get("response") or "").strip(),
                "model": str(data.get("model") or payload["model"])}
