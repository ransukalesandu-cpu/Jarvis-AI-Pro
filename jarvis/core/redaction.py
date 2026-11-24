"""One place for the patterns that keep secrets (and, where asked, personal data) out of logs, traces,
prompts, crash reports and sandboxes.

Before this module JARVIS had six redaction functions with six different pattern lists, so a token shape
known to one of them (an AWS key, a Slack token) could still reach a log written by another. They now all
finish with :func:`redact_secrets`, which applies the union, and keep their own placeholder strings so
nothing that reads their output changes:

==============================================  ============================================
``core.self_repair.redact_secrets``             incident log
``core.ai_error_repair.redact_secrets``         diagnostic prompts
``agent.store.redact``                          agent task state (via self_repair)
``computer_control.redaction.redact_text``      computer-control traces (via agent.store)
``memory.memory_manager.redact_sensitive_content``  memory + provider context (secrets + PII)
``webui.redact.scrub``                          log lines shown in the web UI
==============================================  ============================================

New code calls :func:`redact` with a profile:

* ``"secrets"``      credentials only;
* ``"secrets+pii"``  also e-mail addresses, phone numbers and labelled identity values;
* ``"display"``      secrets plus long opaque tokens and home-folder user names, for text shown on screen.

It is a practical filter, not a guarantee: a secret in an unknown format with no label can still pass.
No imports beyond the standard library, so anything can use it, including crash handlers.
"""
from __future__ import annotations

import re

PLACEHOLDER = "[REDACTED]"

# ── credential shapes recognisable on their own (no label needed) ─────────────
TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),                               # Google API key
    re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}"),                             # Google OAuth access token
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{8,}"),                        # OpenAI / Anthropic
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{12,}"),           # Stripe-style
    re.compile(r"\b(?:pk|rk)-[A-Za-z0-9_-]{12,}"),                          # other provider keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}"),                           # GitHub
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                    # AWS access key id
    re.compile(r"\bAC[0-9a-fA-F]{32}\b"),                                   # Twilio account SID
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),                          # Slack
    re.compile(r"\bIGQV[A-Za-z0-9_-]{16,}"),                                # Instagram Graph
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{5,}"),  # JWT
)

# Authorization header values, whatever the scheme. Group 1 keeps the header name. The possessive
# ``\s*+`` stops the "already redacted?" check from being dodged by backtracking over the space.
AUTH_HEADER = re.compile(
    r"(?i)(\bauthorization[\"']?\s*[:=]\s*+)(?!\[)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n]+)")
# "Bearer <token>" anywhere (log lines, exception messages). 12+ characters so "bearer of news" survives.
BEARER = re.compile(r"(?i)\b(bearer)\s+(?!\[)[A-Za-z0-9._~+/-]{12,}=*")

# name = value / "name": "value", for names that end in a secret word. Group 1 is the name, group 2 the
# separator; the value is replaced. Values already starting with "[" are left alone, so text that an
# earlier pass redacted keeps its placeholder.
SECRET_NAME = (r"[a-z0-9_-]*(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
               r"token|secret|password|passwd|passphrase|private[_-]?key|client[_-]?secret)")
ASSIGNMENT = re.compile(
    r"(?i)\b(" + SECRET_NAME + r")([\"']?\s*[:=]\s*)"
    r"(?:\"(?!\[)[^\"\r\n]*\"|'(?!\[)[^'\r\n]*'|(?![\[\"'])[^\s,;}\]&\"']+)")

# ── personal data (profile "secrets+pii"); placeholders match memory_manager's long-standing output ──
LABELED_SENSITIVE = re.compile(
    r"(?im)\b(api[_ -]?key|private key|key|password|passphrase|secret|"
    r"(?:access|refresh|auth|session)[_ -]?token|token|"
    r"auth(?:orization)?|client[_ -]?secret|otp|one[- ]time code|verification code|"
    r"credit card|card number|cvv|ssn|social security|national id|driver'?s license|passport|NIC|"
    r"bank account|account number|routing number|IBAN|SWIFT|home address|address|"
    r"date of birth|birth date|birthday|date of birth|email|e-mail|phone|mobile)\b"
    r"\s*(?:is|[:=])\s*[^\r\n,;]+",
    re.IGNORECASE,
)
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE = re.compile(r"(?<!\w)\+?\d[\d(). -]{7,}\d(?!\w)")
_DATE = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")

# ── display extras (profile "display") ────────────────────────────────────────
LONG_OPAQUE = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")
HOME_PATHS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)([A-Z]:\\Users\\)[^\\\s]+"), r"\1~"),
    (re.compile(r"(/home/|/Users/)[^/\s]+"), r"\1~"),
)


def redact_token_shapes(text: object, *, placeholder: str = PLACEHOLDER) -> str:
    """Only the self-identifying credential shapes (:data:`TOKEN_PATTERNS`).

    Callers whose output depends on the order of their own passes run this at the point where their
    old token list ran, then finish with :func:`redact_secrets`.
    """
    value = str(text if text is not None else "")
    for pattern in TOKEN_PATTERNS:
        value = pattern.sub(placeholder, value)
    return value


def redact_secrets(text: object, *, placeholder: str = PLACEHOLDER) -> str:
    """Replace every known credential shape, labelled secret value and auth header value."""
    value = str(text if text is not None else "")
    if not value:
        return value
    value = AUTH_HEADER.sub(lambda m: m.group(1) + placeholder, value)
    value = BEARER.sub(lambda m: m.group(1) + " " + placeholder, value)
    value = ASSIGNMENT.sub(lambda m: m.group(1) + m.group(2) + placeholder, value)
    return redact_token_shapes(value, placeholder=placeholder)


def redact_pii(text: object) -> str:
    """E-mail addresses, phone numbers (ISO dates kept) and labelled identity values."""
    value = str(text if text is not None else "")
    value = LABELED_SENSITIVE.sub(lambda m: m.group(1) + ": [REDACTED]", value)
    value = EMAIL.sub("[REDACTED_EMAIL]", value)
    value = PHONE.sub(
        lambda m: m.group(0) if _DATE.fullmatch(m.group(0).strip()) else "[REDACTED_NUMBER]", value)
    return value


def redact_display(text: object, *, placeholder: str = "[redacted]") -> str:
    """Secrets, long opaque tokens and the user name in home-folder paths, for text shown on screen."""
    value = redact_secrets(text, placeholder=placeholder)
    value = LONG_OPAQUE.sub(placeholder, value)
    for pattern, replacement in HOME_PATHS:
        value = pattern.sub(replacement, value)
    return value


PROFILES = ("secrets", "secrets+pii", "display")


def redact(text: object, profile: str = "secrets", *, limit: int | None = None) -> str:
    """Redact ``text`` with one of :data:`PROFILES`, then cut it to ``limit`` characters if given."""
    if profile == "secrets":
        value = redact_secrets(text)
    elif profile == "secrets+pii":
        value = redact_secrets(redact_pii(text))
    elif profile == "display":
        value = redact_display(text)
    else:
        raise ValueError(f"unknown redaction profile {profile!r}; expected one of {PROFILES}")
    if limit is not None and len(value) > limit:
        value = value[: max(0, limit - 1)] + "…"
    return value
