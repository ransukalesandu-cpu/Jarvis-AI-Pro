import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from core.supabase_cloud_provider import (
    call_supabase_provider, _get_access_token, _AUTH,
    _load_persisted_refresh_token, _persist_refresh_token,
    reset_supabase_auth_session,
)


class SupabaseCloudProviderTests(unittest.TestCase):
    def setUp(self):
        # Reset module-level auth state before every test; an immediately-exited
        # patch.dict context would restore the previous values instead.
        _AUTH.update({
            "access_token": "",
            "refresh_token": "",
            "expires_at": 0.0,
            "refresh_failed": False,
        })

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

    def test_transient_refresh_failure_retries_same_identity_without_signup(self):
        with TemporaryDirectory() as folder:
            blocked_file = Path(folder) / "refresh.blocked"
            session_file = Path(folder) / "session.dat"
            with patch("core.supabase_cloud_provider._SESSION_FILE", session_file), \
                 patch("core.supabase_cloud_provider._SESSION_BLOCKED_FILE", blocked_file), \
                 patch.dict(_AUTH, {
                     "access_token": "", "refresh_token": "stale-refresh-token",
                     "expires_at": 0.0, "refresh_failed": False,
                 }), \
                 patch("core.supabase_cloud_provider._load_persisted_refresh_token", return_value=""), \
                 patch("core.supabase_cloud_provider._request_json", side_effect=[
                     RuntimeError("Supabase request failed (URLError)"),
                     {"access_token": "recovered-jwt", "refresh_token": "rotated-refresh", "expires_in": 3600},
                 ]) as request:
                with self.assertRaisesRegex(RuntimeError, "session refresh failed"):
                    _get_access_token("https://example.supabase.co", "public-test-key", 3)
                self.assertEqual(_AUTH["access_token"], "")
                self.assertEqual(_AUTH["refresh_token"], "stale-refresh-token")
                self.assertEqual(_AUTH["expires_at"], 0.0)
                self.assertTrue(_AUTH["refresh_failed"])
                self.assertTrue(blocked_file.exists())

                token = _get_access_token("https://example.supabase.co", "public-test-key", 3)
                self.assertEqual(token, "recovered-jwt")
                self.assertEqual(request.call_count, 2)
                self.assertTrue(all(
                    "/auth/v1/token?grant_type=refresh_token" in call.args[0]
                    for call in request.call_args_list
                ))
                self.assertFalse(blocked_file.exists())
                self.assertFalse(_AUTH["refresh_failed"])

    def test_permanent_refresh_failure_blocks_signup_until_explicit_reset(self):
        with TemporaryDirectory() as folder:
            blocked_file = Path(folder) / "refresh.blocked"
            session_file = Path(folder) / "session.dat"
            with patch("core.supabase_cloud_provider._SESSION_FILE", session_file), \
                 patch("core.supabase_cloud_provider._SESSION_BLOCKED_FILE", blocked_file), \
                 patch.dict(_AUTH, {
                     "access_token": "", "refresh_token": "invalid-refresh-token",
                     "expires_at": 0.0, "refresh_failed": False,
                 }), \
                 patch("core.supabase_cloud_provider._load_persisted_refresh_token", return_value=""), \
                 patch("core.supabase_cloud_provider._request_json", side_effect=RuntimeError(
                     "Supabase request failed with HTTP 401"
                 )) as request:
                with self.assertRaisesRegex(RuntimeError, "session refresh failed"):
                    _get_access_token("https://example.supabase.co", "public-test-key", 3)
                self.assertEqual(_AUTH["refresh_token"], "")
                self.assertTrue(_AUTH["refresh_failed"])
                self.assertTrue(blocked_file.exists())

                # Simulate a new process: the persisted marker still blocks signup.
                _AUTH["refresh_failed"] = False
                with self.assertRaisesRegex(RuntimeError, "explicitly reset/re-enroll"):
                    _get_access_token("https://example.supabase.co", "public-test-key", 3)
                self.assertEqual(request.call_count, 1)
                self.assertFalse(any(
                    "/auth/v1/signup" in call.args[0]
                    for call in request.call_args_list
                ))

                request.side_effect = None
                request.return_value = {
                    "access_token": "new-enrollment-jwt",
                    "refresh_token": "new-enrollment-refresh",
                    "expires_in": 3600,
                }
                reset_supabase_auth_session()
                self.assertFalse(blocked_file.exists())
                self.assertFalse(_AUTH["refresh_failed"])
                token = _get_access_token("https://example.supabase.co", "public-test-key", 3)
                self.assertEqual(token, "new-enrollment-jwt")
                self.assertIn("/auth/v1/signup", request.call_args.args[0])
                self.assertEqual(request.call_count, 2)

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

    def test_windows_refresh_token_is_encrypted_and_reloaded(self):
        with TemporaryDirectory() as folder:
            session_file = Path(folder) / "session.dat"
            protect = lambda value: b"dpapi:" + value
            unprotect = lambda value: value.removeprefix(b"dpapi:")
            with patch("core.supabase_cloud_provider.sys.platform", "win32"):
                with patch("core.supabase_cloud_provider._SESSION_FILE", session_file):
                    with patch("security.auth_manager._dpapi_protect", side_effect=protect):
                        with patch("security.auth_manager._dpapi_unprotect", side_effect=unprotect):
                            _persist_refresh_token("refresh-secret")
                            self.assertNotEqual(session_file.read_bytes(), b"refresh-secret")
                            self.assertEqual(_load_persisted_refresh_token(), "refresh-secret")

    def test_macos_native_keyring_persists_supabase_identity(self):
        class FakeKeyring:
            values = {}

            @classmethod
            def set_password(cls, service, account, value):
                cls.values[(service, account)] = value

            @classmethod
            def get_password(cls, service, account):
                return cls.values.get((service, account))

        with patch("core.supabase_cloud_provider.sys.platform", "darwin"), \
             patch("core.supabase_cloud_provider._native_keyring", return_value=FakeKeyring), \
             patch.dict(_AUTH, {
                 "access_token": "access-test",
                 "refresh_token": "refresh-test",
                 "expires_at": 9999999999.0,
                 "refresh_failed": False,
             }):
            _persist_refresh_token("refresh-test")
            self.assertEqual(_load_persisted_refresh_token(), "refresh-test")
            from core.supabase_cloud_provider import has_persistent_auth_session
            self.assertTrue(has_persistent_auth_session())

    def test_missing_public_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "configuration is incomplete"):
                call_supabase_provider(provider="gemini", prompt="hello", system_prompt="JARVIS")


if __name__ == "__main__":
    unittest.main()
