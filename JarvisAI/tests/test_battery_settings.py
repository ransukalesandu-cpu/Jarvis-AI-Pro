"""Tests for the persisted battery bands and the dialog that edits them.

The bands decide when the user is warned and when the visuals get cheaper, so
two things are non-negotiable: a corrupt settings file must degrade to the
defaults rather than crash, and an out-of-order set must never reach the disk
unvalidated.
"""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

if sys.platform != "win32" and not os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import unittest

from core.battery_settings import KEYS, describe, load_thresholds, save_thresholds
from core.system_status import BatteryThresholds


class FakeSettings:
    """Minimal ``QSettings`` stand-in (dict semantics, no registry)."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.synced = 0

    def value(self, key, default=None, type=None):  # noqa: A002 - QSettings signature
        return self.values.get(key, default)

    def setValue(self, key, value):  # noqa: N802 - QSettings API
        self.values[key] = value

    def sync(self):
        self.synced += 1


class BrokenSettings(FakeSettings):
    def value(self, key, default=None, type=None):  # noqa: A002 - QSettings signature
        raise RuntimeError("registry locked")

    def setValue(self, key, value):  # noqa: N802 - QSettings API
        raise RuntimeError("registry locked")


class TestLoadThresholds(unittest.TestCase):
    def test_no_settings_yields_the_defaults(self):
        self.assertEqual(load_thresholds(None), BatteryThresholds())

    def test_persisted_values_are_used(self):
        settings = FakeSettings({
            KEYS["fifty"]: 60, KEYS["low"]: 30,
            KEYS["critical"]: 12, KEYS["full"]: 95,
        })
        bands = load_thresholds(settings)
        self.assertEqual((bands.fifty, bands.low, bands.critical, bands.full), (60, 30, 12, 95))

    def test_junk_values_fall_back_to_defaults(self):
        settings = FakeSettings({
            KEYS["fifty"]: "not a number", KEYS["low"]: None,
            KEYS["critical"]: True, KEYS["full"]: "88",
        })
        bands = load_thresholds(settings)
        self.assertEqual(bands.fifty, BatteryThresholds().fifty)
        self.assertEqual(bands.low, BatteryThresholds().low)
        # A bool is not a level, even though bool is an int subclass.
        self.assertEqual(bands.critical, BatteryThresholds().critical)
        self.assertEqual(bands.full, 88)

    def test_unreadable_settings_degrade_instead_of_raising(self):
        self.assertEqual(load_thresholds(BrokenSettings()), BatteryThresholds())

    def test_out_of_order_stored_values_are_clamped_on_read(self):
        settings = FakeSettings({
            KEYS["fifty"]: 40, KEYS["low"]: 80,
            KEYS["critical"]: 70, KEYS["full"]: 50,
        })
        bands = load_thresholds(settings)
        self.assertLess(bands.critical, bands.low)
        self.assertLess(bands.low, bands.fifty)
        self.assertGreater(bands.full, bands.fifty)


class TestSaveThresholds(unittest.TestCase):
    def test_saving_writes_every_key_and_syncs(self):
        settings = FakeSettings()
        saved = save_thresholds(settings, BatteryThresholds(55, 20, 8, 100))
        self.assertEqual(saved, BatteryThresholds(55, 20, 8, 100))
        for field, key in KEYS.items():
            self.assertEqual(settings.values[key], getattr(saved, field))
        self.assertEqual(settings.synced, 1)

    def test_saving_validates_an_impossible_set(self):
        settings = FakeSettings()
        saved = save_thresholds(settings, BatteryThresholds(fifty=40, low=90, critical=95, full=30))
        self.assertLess(saved.critical, saved.low)
        self.assertLess(saved.low, saved.fifty)
        self.assertGreaterEqual(saved.full, saved.fifty + 1)
        # What was persisted is exactly what was returned.
        self.assertEqual(load_thresholds(settings), saved)

    def test_a_broken_backend_does_not_raise(self):
        saved = save_thresholds(BrokenSettings(), BatteryThresholds(50, 25, 10, 100))
        self.assertEqual(saved, BatteryThresholds(50, 25, 10, 100))

    def test_none_settings_still_validates(self):
        self.assertEqual(
            save_thresholds(None, BatteryThresholds(200, 200, 200, -5)),
            BatteryThresholds(200, 200, 200, -5).validated(),
        )


class TestDescribe(unittest.TestCase):
    def test_description_lists_every_band(self):
        text = describe(BatteryThresholds(50, 25, 10, 100))
        self.assertIn("Critical ≤ 10%", text)
        self.assertIn("Low ≤ 25%", text)
        self.assertIn("Half ≤ 50%", text)
        self.assertIn("Full ≥ 100%", text)

    def test_description_is_validated_before_display(self):
        self.assertIn("Full ≥", describe(BatteryThresholds(fifty=40, low=90, critical=95, full=0)))


class TestThresholdsDialog(unittest.TestCase):
    """The dialog is a thin editor: it validates, it does not apply anything."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _dialog(self, thresholds=None):
        from ui.panels.battery_settings import BatteryThresholdsDialog

        dialog = BatteryThresholdsDialog(thresholds)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_it_opens_on_the_supplied_values(self):
        dialog = self._dialog(BatteryThresholds(60, 30, 12, 95))
        self.assertEqual(dialog.thresholds(), BatteryThresholds(60, 30, 12, 95))

    def test_saving_emits_the_validated_set_not_the_raw_spin_values(self):
        from PyQt6.QtWidgets import QSpinBox

        dialog = self._dialog(BatteryThresholds(50, 25, 10, 100))
        emitted = []
        dialog.sig_saved.connect(emitted.append)
        dialog._spins["critical"].setValue(45)   # above "low" (25): impossible
        dialog._on_save()
        self.assertEqual(len(emitted), 1)
        saved = emitted[0]
        self.assertLess(saved.critical, saved.low)
        self.assertEqual(saved, dialog.thresholds())
        self.assertTrue(any(isinstance(w, QSpinBox) for w in dialog.findChildren(QSpinBox)))

    def test_restore_defaults_does_not_save_on_its_own(self):
        dialog = self._dialog(BatteryThresholds(70, 40, 20, 99))
        emitted = []
        dialog.sig_saved.connect(emitted.append)
        dialog._restore_defaults()
        self.assertEqual(emitted, [])
        self.assertEqual(dialog.thresholds(), BatteryThresholds())

    def test_the_warning_is_visible_only_for_an_unordered_set(self):
        dialog = self._dialog(BatteryThresholds(50, 25, 10, 100))
        self.assertTrue(dialog._warning.isHidden())
        dialog._spins["critical"].setValue(45)
        self.assertFalse(dialog._warning.isHidden())


if __name__ == "__main__":
    unittest.main()
