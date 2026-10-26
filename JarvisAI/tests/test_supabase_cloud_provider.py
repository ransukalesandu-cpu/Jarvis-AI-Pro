import os
import unittest
from unittest.mock import patch

from core.supabase_cloud_provider import call_supabase_provider


class SupabaseCloudProviderTests(unittest.TestCase):
    def test_claude_name_maps_to_anthropic_function_provider(self):
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("core.supabase_cloud_provider._get_access_token", return_value="signed-user-jwt"):
                with patch(
                    "core.supabase_cloud_provider._request_json",
                    return_value={"text": "answer", "model": "claude-test"},
                ) as request:
                    result = call_supabase_provider(
                        provider="claude", prompt="hello", system_prompt="You are JARVIS", timeout=3
                    )
        self.assertEqual(result["text"], "answer")
        self.assertEqual(request.call_args.kwargs["body"]["provider"], "anthropic")
        self.assertEqual(
            request.call_args.args[0],
            "https://example.supabase.co/functions/v1/jarvis-cloud-ai",
        )
        self.assertEqual(
            request.call_args.kwargs["headers"]["Authorization"],
            "Bearer signed-user-jwt",
        )

    def test_missing_public_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "configuration is incomplete"):
                call_supabase_provider(provider="gemini", prompt="hello", system_prompt="JARVIS")


if __name__ == "__main__":
    unittest.main()
