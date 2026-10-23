"""
Jarvis AI Pro - Hybrid LLM & Offline Routing Engine
Intelligently routes prompts across Gemini Live, Claude, OpenAI, and local Ollama.
Includes automatic internet connectivity checks and local failover.
"""

import os
import time
import socket
import logging
from typing import Dict, Any, Optional, Generator

logger = logging.getLogger("Jarvis.LLMRouter")


class HybridLLMRouter:
    def __init__(self, preferred_provider: str = "gemini"):
        self.preferred_provider = preferred_provider
        self.providers = {
            "gemini": self._call_gemini,
            "openai": self._call_openai,
            "claude": self._call_claude,
            "ollama": self._call_ollama,  # Local offline
        }
        self.ollama_endpoint = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.local_model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    @staticmethod
    def is_online(host: str = "1.1.1.1", port: int = 53, timeout: float = 1.5) -> bool:
        """Fast check to see if an internet connection is available."""
        try:
            socket.setdefaulttimeout(timeout)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((host, port))
            return True
        except OSError:
            return False

    def query(self, prompt: str, system_prompt: str = "You are JARVIS, an advanced personal AI.", **kwargs) -> Dict[str, Any]:
        """
        Executes query against the best available provider with automatic fallback.
        """
        online = self.is_online()
        start_time = time.time()

        # If offline, bypass cloud providers straight to local Ollama
        if not online:
            logger.warning("[ROUTER] Network offline detected. Switching to local LLM.")
            result = self._call_ollama(prompt, system_prompt, **kwargs)
            result["latency_ms"] = round((time.time() - start_time) * 1000, 2)
            result["mode"] = "local-offline"
            return result

        # Attempt preferred cloud provider
        order = [self.preferred_provider] + [p for p in ["gemini", "openai", "claude", "ollama"] if p != self.preferred_provider]

        for provider in order:
            try:
                handler = self.providers.get(provider)
                if handler:
                    result = handler(prompt, system_prompt, **kwargs)
                    result["latency_ms"] = round((time.time() - start_time) * 1000, 2)
                    result["provider"] = provider
                    result["mode"] = "cloud" if provider != "ollama" else "local"
                    return result
            except Exception as e:
                logger.warning(f"[ROUTER] Provider '{provider}' failed: {e}. Trying fallback...")

        raise RuntimeError("All LLM providers (including local fallback) failed to respond.")

    # ----------------- Provider Implementations -----------------
    def _call_gemini(self, prompt: str, system_prompt: str, **kwargs) -> Dict[str, Any]:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not configured")
        
        # Native Google GenAI SDK integration
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=kwargs.get("model", "gemini-2.5-flash"),
            contents=prompt,
            config={"system_instruction": system_prompt}
        )
        return {"text": response.text, "model": "gemini-2.5-flash"}

    def _call_openai(self, prompt: str, system_prompt: str, **kwargs) -> Dict[str, Any]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured")
        
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=kwargs.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        return {"text": response.choices[0].message.content, "model": "gpt-4o-mini"}

    def _call_claude(self, prompt: str, system_prompt: str, **kwargs) -> Dict[str, Any]:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured")
        
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=kwargs.get("model", "claude-3-5-sonnet-latest"),
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        return {"text": response.content[0].text, "model": "claude-3-5-sonnet"}

    def _call_ollama(self, prompt: str, system_prompt: str, **kwargs) -> Dict[str, Any]:
        import urllib.request
        import json

        url = f"{self.ollama_endpoint}/api/generate"
        payload = {
            "model": self.local_model,
            "prompt": f"System: {system_prompt}\nUser: {prompt}\nJarvis:",
            "stream": False
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode())
            return {"text": data.get("response", "").strip(), "model": self.local_model}
