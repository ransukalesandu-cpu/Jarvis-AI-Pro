import json
import os
import unittest
from unittest.mock import MagicMock, patch

from core.personal_cloud_memory import _request_default_owner_memory


class DefaultOwnerMemoryHostBindingTests(unittest.TestCase):
    def test_guest_mode_request_is_signed_by_the_enrolled_device(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "ok": True,
            "profile": {"nickname": "Owner"},
        }).encode("utf-8")
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        }
        signature_headers = {
            "X-Jarvis-Host-Timestamp": "1793560000",
            "X-Jarvis-Host-Nonce": "nonce-value-that-is-long-enough",
            "X-Jarvis-Host-Signature": "signature-base64",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("core.supabase_cloud_provider._get_access_token", return_value="session-jwt"):
                with patch("core.supabase_cloud_provider.has_persistent_auth_session", return_value=True):
                    with patch("security.host_device_identity.sign_request", return_value=signature_headers) as sign:
                        with patch("security.host_device_identity.public_key_b64", return_value="device-public-key"):
                            with patch("core.personal_cloud_memory.urllib.request.urlopen", return_value=response) as urlopen:
                                profile = _request_default_owner_memory()

        self.assertEqual(profile, {"nickname": "Owner"})
        sign.assert_called_once_with(b"{}")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.data, b"{}")
        self.assertEqual(request.get_header("X-jarvis-host-key"), "device-public-key")
        self.assertEqual(request.get_header("X-jarvis-host-signature"), "signature-base64")
        self.assertEqual(request.get_header("Authorization"), "Bearer session-jwt")

    def test_request_fails_closed_without_persistent_installation_identity(self):
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("core.supabase_cloud_provider._get_access_token", return_value="session-jwt"):
                with patch("core.supabase_cloud_provider.has_persistent_auth_session", return_value=False):
                    with patch("security.host_device_identity.sign_request") as sign:
                        with self.assertRaisesRegex(RuntimeError, "stable OS-protected"):
                            _request_default_owner_memory()
        sign.assert_not_called()


if __name__ == "__main__":
    unittest.main()
