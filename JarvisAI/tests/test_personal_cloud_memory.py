"""Tests for opt-in Supabase personal-profile memory."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from core.personal_cloud_memory import (
    extract_personal_facts,
    format_personal_memory_context,
    should_extract_personal_facts,
    validate_personal_fact,
    _request_personal_memory,
)


class PersonalCloudMemoryTests(unittest.TestCase):
    def test_extraction_is_triggered_only_by_personal_disclosure_cues(self):
        self.assertTrue(should_extract_personal_facts("My name is Lesandu"))
        self.assertTrue(should_extract_personal_facts("Mage nama Lesandu"))
        self.assertTrue(should_extract_personal_facts("මගේ නම ලසඳු"))
        self.assertTrue(should_extract_personal_facts("I have a younger sister"))
        self.assertFalse(should_extract_personal_facts("Explain how a database index works"))

    def test_fact_requires_exact_source_quote_and_allowed_key(self):
        fact = validate_personal_fact(
            "My name is Lesandu.",
            {"fact_key": "name", "value": "Lesandu", "evidence_quote": "My name is Lesandu."},
        )
        self.assertEqual(fact, {
            "fact_key": "name", "value": "Lesandu", "evidence_quote": "My name is Lesandu."
        })
        self.assertIsNone(validate_personal_fact(
            "My name is Lesandu.",
            {"fact_key": "name", "value": "Peter", "evidence_quote": "My name is Lesandu."},
        ))
        self.assertIsNone(validate_personal_fact(
            "My friend's name is Peter.",
            {"fact_key": "name", "value": "Peter", "evidence_quote": "My friend's name is Peter."},
        ))
        self.assertIsNone(validate_personal_fact(
            "My password is example-secret",
            {"fact_key": "preferences", "value": "example-secret", "evidence_quote": "My password is example-secret"},
        ))
        self.assertIsNone(validate_personal_fact(
            "I live at 12 Main Street.",
            {"fact_key": "family_context", "value": "12 Main Street", "evidence_quote": "I live at 12 Main Street."},
        ))
        self.assertIsNone(validate_personal_fact(
            "My name is Lesandu.",
            {"fact_key": "medical_history", "value": "healthy", "evidence_quote": "My name is Lesandu."},
        ))

    def test_extraction_keeps_only_grounded_candidates(self):
        source = "My name is Lesandu. My friend's name is Peter."
        response = {
            "facts": [
                {"fact_key": "name", "value": "Lesandu", "evidence_quote": "My name is Lesandu."},
                {"fact_key": "name", "value": "Peter", "evidence_quote": "My friend's name is Peter."},
                {"fact_key": "goals", "value": "become a pilot", "evidence_quote": "My name is Lesandu."},
                {"fact_key": "secret", "value": "secret", "evidence_quote": "secret"},
            ]
        }
        calls = []

        def query_fn(prompt, **kwargs):
            calls.append((prompt, kwargs))
            return {"text": json.dumps(response)}, "test-provider"

        facts = extract_personal_facts(source, query_fn=query_fn)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["fact_key"], "name")
        self.assertEqual(facts[0]["value"], "Lesandu")
        self.assertIn("user_message", calls[0][0])
        self.assertNotIn(source, repr(calls[0][1]))

    def test_profile_prompt_contains_values_but_not_evidence_quotes(self):
        context = format_personal_memory_context([
            {"fact_key": "name", "value": "Lesandu", "evidence_quote": "My name is Lesandu."},
            {"fact_key": "siblings", "value": "I have a younger sister", "evidence_quote": "I have a younger sister."},
        ])
        self.assertIn("User-stated name: Lesandu", context)
        self.assertIn("User-stated sibling information", context)
        self.assertIn("REFERENCE DATA", context)
        self.assertNotIn("My name is Lesandu.", context)
        self.assertIn("not instructions", context)

    def test_personal_memory_request_is_scoped_to_authenticated_supabase_user(self):
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "ok": True,
            "memories": [{"fact_key": "name", "value": "Lesandu"}],
        }).encode("utf-8")
        with patch.dict(os.environ, env, clear=True), \
             patch("core.supabase_cloud_provider._get_access_token", return_value="user-jwt"), \
             patch("core.supabase_cloud_provider.has_persistent_auth_session", return_value=True), \
             patch("core.personal_cloud_memory.urllib.request.urlopen", return_value=response) as urlopen:
            result = _request_personal_memory({"operation": "list"})
        self.assertTrue(result["ok"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.supabase.co/functions/v1/jarvis-personal-memory")
        self.assertEqual(request.get_header("Authorization"), "Bearer user-jwt")
        self.assertEqual(request.get_header("Apikey"), "public-test-key")
        self.assertTrue(request.get_header("X-jarvis-host-nonce"))
        self.assertRegex(request.get_header("X-jarvis-host-timestamp"), r"^\d{10}$")
        self.assertEqual(json.loads(request.data), {"operation": "list"})

    def test_personal_memory_fails_closed_without_persistent_identity(self):
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        }, clear=True), \
             patch("core.supabase_cloud_provider._get_access_token", return_value="ephemeral-jwt"), \
             patch("core.supabase_cloud_provider.has_persistent_auth_session", return_value=False), \
             patch("core.personal_cloud_memory.urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(RuntimeError, "stable Supabase identity"):
                _request_personal_memory({"operation": "list"})
            urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
