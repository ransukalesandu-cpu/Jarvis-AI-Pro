"""
tests/test_auth_flow.py — Root unit tests for Voice Biometrics, Auth Manager, and Dispatcher.
"""

import os
import sys
import unittest
import numpy as np
import tempfile
import time
import subprocess
from pathlib import Path

# Adjust sys.path
BASE_DIR = Path(__file__).resolve().parent.parent / "JarvisAI"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from security.voice_auth import SpeakerAuthenticator, compute_cosine_similarity, EMBEDDING_DIM
from security.auth_manager import (
    AuthManager, RESTRICTED_MODE, FULL_ACCESS_MODE, CHALLENGE_MODE, PRIVACY_LOCK
)
from core.dispatcher import ActionDispatcher, TIER_1_BASIC, TIER_2_PRIVILEGED


class TestAuthFlow(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = BASE_DIR / "tests" / "tmp_auth"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.emb_path = self.tmp_dir / "master_voice.emb"
        self.vault_path = self.tmp_dir / "pin_vault.dat"
        self.state_path = self.tmp_dir / "auth_state.json"

        self.authenticator = SpeakerAuthenticator(emb_path=self.emb_path)
        self.auth_manager = AuthManager(
            vault_path=self.vault_path,
            state_path=self.state_path,
            voice_authenticator=self.authenticator,
            cooldown_seconds=60,
        )

    def tearDown(self):
        import shutil
        if self.tmp_dir.exists():
            try:
                shutil.rmtree(self.tmp_dir)
            except Exception:
                pass

    def test_default_unenrolled_state_fails_closed(self):
        """Default unenrolled state fails closed until enrolled."""
        self.assertFalse(self.auth_manager.is_pin_enrolled())
        self.assertFalse(self.auth_manager.verify_pin("1234"))

    def test_enroll_pin_and_successful_verification(self):
        """Enrolling PIN and verifying grants FULL_ACCESS_MODE."""
        self.auth_manager.set_master_pin("5678")
        self.assertTrue(self.auth_manager.is_pin_enrolled())

        # Correct PIN grants FULL_ACCESS_MODE
        self.assertTrue(self.auth_manager.verify_pin("5678"))
        self.assertEqual(self.auth_manager.get_state(), FULL_ACCESS_MODE)
        self.assertEqual(self.auth_manager.failed_pin_attempts, 0)

    def test_three_failed_pin_attempts_trigger_privacy_lock(self):
        """3 failed PIN attempts trigger Privacy Lock, persisting cooldown state."""
        self.auth_manager.set_master_pin("1234")

        self.assertFalse(self.auth_manager.verify_pin("0000"))
        self.assertEqual(self.auth_manager.failed_pin_attempts, 1)

        self.assertFalse(self.auth_manager.verify_pin("0000"))
        self.assertEqual(self.auth_manager.failed_pin_attempts, 2)

        # 3rd failure triggers Privacy Lock
        self.assertFalse(self.auth_manager.verify_pin("0000"))
        self.assertEqual(self.auth_manager.get_state(), PRIVACY_LOCK)

        # Check state file persistence
        self.assertTrue(self.state_path.exists())

    def test_privacy_lock_cooldown_expiration(self):
        """Privacy Lock state expires after cooldown."""
        self.auth_manager.set_master_pin("1234")
        self.auth_manager.trigger_privacy_lock("test cooldown")
        self.assertEqual(self.auth_manager.get_state(), PRIVACY_LOCK)

        # Fast forward cooldown in persistent file
        self.auth_manager.lock_until = time.time() - 1.0
        self.auth_manager._save_persistent_state()

        # State transitions out of PRIVACY_LOCK
        self.assertEqual(self.auth_manager.get_state(), CHALLENGE_MODE)

    def test_recall_memory_and_private_actions_in_tier2(self):
        """recall_memory, save_memory, and unknown actions are Tier 2 Privileged."""
        self.assertEqual(ActionDispatcher.get_action_tier("recall_memory"), TIER_2_PRIVILEGED)
        self.assertEqual(ActionDispatcher.get_action_tier("save_memory"), TIER_2_PRIVILEGED)
        self.assertEqual(ActionDispatcher.get_action_tier("unknown_custom_action"), TIER_2_PRIVILEGED)

        # Blocked in RESTRICTED_MODE
        allowed, prompt = ActionDispatcher.can_dispatch("recall_memory", RESTRICTED_MODE)
        self.assertFalse(allowed)
        self.assertEqual(prompt, "Voice identity unconfirmed. Please enter or speak your PIN.")

    def test_no_committed_credential_artifacts(self):
        """Verify no sensitive credential/voice artifacts are tracked in git."""
        res = subprocess.run(
            ["git", "ls-files", "JarvisAI/config/pin_vault.dat", "JarvisAI/config/auth_state.json", "master_voice.emb", "master_voice.emb.npy"],
            capture_output=True, text=True
        )
        self.assertEqual(res.stdout.strip(), "")

    def test_cosine_similarity_grant_full_access(self):
        """Cosine similarity >= 0.80 grants FULL_ACCESS_MODE when enrolled."""
        vec_master = np.random.randn(EMBEDDING_DIM).astype(np.float32)
        vec_master /= np.linalg.norm(vec_master)
        self.authenticator.save_master_profile(vec_master, filepath=self.emb_path)

        noise = np.random.randn(EMBEDDING_DIM).astype(np.float32) * 0.01
        vec_match = vec_master + noise
        vec_match /= np.linalg.norm(vec_match)

        similarity = compute_cosine_similarity(vec_master, vec_match)
        self.assertGreaterEqual(similarity, 0.80)

        state, msg = self.auth_manager.process_voice_result(
            is_master=True, similarity=similarity, is_live=True, is_stranger=False
        )
        self.assertEqual(state, FULL_ACCESS_MODE)


if __name__ == "__main__":
    unittest.main()
