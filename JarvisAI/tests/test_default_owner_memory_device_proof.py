"""Device-proof tests for the shared default-owner profile endpoint client."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from core.personal_cloud_memory import _request_default_owner_memory


class DefaultOwnerMemoryDeviceProofTests(unittest.TestCase):
    def test_default_profile_request_includes_enrolled_device_signature(self):
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"ok": True, "profile": {"nickname": "Owner"}}
        ).encode("utf-8")
        signed = {
            "X-Jarvis-Host-Timestamp": "1793500000",
            "X-Jarvis-Host-Nonce": "unique-test-nonce-123456",
            "X-Jarvis-Host-Signature": "c2lnbmF0dXJl",
        }
        with patch.dict(os.environ, env, clear=True), \
             patch("core.supabase_cloud_provider._get_access_token", return_value="auth-jwt"), \
             patch("core.supabase_cloud_provider.has_persistent_auth_session", return_value=True), \
             patch("security.host_device_identity.sign_request", return_value=signed) as sign, \
             patch("security.host_device_identity.public_key_b64", return_value="cHVibGljLWtleQ=="), \
             patch("core.personal_cloud_memory.urllib.request.urlopen", return_value=response) as urlopen:
            result = _request_default_owner_memory(timeout=3)

        self.assertEqual(result, {"nickname": "Owner"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.data, b"{}")
        sign.assert_called_once_with(b"{}")
        self.assertEqual(request.get_header("X-jarvis-host-key"), "cHVibGljLWtleQ==")
        self.assertEqual(request.get_header("X-jarvis-host-signature"), signed["X-Jarvis-Host-Signature"])
        self.assertEqual(request.get_header("Authorization"), "Bearer auth-jwt")


if __name__ == "__main__":
    unittest.main()
