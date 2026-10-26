"""Unit tests for Gemini Live model and API-version selection policy."""

from __future__ import annotations

import unittest

from core.live_session import select_live_api_version, select_live_model


PRIMARY = "models/live-primary"
FALLBACKS = ("models/live-fallback", "models/live-proactive")


class LiveSessionPolicyTests(unittest.TestCase):
    def test_prefers_available_primary_model(self):
        self.assertEqual(
            select_live_model(
                primary_model=PRIMARY,
                fallback_models=FALLBACKS,
                cooldowns={},
                now=100.0,
                proactive_audio_enabled=True,
                proactive_audio_model="models/live-proactive",
            ),
            PRIMARY,
        )

    def test_skips_models_still_in_cooldown(self):
        self.assertEqual(
            select_live_model(
                primary_model=PRIMARY,
                fallback_models=FALLBACKS,
                cooldowns={PRIMARY: 200.0, FALLBACKS[0]: 150.0},
                now=100.0,
                proactive_audio_enabled=True,
                proactive_audio_model=FALLBACKS[1],
            ),
            FALLBACKS[1],
        )

    def test_when_all_models_are_cooling_retries_earliest_expiry(self):
        self.assertEqual(
            select_live_model(
                primary_model=PRIMARY,
                fallback_models=FALLBACKS,
                cooldowns={PRIMARY: 300.0, FALLBACKS[0]: 250.0, FALLBACKS[1]: 275.0},
                now=100.0,
                proactive_audio_enabled=True,
                proactive_audio_model=FALLBACKS[1],
            ),
            FALLBACKS[0],
        )

    def test_proactive_audio_model_is_excluded_when_setting_is_off(self):
        self.assertEqual(
            select_live_model(
                primary_model=PRIMARY,
                fallback_models=FALLBACKS,
                cooldowns={PRIMARY: 200.0, FALLBACKS[0]: 150.0},
                now=100.0,
                proactive_audio_enabled=False,
                proactive_audio_model=FALLBACKS[1],
            ),
            FALLBACKS[0],
        )

    def test_rejects_empty_candidate_list(self):
        with self.assertRaisesRegex(ValueError, "At least one"):
            select_live_model(
                primary_model="",
                fallback_models=(),
                cooldowns={},
                now=1.0,
                proactive_audio_enabled=False,
                proactive_audio_model="",
            )

    def test_enhanced_primary_uses_alpha_api(self):
        self.assertEqual(
            select_live_api_version(
                enhanced_live=True,
                active_model=PRIMARY,
                primary_model=PRIMARY,
            ),
            "v1alpha",
        )

    def test_fallback_uses_beta_api_even_when_enhanced_is_enabled(self):
        self.assertEqual(
            select_live_api_version(
                enhanced_live=True,
                active_model=FALLBACKS[0],
                primary_model=PRIMARY,
            ),
            "v1beta",
        )

    def test_regular_primary_uses_beta_api(self):
        self.assertEqual(
            select_live_api_version(
                enhanced_live=False,
                active_model=PRIMARY,
                primary_model=PRIMARY,
            ),
            "v1beta",
        )


if __name__ == "__main__":
    unittest.main()
