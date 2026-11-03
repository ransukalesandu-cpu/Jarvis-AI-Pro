"""Per-session Claude usage counter, so the owner can see what the API is costing.

The Anthropic API key is pay-per-use and separate from a Claude Pro
subscription. This module does not enforce a budget: the real spending limit is
the one set in the Anthropic Console. It only counts calls and tokens for the
current JARVIS process and prints one line per call.

Only the call source, the model name and token counts are recorded. Prompt and
answer text, and API keys, never pass through here.
"""
from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0}


def _tokens(usage: Any, name: str) -> int:
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, 0)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def record_claude_usage(response: Any, *, source: str, model: str) -> dict[str, int]:
    """Count one Claude response and print a usage line. Never raises."""
    try:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        input_tokens = _tokens(usage, "input_tokens") if usage is not None else 0
        output_tokens = _tokens(usage, "output_tokens") if usage is not None else 0
        with _lock:
            _totals["calls"] += 1
            _totals["input_tokens"] += input_tokens
            _totals["output_tokens"] += output_tokens
            snapshot = dict(_totals)
        print(
            f"[Claude usage] call #{snapshot['calls']} source={source} model={model} "
            f"input_tokens={input_tokens} output_tokens={output_tokens} "
            f"session_total_in={snapshot['input_tokens']} "
            f"session_total_out={snapshot['output_tokens']}"
        )
        return snapshot
    except Exception:
        return usage_snapshot()


def usage_snapshot() -> dict[str, int]:
    """Totals for this process: calls, input_tokens, output_tokens."""
    with _lock:
        return dict(_totals)


def reset_usage() -> None:
    """Start counting from zero (tests, or a fresh session)."""
    with _lock:
        for key in _totals:
            _totals[key] = 0
