"""
Local "second opinion" model for when a cloud model refuses a plain request.

Gemini (and sometimes the other cloud providers) refuse or filter requests the
owner considers ordinary. When that happens JARVIS can hand the SAME question to
a local model running in Ollama on the laptop — typically a Heretic-processed
open-weight model (github.com/p-e-w/heretic, run separately; nothing from that
AGPL project is copied here). See docs/UNCENSORED_FALLBACK.md.

Scope:
    * Text answers (voice + chat).
    * Actions too, unless switched off (``uncensored_for_tools`` /
      ``JARVIS_UNCENSORED_TOOLS=0``): the agent planner and the
      computer-control planner fall back to the local model when the cloud
      planner refuses, and a refused voice request that needs actions on the PC
      is started as an autonomous task. The owner chose this knowing that a
      model without refusal training follows injected instructions (emails, web
      pages) more easily; what still protects the PC does not depend on the
      model: owner verification and Privacy Lock before a task starts, the
      planners' tool allow-lists, untrusted-content wrapping, path_guard, the
      action log and the stop word / emergency stop.
    * Off by default. It turns on only when a local model name is configured:
      ``uncensored_model`` in config/api_keys.json or ``JARVIS_UNCENSORED_MODEL``.
    * Local only: the request goes to Ollama (``OLLAMA_HOST``, default
      127.0.0.1:11434) and never to a cloud host.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from typing import Callable, Optional

DEFAULT_TIMEOUT_S = 180.0
_LIVE_MAX_REFUSAL_CHARS = 400          # a long spoken answer is not a refusal

SYSTEM_PROMPT = (
    "You are JARVIS, the owner's private assistant running locally on his laptop. "
    "Answer the request directly and helpfully. Your answer will be read aloud: "
    "keep it short, plain sentences, no Markdown, no lists."
)

# Phrases cloud models use when they decline on policy grounds. Deliberately
# about *declining*, not about failing ("I can't open that app, it isn't
# installed" must not trigger a second model).
_REFUSAL_PATTERNS = [
    r"\bI(?:'m| am)? (?:sorry|afraid)[,.]? (?:but )?I (?:can(?:no|')t|won't|am not able to|'m not able to|am unable to|'m unable to) (?:help|assist|provide|do that|create|write|generate|answer|comply|share|give|discuss|go into)",
    r"^\s*(?:sorry[,.]?\s*)?I (?:can(?:no|')t|won't) (?:help|assist) (?:you )?with (?:that|this|requests?)",
    r"\bI(?:'m| am) (?:not able|unable) to (?:help|assist) with (?:that|this|requests?)",
    r"\bI (?:can(?:no|')t|won't) (?:provide|create|generate|write|produce) (?:that|this|content|information|instructions|material)",
    r"\b(?:against|violates?) (?:my|our|the) (?:guidelines|policies|policy|usage policy|content policy|safety guidelines)",
    r"\bnot (?:something|a request) I (?:can|am able to|'m able to) (?:help|assist) with",
    r"\bAs an AI(?: language model| assistant)?, I (?:can(?:no|')t|won't|am not able|'m not able|don't)",
    r"\bI(?:'m| am) not (?:comfortable|permitted|allowed) (?:helping|assisting|providing|to)",
]
_REFUSAL_RE = re.compile("|".join(f"(?:{p})" for p in _REFUSAL_PATTERNS), re.IGNORECASE | re.MULTILINE)


def is_refusal(text: str, *, max_chars: int | None = None) -> bool:
    """True when ``text`` reads like a policy refusal rather than an answer."""
    text = str(text or "").strip()
    if not text:
        return False
    if max_chars is not None and len(text) > max_chars:
        return False
    # Look at the opening: an answer that merely mentions a policy later on is
    # still an answer.
    return bool(_REFUSAL_RE.search(text[:600]))


# ── configuration ───────────────────────────────────────────────────────────
def _config() -> dict:
    try:
        from jarvis.memory.config_manager import load_api_keys
        return load_api_keys() or {}
    except Exception:
        return {}


def model_name() -> str:
    env = os.environ.get("JARVIS_UNCENSORED_MODEL", "").strip()
    if env:
        return env
    return str(_config().get("uncensored_model") or "").strip()


def enabled() -> bool:
    if os.environ.get("JARVIS_UNCENSORED_FALLBACK", "").strip().lower() in {"0", "false", "off", "no"}:
        return False
    return bool(model_name())


def tools_enabled() -> bool:
    """Planners and voice actions may use the local model (owner's choice, on by
    default once a model is configured; ``JARVIS_UNCENSORED_TOOLS=0`` or
    ``"uncensored_for_tools": false`` turns it off)."""
    if not enabled():
        return False
    env = os.environ.get("JARVIS_UNCENSORED_TOOLS", "").strip().lower()
    if env:
        return env not in {"0", "false", "off", "no"}
    value = _config().get("uncensored_for_tools", True)
    return value is not False and str(value).strip().lower() not in {"0", "false", "off", "no"}


def speak_enabled() -> bool:
    return os.environ.get("JARVIS_UNCENSORED_SPEAK", "1").strip().lower() not in {"0", "false", "off", "no"}


def _endpoint() -> str:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host


# ── the local call ──────────────────────────────────────────────────────────
_post: Optional[Callable[[str, dict, float], dict]] = None      # tests


def _http_post(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def answer(prompt: str, system: str = SYSTEM_PROMPT, *, timeout: float = DEFAULT_TIMEOUT_S,
           num_ctx: int = 4096) -> Optional[dict]:
    """Ask the local model. Returns {'text', 'model', 'provider'} or None when
    the fallback is off, Ollama is unreachable, or the local model refused too."""
    prompt = str(prompt or "").strip()
    if not prompt or not enabled():
        return None
    model = model_name()
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "messages": [{"role": "system", "content": system or SYSTEM_PROMPT},
                     {"role": "user", "content": prompt}],
        "options": {"num_ctx": int(num_ctx)},
    }
    try:
        data = (_post or _http_post)(_endpoint() + "/api/chat", payload, timeout)
    except Exception as exc:
        print(f"[Uncensored] local model unavailable ({type(exc).__name__}); is Ollama running?")
        return None
    text = str(((data or {}).get("message") or {}).get("content") or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if not text or is_refusal(text):
        return None
    return {"text": text, "model": str(data.get("model") or model), "provider": "ollama-uncensored"}


# ── Gemini Live hook ────────────────────────────────────────────────────────
_CLASSIFY_PROMPT = (
    "Does this request need actions on the owner's computer or phone (opening, "
    "creating, deleting, moving, downloading, installing, sending, clicking, typing, "
    "running something), or only a spoken answer? Reply with exactly one word: "
    "ACT or ANSWER.\n\nRequest: "
)


def needs_action(user_text: str) -> bool:
    """Ask the local model whether a refused request is an action or a question."""
    result = answer(_CLASSIFY_PROMPT + user_text, "You classify requests. One word only.",
                    timeout=60.0)
    return bool(result) and result["text"].strip().upper().startswith("ACT")


def maybe_handle_live_turn(user_text: str, assistant_text: str,
                           deliver: Callable[[str], None],
                           start_task: Optional[Callable[[str], str]] = None) -> bool:
    """Called once per finished Live turn. When Gemini's spoken reply was a
    short refusal of the owner's request, handle it locally in the background:
    an action request becomes an autonomous task (``start_task``, when tools are
    allowed), anything else gets a local text answer passed to ``deliver``.
    Returns True when a fallback was started."""
    if not enabled():
        return False
    user_text = str(user_text or "").strip()
    if len(user_text) < 3 or not is_refusal(assistant_text, max_chars=_LIVE_MAX_REFUSAL_CHARS):
        return False

    def _work():
        try:
            if start_task is not None and tools_enabled() and needs_action(user_text):
                deliver(start_task(user_text))
                return
            result = answer(user_text)
            if result:
                deliver(result["text"])
            else:
                print("[Uncensored] the local model had no answer either.")
        except Exception as exc:
            print(f"[Uncensored] fallback failed: {type(exc).__name__}")

    threading.Thread(target=_work, name="uncensored-fallback", daemon=True).start()
    return True


_tts_player = None
_tts_lock = threading.Lock()


def speak_locally(text: str) -> None:
    """Read ``text`` with JARVIS's own TTS engine (not Gemini). Blocking."""
    global _tts_player
    from jarvis.core.tts import create_tts_player
    with _tts_lock:
        if _tts_player is None:
            _tts_player = create_tts_player(_config())
        player = _tts_player
    player.speak(text)


def stop_speaking() -> None:
    """Stop word: cut off a local-model answer that is being read out."""
    with _tts_lock:
        player = _tts_player
    if player is not None and player.is_playing:
        player.stop()
