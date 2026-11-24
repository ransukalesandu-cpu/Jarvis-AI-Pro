"""Shared redaction (core/redaction.py) and the six functions that now finish with it.

Fake tokens are assembled at runtime so the repository's secret scanner does not flag this file.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from jarvis.core import redaction as r

TOKENS = {
    "google_api_key": "AIza" + "B" * 35,  # pragma: allowlist secret
    "google_oauth": "ya29." + "C" * 30,
    "openai": "sk-" + "D" * 24,
    "anthropic": "sk-" + "ant-" + "E" * 30,
    "stripe": "sk_" + "live_" + "F" * 24,
    "provider_pk": "pk-" + "G" * 20,
    "github": "gh" + "p_" + "H" * 36,
    "aws": "AK" + "IA" + "J" * 16,
    "twilio_sid": "AC" + "a1" * 16,
    "slack": "xo" + "xb-" + "1234567890-abcdef",
    "instagram": "IGQV" + "K" * 20,
    "jwt": "ey" + "J" + "L" * 12 + "." + "M" * 10 + "." + "N" * 8,
}


@pytest.mark.parametrize("name", sorted(TOKENS))
def test_every_token_shape_is_redacted(name):
    token = TOKENS[name]
    out = r.redact_secrets(f"value {token} end")
    assert token not in out
    assert out == "value [REDACTED] end"


@pytest.mark.parametrize("text,kept,gone", [
    ("api_key=abc123", "api_key=", "abc123"),
    ('{"password": "hunter2"}', '"password": ', "hunter2"),  # pragma: allowlist secret
    ("client_secret: 'xyz-987'", "client_secret: ", "xyz-987"),  # pragma: allowlist secret
    ("GITHUB_TOKEN=abcdef0123", "GITHUB_TOKEN=", "abcdef0123"),
    ("passphrase = correct horse", "passphrase = ", "correct"),
])
def test_labelled_values_lose_the_value_keep_the_name(text, kept, gone):
    out = r.redact_secrets(text)
    assert kept in out and gone not in out and "[REDACTED]" in out


def test_authorization_header_value_is_removed_whatever_the_scheme():
    out = r.redact_secrets("Authorization: Digest username=bob, response=6629fae49393a053")
    assert out == "Authorization: [REDACTED]"


def test_bearer_token():
    assert r.redact_secrets("sent Bearer " + "Z" * 20) == "sent Bearer [REDACTED]"


@pytest.mark.parametrize("text", [
    "the bearer of good news arrived",
    "max_tokens=500 temperature=0.2",
    "token count is 5",
    "basic setup done on 2026-11-24",
    "use sk-learn for this",
    "The key insight: memory is local",
    "[AudioTrace 4/OUTPUT] Write timing #1: 4800 bytes accepted in 3 ms",
])
def test_ordinary_text_is_left_alone(text):
    assert r.redact_secrets(text) == text


def test_redaction_is_idempotent_and_respects_existing_placeholders():
    mixed = f"api_key=abc Bearer {'Q' * 20} {TOKENS['github']} Authorization: Basic Zm9vOmJhcg=="
    once = r.redact_secrets(mixed)
    assert r.redact_secrets(once) == once
    for already in ("api_key=[REDACTED_API_KEY]", "token: [redacted]", "password=[REDACTED_CREDENTIAL]"):
        assert r.redact_secrets(already) == already


def test_pii_profile():
    out = r.redact("mail me at someone@example.org or +94 77 123 4567 on 2026-11-24", "secrets+pii")
    assert "[REDACTED_EMAIL]" in out and "[REDACTED_NUMBER]" in out
    assert "2026-11-24" in out
    assert r.redact("my phone is 0771234567", "secrets+pii") == "my phone: [REDACTED]"


def test_display_profile():
    out = r.redact(r"C:\Users\lesa\jarvis and /home/lesa/x " + "a" * 45, "display")
    assert r"C:\Users\~\jarvis" in out and "/home/~/x" in out and "[redacted]" in out
    assert "lesa" not in out


def test_profiles_and_limit():
    with pytest.raises(ValueError):
        r.redact("x", "everything")
    assert r.redact("abcdefghij", limit=5) == "abcd…"
    assert r.redact(None) == ""


def _callers():
    from jarvis.agent.store import redact as agent_redact
    from jarvis.computer_control.redaction import redact_text
    from jarvis.core.ai_error_repair import redact_secrets as diag_redact
    from jarvis.core.self_repair import redact_secrets as incident_redact
    from jarvis.memory.memory_manager import redact_sensitive_content
    from jarvis.webui.redact import scrub
    return {
        "self_repair": incident_redact, "ai_error_repair": diag_redact, "agent.store": agent_redact,
        "computer_control": redact_text, "memory_manager": redact_sensitive_content, "webui": scrub,
    }


@pytest.mark.parametrize("caller", ["self_repair", "ai_error_repair", "agent.store", "computer_control",
                                    "memory_manager", "webui"])
@pytest.mark.parametrize("shape", ["aws", "slack", "twilio_sid", "google_oauth", "instagram", "github"])
def test_all_six_redaction_paths_share_the_union(caller, shape):
    """AWS, Slack, Twilio, OAuth and Instagram shapes used to be known only to memory_manager."""
    token = TOKENS[shape]
    out = _callers()[caller](f"failed with {token} while syncing")
    assert token not in out


def test_each_path_keeps_its_own_placeholder():
    c = _callers()
    assert "[REDACTED_API_KEY]" in c["self_repair"]("key " + TOKENS["google_api_key"])
    assert "[REDACTED_CREDENTIAL]" in c["memory_manager"]("key " + TOKENS["google_api_key"])
    assert "[redacted]" in c["webui"]("key " + TOKENS["google_api_key"])
    assert c["memory_manager"]("Bearer abc") == "[REDACTED_CREDENTIAL]"


def test_module_needs_only_the_standard_library():
    """Crash handlers and the future IPC layer must be able to import it with nothing else loaded."""
    source = (Path(__file__).resolve().parents[1] / "core" / "redaction.py").read_text(encoding="utf-8")
    imports = re.findall(r"^(?:from|import)\s+([A-Za-z_][\w.]*)", source, flags=re.M)
    assert set(imports) <= {"__future__", "re"}, imports
