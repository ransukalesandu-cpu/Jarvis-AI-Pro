"""Per-session Claude API usage: a call counter and one log line per call.

The Anthropic API is pay-per-use and separate from a Claude Pro subscription,
so the owner should be able to see what JARVIS spends. This records, for each
call, only the model and the token counts: never the prompt, the answer, or a
key. The real spending limit belongs in the Anthropic Console (Settings ->
Limits); this is visibility, not a cap.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("Jarvis.ClaudeUsage")

_lock = threading.Lock()
_calls = 0
_input_tokens = 0
_output_tokens = 0
_by_model: dict[str, int] = {}


def _tokens(usage: Any, name: str) -> int:
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, 0)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def record_call(model: str, usage: Any = None, *, source: str = "") -> int:
    """Count one Claude call and log model + tokens. Returns the call number."""
    global _calls, _input_tokens, _output_tokens
    tin = _tokens(usage, "input_tokens") + _tokens(usage, "cache_read_input_tokens") \
        + _tokens(usage, "cache_creation_input_tokens")
    tout = _tokens(usage, "output_tokens")
    with _lock:
        _calls += 1
        _input_tokens += tin
        _output_tokens += tout
        _by_model[str(model)] = _by_model.get(str(model), 0) + 1
        n = _calls
    line = (f"[Claude] call #{n} {source + ' ' if source else ''}model={model} "
            f"input_tokens={tin} output_tokens={tout}")
    print(line)
    logger.info(line)
    return n


def session_usage() -> dict:
    """Totals for this session (no content, no keys)."""
    with _lock:
        return {"calls": _calls, "input_tokens": _input_tokens,
                "output_tokens": _output_tokens, "by_model": dict(_by_model)}


def reset() -> None:
    """For tests."""
    global _calls, _input_tokens, _output_tokens
    with _lock:
        _calls = _input_tokens = _output_tokens = 0
        _by_model.clear()
