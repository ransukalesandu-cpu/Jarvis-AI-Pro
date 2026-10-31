"""Tests for the shared hologram palette and visual preferences.

These are pure-logic tests: ``core/hologram_theme.py`` deliberately imports no Qt
so the colour identity can be verified (and reused by the headless core) without
a display server.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import unittest

from core.hologram_theme import (
    BIHANSA_PALETTE,
    JARVIS_PALETTE,
    PALETTES,
    STATE_ACCENTS,
    ThemePalette,
    VisualPreferences,
    palette_for_mode,
    state_accent,
)


class FakeSettings:
    """Minimal QSettings stand-in that can also return junk."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None):
        return self.values.get(key, default)


class TestPalettes(unittest.TestCase):
    def test_palettes_are_frozen_and_complete(self):
        for palette in PALETTES.values():
            self.assertIsInstance(palette, ThemePalette)
            for rgb in (palette.primary, palette.secondary, palette.glow,
                        palette.accent, palette.deep, palette.heart_red,
                        palette.heart_pink, palette.heart_orange):
                self.assertEqual(len(rgb), 3)
                self.assertTrue(all(isinstance(c, int) and 0 <= c <= 255 for c in rgb))

    def test_jarvis_is_copper_and_bihansa_is_pink(self):
        # JARVIS: copper orange, red dominant with a warm amber middle channel.
        self.assertGreater(JARVIS_PALETTE.primary[0], 200)
        self.assertGreater(JARVIS_PALETTE.primary[1], 120)
        self.assertGreater(JARVIS_PALETTE.primary[0], JARVIS_PALETTE.primary[2])
        # Bihansa: rose pink, red and blue both high, green lower.
        self.assertGreater(BIHANSA_PALETTE.primary[0], 200)
        self.assertGreater(BIHANSA_PALETTE.primary[2], 150)
        self.assertNotEqual(JARVIS_PALETTE.primary, BIHANSA_PALETTE.primary)

    def test_palette_for_mode(self):
        self.assertIs(palette_for_mode("jarvis"), JARVIS_PALETTE)
        self.assertIs(palette_for_mode("BIHANSA"), BIHANSA_PALETTE)
        self.assertIs(palette_for_mode(" Bihansa "), BIHANSA_PALETTE)
        self.assertIs(palette_for_mode(None), JARVIS_PALETTE)
        self.assertIs(palette_for_mode("nonsense"), JARVIS_PALETTE)

    def test_scaled_brightens_but_keeps_depth(self):
        bright = JARVIS_PALETTE.scaled(1.4)
        self.assertTrue(all(a >= b for a, b in zip(bright.primary, JARVIS_PALETTE.primary)))
        self.assertEqual(bright.deep, JARVIS_PALETTE.deep)
        # Extreme factors clamp instead of overflowing 8-bit channels.
        hot = JARVIS_PALETTE.scaled(99)
        self.assertTrue(all(c <= 255 for c in hot.primary))
        dim = JARVIS_PALETTE.scaled(0.0)
        self.assertEqual(dim.primary, tuple(int(c * 0.2) for c in JARVIS_PALETTE.primary))

    def test_palette_dict_roundtrip(self):
        data = BIHANSA_PALETTE.as_dict()
        self.assertEqual(data["mode"], "bihansa")
        self.assertEqual(data["primary"], BIHANSA_PALETTE.primary)


class TestStateAccent(unittest.TestCase):
    def test_known_states(self):
        self.assertEqual(state_accent("idle"), 0.0)
        self.assertGreater(state_accent("SPEAKING"), state_accent("LISTENING"))
        self.assertEqual(state_accent("PRIVACY_LOCK"), 0.0)

    def test_unknown_state_is_neutral(self):
        self.assertEqual(state_accent("SOMETHING_NEW"), 0.0)
        self.assertEqual(state_accent(None), 0.0)
        self.assertEqual(set(STATE_ACCENTS) >= {"IDLE", "LISTENING", "THINKING", "SPEAKING"}, True)


class TestVisualPreferences(unittest.TestCase):
    def test_validated_clamps_and_normalises_mode(self):
        prefs = VisualPreferences(
            mode="BiHaNsA", glow=9.0, animation_speed=-1.0, particle_intensity=4.0,
            glass_opacity=0.0, hologram_scale=5.0,
        ).validated()
        self.assertEqual(prefs.mode, "bihansa")
        self.assertAlmostEqual(prefs.glow, 1.6)
        self.assertAlmostEqual(prefs.animation_speed, 0.0)
        self.assertAlmostEqual(prefs.particle_intensity, 1.0)
        self.assertAlmostEqual(prefs.glass_opacity, 0.35)
        self.assertAlmostEqual(prefs.hologram_scale, 1.3)

    def test_unknown_mode_falls_back_to_jarvis(self):
        self.assertEqual(VisualPreferences(mode="klingon").validated().mode, "jarvis")

    def test_palette_properties(self):
        prefs = VisualPreferences(mode="bihansa", glow=1.0)
        self.assertIs(prefs.palette, BIHANSA_PALETTE)
        self.assertEqual(prefs.scaled_palette().primary, BIHANSA_PALETTE.primary)

    def test_from_settings_with_defaults(self):
        prefs = VisualPreferences.from_settings(FakeSettings())
        self.assertEqual(prefs.mode, "jarvis")
        self.assertTrue(prefs.battery_saver)
        self.assertTrue(prefs.charging_effects)
        self.assertFalse(prefs.reduced_motion)

    def test_from_settings_reads_persisted_values(self):
        prefs = VisualPreferences.from_settings(FakeSettings({
            "visual/mode": "bihansa",
            "visual/glow": "1.25",
            "visual/reduced_motion": "true",
            "visual/battery_saver": "off",
            "visual/charging_effects": "0",
        }))
        self.assertEqual(prefs.mode, "bihansa")
        self.assertAlmostEqual(prefs.glow, 1.25)
        self.assertTrue(prefs.reduced_motion)
        self.assertFalse(prefs.battery_saver)
        self.assertFalse(prefs.charging_effects)

    def test_from_settings_survives_junk_and_broken_settings(self):
        junk = FakeSettings({
            "visual/glow": "not-a-number",
            "visual/reduced_motion": "maybe",
            "visual/mode": "",
        })
        prefs = VisualPreferences.from_settings(junk)
        self.assertAlmostEqual(prefs.glow, 1.0)
        self.assertFalse(prefs.reduced_motion)
        self.assertEqual(prefs.mode, "jarvis")

        class Exploding:
            def value(self, *args, **kwargs):
                raise RuntimeError("settings backend gone")

        fallback = VisualPreferences.from_settings(Exploding(), fallback_mode="bihansa")
        self.assertEqual(fallback.mode, "bihansa")
        self.assertAlmostEqual(fallback.glow, 1.0)


if __name__ == "__main__":
    unittest.main()
