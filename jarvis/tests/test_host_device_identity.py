"""Cross-platform host-device key storage tests."""
from __future__ import annotations

import base64
import sys
import types
import unittest
from unittest.mock import patch

from jarvis.security import host_device_identity as identity


class HostDeviceIdentityTests(unittest.TestCase):
    def test_linux_uses_secret_service_keyring_and_persists_key(self):
        values = {}
        backend = type(
            "SecretServiceBackend", (),
            {"__module__": "keyring.backends.SecretService"},
        )()
        fake_keyring = types.ModuleType("keyring")
        fake_keyring.get_keyring = lambda: backend
        fake_keyring.get_password = lambda service, account: values.get((service, account))
        fake_keyring.set_password = lambda service, account, value: values.__setitem__((service, account), value)

        with patch.dict(sys.modules, {"keyring": fake_keyring}), \
             patch.object(identity.sys, "platform", "linux"):
            first = identity._keyring_private_key()
            second = identity._keyring_private_key()

        first_raw = first.private_bytes(
            identity.serialization.Encoding.Raw,
            identity.serialization.PrivateFormat.Raw,
            identity.serialization.NoEncryption(),
        )
        second_raw = second.private_bytes(
            identity.serialization.Encoding.Raw,
            identity.serialization.PrivateFormat.Raw,
            identity.serialization.NoEncryption(),
        )
        self.assertEqual(first_raw, second_raw)
        self.assertEqual(len(base64.b64decode(next(iter(values.values())))), 32)

    def test_macos_uses_keychain_keyring_and_persists_key(self):
        values = {}
        backend = type(
            "MacOSKeychainBackend", (),
            {"__module__": "keyring.backends.macOS"},
        )()
        fake_keyring = types.ModuleType("keyring")
        fake_keyring.get_keyring = lambda: backend
        fake_keyring.get_password = lambda service, account: values.get((service, account))
        fake_keyring.set_password = lambda service, account, value: values.__setitem__((service, account), value)

        with patch.dict(sys.modules, {"keyring": fake_keyring}), \
             patch.object(identity.sys, "platform", "darwin"):
            first = identity._keyring_private_key()
            second = identity._keyring_private_key()

        first_raw = first.private_bytes(
            identity.serialization.Encoding.Raw,
            identity.serialization.PrivateFormat.Raw,
            identity.serialization.NoEncryption(),
        )
        second_raw = second.private_bytes(
            identity.serialization.Encoding.Raw,
            identity.serialization.PrivateFormat.Raw,
            identity.serialization.NoEncryption(),
        )
        self.assertEqual(first_raw, second_raw)

    def test_unknown_keyring_backend_fails_closed(self):
        backend = type("PlaintextBackend", (), {"__module__": "keyring.backends.fail"})()
        fake_keyring = types.ModuleType("keyring")
        fake_keyring.get_keyring = lambda: backend
        with patch.dict(sys.modules, {"keyring": fake_keyring}), \
             patch.object(identity.sys, "platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "native OS credential store"):
                identity._keyring_private_key()


if __name__ == "__main__":
    unittest.main()
