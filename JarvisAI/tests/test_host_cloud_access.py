import unittest

from security.host_cloud_access import host_session_verified


class FakeManager:
    def __init__(self, allowed=True, factors=True):
        self.allowed = allowed
        self.factors = factors

    def is_owner_access_allowed(self):
        return self.allowed

    def owner_factors_verified(self):
        return self.factors


class HostCloudAccessTests(unittest.TestCase):
    def test_requires_both_owner_factors(self):
        self.assertTrue(host_session_verified(FakeManager(True, True)))
        self.assertFalse(host_session_verified(FakeManager(True, False)))
        self.assertFalse(host_session_verified(FakeManager(False, True)))
        self.assertFalse(host_session_verified(None))

    def test_missing_factor_method_fails_closed(self):
        class OldManager:
            def is_owner_access_allowed(self):
                return True

        self.assertFalse(host_session_verified(OldManager()))


if __name__ == "__main__":
    unittest.main()
