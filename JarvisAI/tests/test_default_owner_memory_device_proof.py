"""Device-proof and transport-security tests for default owner memory."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.personal_cloud_memory import (
    _NoRedirectHandler,
    _request_default_owner_memory,
)


class DefaultOwnerMemoryDeviceProofTests(unittest.TestCase):
    def test_default_profile_request_uses_real_ed25519_signature(self):
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        }
        private_key = Ed25519PrivateKey.generate()
        public_raw = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"ok": True, "profile": {"nickname": "Owner"}}
        ).encode("utf-8")
        opener = MagicMock()
        opener.open.return_value = response

        with patch.dict(os.environ, env, clear=True), \\
             patch("core.supabase_cloud_provider._get_access_token", return_value="auth-jwt"), \\
             patch("core.supabase_cloud_provider.has_persistent_auth_session", return_value=True), \\
             patch("security.host_device_identity._private_key", return_value=private_key), \\
             patch("urllib.request.build_opener", return_value=opener) as build_opener:
            result = _request_default_owner_memory(timeout=3)

        self.assertEqual(result, {"nickname": "Owner"})
        build_opener.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.data, b"{}")
        self.assertEqual(request.get_header("Authorization"), "Bearer auth-jwt")
        self.assertEqual(
            request.get_header("X-jarvis-host-key"),
            base64.b64encode(public_raw).decode("ascii"),
        )
        timestamp = request.get_header("X-jarvis-host-timestamp")
        nonce = request.get_header("X-jarvis-host-nonce")
        signature = base64.b64decode(request.get_header("X-jarvis-host-signature"))
        digest = hashlib.sha256(b"{}").hexdigest()
        signed_message = f"JARVIS-HOST-V1\\n{timestamp}\\n{nonce}\\n{digest}".encode("utf-8")
        private_key.public_key().verify(signature, signed_message)

    def test_http_supabase_url_is_rejected_before_credentials_are_requested(self):
        env = {
            "SUPABASE_URL": "http://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        }
        with patch.dict(os.environ, env, clear=True), \\
             patch("core.supabase_cloud_provider._get_access_token") as get_token:
            with self.assertRaisesRegex(RuntimeError, "HTTPS"):
                _request_default_owner_memory()
        get_token.assert_not_called()

    def test_redirect_handler_never_forwards_credentials(self):
        handler = _NoRedirectHandler()
        request = __import__("urllib.request", fromlist=["Request"]).Request(
            "https://example.supabase.co/functions/v1/jarvis-default-owner-memory",
            data=b"{}",
        )
        self.assertIsNone(
            handler.redirect_request(
                request, None, 302, "Found", {},
                "http://attacker.example/collect",
            )
        )


if __name__ == "__main__":
    unittest.main()
