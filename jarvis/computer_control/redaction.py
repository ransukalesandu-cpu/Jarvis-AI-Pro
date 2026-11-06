"""Redaction for everything computer control writes down or sends away.

Three rules (owner decision 7 — password fields):

1. Text typed into a password field is never logged, stored in a trace or a
   workflow, or sent to a provider: :func:`redact_params` replaces it with
   ``[password-field]``.
2. Screenshots that leave the process (vision provider, saved trace) have
   password-field rectangles painted over first: :func:`mask_regions`.
3. Secrets in any free text (API keys, tokens, ``password=...``) are scrubbed
   with the same patterns the action log already uses.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

PASSWORD_PLACEHOLDER = "[password-field]"
SECRET_KEYS = ("password", "passwd", "passphrase", "token", "secret", "api_key", "apikey",
               "pin", "otp", "cookie", "session", "authorization", "credential", "private_key")
_TEXT_KEYS = ("text", "value", "keys", "content", "input")
_EXTRA_PATTERNS = (
    re.compile(r"\b(sk|pk|rk)[-_][A-Za-z0-9_-]{12,}"),           # provider keys
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),                      # Google API keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),                  # GitHub tokens
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),  # JWT
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{12,}=*"),
)


def is_password_target(params: Mapping[str, Any] | None) -> bool:
    params = params or {}
    if params.get("is_password") or params.get("password_field"):
        return True
    element = params.get("element")
    if isinstance(element, Mapping) and (element.get("is_password")
                                         or str(element.get("control_type", "")).lower() == "password"):
        return True
    return False


#: a secret-named key inside JSON-looking text, e.g. a tool argument that arrives as a
#: JSON string: '{"password": "..."}' -> '{"password": "[REDACTED]"}'
_JSON_SECRET = re.compile(r'("[^"\\]{0,40}?(?:' + "|".join(SECRET_KEYS) + r')[^"\\]{0,40}?"\s*:\s*)'
                          r'("(?:[^"\\]|\\.)*"|[^\s,}\]]+)', re.I)


def redact_text(text: Any, limit: int = 2000) -> str:
    value = str(text if text is not None else "")
    for pattern in _EXTRA_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    value = _JSON_SECRET.sub(lambda m: m.group(1) + '"[REDACTED]"', value)
    try:
        from jarvis.agent.store import redact
        return redact(value, limit)
    except Exception:
        return value[:limit]


def redact_params(params: Mapping[str, Any] | None, *, limit: int = 300) -> dict:
    """A copy of ``params`` that is safe to log, show or send."""
    params = dict(params or {})
    password = is_password_target(params)
    out: dict = {}
    for key, value in params.items():
        lowered = str(key).lower()
        if any(word in lowered for word in SECRET_KEYS):
            out[key] = "[redacted]"
        elif password and lowered in _TEXT_KEYS:
            out[key] = PASSWORD_PLACEHOLDER
        elif isinstance(value, Mapping):
            out[key] = redact_params(value, limit=limit)
        elif isinstance(value, (list, tuple)):
            out[key] = [redact_params(v, limit=limit) if isinstance(v, Mapping)
                        else redact_text(v, limit) if isinstance(v, str) else v
                        for v in list(value)[:20]]
        elif isinstance(value, str):
            out[key] = redact_text(value, limit)
        else:
            out[key] = value
    return out


def mask_regions(image: Any, rects: Iterable[tuple[int, int, int, int]]):
    """Paint over ``(left, top, width, height)`` rectangles of a PIL image.

    Returns a new image; the input is not modified. Used for password fields
    (and any other sensitive control) before a screenshot leaves the process.
    """
    rects = [tuple(int(v) for v in r) for r in rects]
    if not rects:
        return image
    from PIL import ImageDraw  # pillow is a declared dependency
    masked = image.copy()
    draw = ImageDraw.Draw(masked)
    for left, top, width, height in rects:
        if width > 0 and height > 0:
            draw.rectangle([left, top, left + width - 1, top + height - 1], fill=(0, 0, 0))
    return masked
