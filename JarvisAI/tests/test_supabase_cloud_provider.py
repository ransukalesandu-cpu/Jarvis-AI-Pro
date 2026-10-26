import json
import os
import unittest
from unittest.mock import MagicMock, patch

from core.supabase_cloud_provider import call_supabase_provider, _get_access_token, _AUTH


class SupabaseCloudProviderTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(_AUTH, {"access_token": "", "refresh_token": "", "expires_at": 0.0}):
            pass

    def test_anonymous_sign_in_does_not_require_email_or_password(self):
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("core.supabase_cloud_provider._request_json", return_value={
                "access_token": "signed-user-jwt",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
            }) as request:
                with patch.dict(_AUTH, {"access_token": "", "refresh_token": "", "expires_at": 0.0}):
                    token = _get_access_token(env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"], 3)
        self.assertEqual(token, "signed-user-jwt")
        self.assertEqual(request.call_args.args[0], "https://example.supabase.co/auth/v1/signup")
        self.assertEqual(request.call_args.kwargs["body"], {})
        self.assertNotIn("SUPABASE_EMAIL", env)
        self.assertNotIn("SUPABASE_PASSWORD", env)

    def test_claude_name_maps_to_anthropic_function_provider(self):
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"text": "answer", "model": "claude-test"}
        ).encode()
        with patch.dict(os.environ, env, clear=True):
            with patch("core.supabase_cloud_provider._get_access_token", return_value="signed-user-jwt"):
                with patch("core.supabase_cloud_provider._local_owner_session_verified", return_value=False):
                    with patch("core.supabase_cloud_provider.urllib.request.urlopen", return_value=response) as urlopen:
                        result = call_supabase_provider(
                            provider="claude", prompt="hello", system_prompt="You are JARVIS", timeout=3
                        )
        self.assertEqual(result["text"], "answer")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.supabase.co/functions/v1/jarvis-cloud-ai")
        self.assertEqual(json.loads(request.data)["provider"], "anthropic")
        self.assertEqual(request.get_header("Authorization"), "Bearer signed-user-jwt")
        self.assertEqual(request.get_header("Apikey"), "public-test-key")
        self.assertTrue(request.get_header("X-jarvis-host-nonce"))
        self.assertRegex(request.get_header("X-jarvis-host-timestamp"), r"^\d{10}$")

    def test_missing_public_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "configuration is incomplete"):
                call_supabase_provider(provider="gemini", prompt="hello", system_prompt="JARVIS")


if __name__ == "__main__":
    unittest.main()
