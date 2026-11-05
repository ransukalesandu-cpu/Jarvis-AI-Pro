"""Turns a raw HUD log line into something safe to show in the web page. No Qt.

Defence in depth, not the only control: the feed also refuses to run at all while the assistant is
locked / awaiting a PIN / silent / in guest mode (see log_feed.py).
"""
from __future__ import annotations

import re

MAX_LINE = 400
KINDS = ("you", "ai", "sys", "err", "file")

_SECRETS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),                         # Google API keys
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{12,}"),              # OpenAI/Anthropic/Stripe style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),                    # GitHub tokens
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),   # JWT
    re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret|password|passwd|pin)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"),                          # any other long opaque token
]
_HOME = [
    (re.compile(r"(?i)([A-Z]:\\Users\\)[^\\\s]+"), r"\1~"),
    (re.compile(r"(/home/|/Users/)[^/\s]+"), r"\1~"),
]
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_CREDENTIAL = re.compile(r"^\s*/(owner|pin|auth|login|password)\b", re.IGNORECASE)
_PREFIX = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_ ]{0,20}):\s?(.*)$", re.DOTALL)


def classify(line: str) -> tuple[str, str] | None:
    """(kind, body) for a line worth showing, or None to drop it entirely."""
    raw = _CONTROL.sub("", str(line or "")).strip()
    if not raw:
        return None
    m = _PREFIX.match(raw)
    prefix, body = (m.group(1).strip().lower(), m.group(2)) if m else ("", raw)
    if prefix == "sec":                                   # authentication events never leave Python
        return None
    if prefix == "you":
        if _CREDENTIAL.match(body):
            return None
        kind = "you"
    elif prefix in ("jarvis", "bihansa", "assistant"):
        kind = "ai"
    elif prefix == "file":
        kind = "file"
    elif prefix in ("err", "error") or (not m and "err" in raw.lower()):
        kind = "err"
    else:
        kind = "sys"
        body = raw if not m else raw                      # keep the original prefix (e.g. "SYS: …") for context
    return kind, body


def scrub(text: str) -> str:
    for rx in _SECRETS:
        text = rx.sub("[redacted]", text)
    for rx, rep in _HOME:
        text = rx.sub(rep, text)
    text = " ".join(text.split())
    return text if len(text) <= MAX_LINE else text[: MAX_LINE - 1] + "…"


def prepare(line: str) -> tuple[str, str] | None:
    c = classify(line)
    if c is None:
        return None
    kind, body = c
    body = scrub(body)
    return (kind, body) if body else None
