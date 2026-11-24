"""Turns a raw HUD log line into something safe to show in the web page. No Qt.

Defence in depth, not the only control: the feed also refuses to run at all while the assistant is
locked / awaiting a PIN / silent / in guest mode (see log_feed.py).
"""
from __future__ import annotations

import re

from jarvis.core.redaction import HOME_PATHS, LONG_OPAQUE, redact_secrets, redact_token_shapes

MAX_LINE = 400
KINDS = ("you", "ai", "sys", "err", "file")

# Token shapes, long opaque tokens and home-folder paths are defined once in core/redaction.py.
# The two below are kept here because they replace the label too ("token: x" -> "[redacted]").
_SECRETS = [
    re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret|password|passwd|pin)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
]
_HOME = HOME_PATHS
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
    text = redact_token_shapes(text, placeholder="[redacted]")
    for rx in _SECRETS:
        text = rx.sub("[redacted]", text)
    text = redact_secrets(text, placeholder="[redacted]")
    text = LONG_OPAQUE.sub("[redacted]", text)
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
