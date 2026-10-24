"""
JarvisAI/tests/test_auth_flow.py — Unit tests for Voice Biometrics, Auth Manager, and Dispatcher.
"""

import sys
import unittest
import numpy as np
from pathlib import Path

# Adjust sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from security.voice_auth import SpeakerAuthenticator, compute_cosine_similarity, EMBEDDING_DIM
from security.auth_manager import (
    AuthManager, RESTRICTED_MODE, FULL_ACCESS_MODE, CHALLENGE_MODE, PRIVACY_LOCK
)
from core.dispatcher import ActionDispatcher, TIER_1_BASIC, TIER_2_PRIVILEGED
from core import security


class TestAuthFlow(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = BASE_DIR / "tests" / "tmp_auth"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.emb_path = self.tmp_dir / "master_voice.emb"
        self.vault_path = self.tmp_dir / "pin_vault.dat"

        self.authenticator = SpeakerAuthenticator(emb_path=self.emb_path)
        self.auth_manager = AuthManager(vault_path=self.vault_path, voice_authenticator=self.authenticator)
        self.auth_manager.set_master_pin("1234")

    def tearDown(self):
        import shutil
        if self.tmp_dir.exists():
            try:
                shutil.rmtree(self.tmp_dir)
            except Exception:
                pass

    def test_cosine_similarity_grant_full_access(self):
        """1. Cosine similarity >= 0.80 grants FULL_ACCESS_MODE."""
        # Generate master embedding vector
        vec_master = np.random.randn(EMBEDDING_DIM).astype(np.float32)
        vec_master /= np.linalg.norm(vec_master)
        self.authenticator.save_master_profile(vec_master, filepath=self.emb_path)

        # Test vector with similarity >= 0.80
        noise = np.random.randn(EMBEDDING_DIM).astype(np.float32) * 0.05
        vec_match = vec_master + noise
        vec_match /= np.linalg.norm(vec_match)

        similarity = compute_cosine_similarity(vec_master, vec_match)
        self.assertGreaterEqual(similarity, 0.80)

        # Evaluate through auth manager
        state, msg = self.auth_manager.process_voice_result(
            is_master=True, similarity=similarity, is_live=True, is_stranger=False
        )
        self.assertEqual(state, FULL_ACCESS_MODE)
        self.assertEqual(self.auth_manager.get_state(), FULL_ACCESS_MODE)

    def test_stranger_speech_tier1_vs_tier2(self):
        """2. Stranger speech allows Tier 1 tasks but blocks Tier 2 tasks in RESTRICTED_MODE."""
        self.auth_manager.set_state(RESTRICTED_MODE)

        # Verify Tier 1 action allowed
        allowed_t1, prompt_t1 = ActionDispatcher.can_dispatch("weather_report", RESTRICTED_MODE)
        self.assertTrue(allowed_t1)
        self.assertEqual(prompt_t1, "Allowed")

        # Verify Tier 2 action blocked and prompts for PIN
        allowed_t2, prompt_t2 = ActionDispatcher.can_dispatch("computer_control", RESTRICTED_MODE)
        self.assertFalse(allowed_t2)
        self.assertEqual(prompt_t2, "Voice identity unconfirmed. Please enter or speak your PIN.")

    def test_successful_pin_entry_clears_failures(self):
        """3. Successful PIN entry switches state to FULL_ACCESS_MODE and clears failure counters."""
        self.auth_manager.set_state(CHALLENGE_MODE)
        self.auth_manager.failed_pin_attempts = 3

        # Enter wrong PIN
        res_wrong = self.auth_manager.verify_pin("9999")
        self.assertFalse(res_wrong)
        self.assertEqual(self.auth_manager.failed_pin_attempts, 4)

        # Enter correct PIN
        res_correct = self.auth_manager.verify_pin("1234")
        self.assertTrue(res_correct)
        self.assertEqual(self.auth_manager.get_state(), FULL_ACCESS_MODE)
        self.assertEqual(self.auth_manager.failed_pin_attempts, 0)

    def test_no_legacy_confirmation_in_full_access_mode(self):
        """4. Verify actions execute immediately in FULL_ACCESS_MODE without manual confirmation gates."""
        security.set_auth_state(FULL_ACCESS_MODE)

        executed = False
        def my_action():
            nonlocal executed
            executed = True
            return "Action Result"

        res = security.guard("computer_control", {"action": "type"}, my_action)
        self.assertTrue(executed)
        self.assertEqual(res, "Action Result")


if __name__ == "__main__":
    unittest.main()
