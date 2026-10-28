"""Tests for the responsive HUD chrome rules (left rail + right dropdown).

The rail used to be a hard 44 px and the dropdown a hard 300 px. On a narrow
window that pair is a fifth of the screen; on a wide one the dropdown looks
underfed. These tests pin the pure rules that replace those constants; the widget
proof that the window *applies* them lives in ``test_hud_task_wiring.py``,
because it needs the wired HUD.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import unittest

from core import hud_layout


class TestRailWidth(unittest.TestCase):
    def test_a_wide_window_gets_the_shipped_rail(self):
        self.assertEqual(hud_layout.rail_width(1600), hud_layout.RAIL_WIDE)

    def test_a_medium_window_gets_the_compact_rail(self):
        self.assertEqual(hud_layout.rail_width(900), hud_layout.RAIL_COMPACT)

    def test_a_narrow_window_gets_the_small_rail(self):
        self.assertEqual(hud_layout.rail_width(600), hud_layout.RAIL_NARROW)

    def test_the_rail_never_grows_with_the_window(self):
        widths = [hud_layout.rail_width(w) for w in (400, 700, 900, 1200, 3840)]
        self.assertEqual(widths, sorted(widths))

    def test_buttons_fit_inside_the_rail(self):
        for window in (320, 640, 900, 1280, 3840):
            self.assertLess(hud_layout.rail_button_size(window), hud_layout.rail_width(window))

    def test_junk_input_is_tolerated(self):
        self.assertEqual(hud_layout.rail_width("wide"), hud_layout.RAIL_WIDE)
        self.assertEqual(hud_layout.rail_button_size(None),
                         hud_layout.rail_width(None) - 4)


class TestDropdownWidth(unittest.TestCase):
    def test_a_wide_window_keeps_the_preferred_width(self):
        self.assertEqual(hud_layout.dropdown_width(1920), hud_layout.DROPDOWN_WIDE)

    def test_a_narrow_window_shrinks_the_dropdown(self):
        self.assertLess(hud_layout.dropdown_width(720), hud_layout.DROPDOWN_WIDE)

    def test_it_never_shrinks_below_the_readable_minimum(self):
        for window in (120, 240, 360):
            self.assertGreaterEqual(hud_layout.dropdown_width(window), hud_layout.DROPDOWN_MIN)

    def test_it_never_exceeds_the_preferred_width(self):
        for window in (800, 1280, 2560, 5120):
            self.assertLessEqual(hud_layout.dropdown_width(window), hud_layout.DROPDOWN_WIDE)

    def test_position_keeps_the_dropdown_on_screen(self):
        for window in (200, 640, 1280):
            width = hud_layout.dropdown_width(window)
            x = hud_layout.dropdown_x(window, width)
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x + width, max(window, width + 8))


class TestDropdownHeight(unittest.TestCase):
    def test_a_tall_window_gets_the_full_dropdown(self):
        self.assertEqual(hud_layout.dropdown_height(1200), hud_layout.DROPDOWN_MAX_HEIGHT)

    def test_a_short_window_clips_it(self):
        self.assertLess(hud_layout.dropdown_height(500), hud_layout.DROPDOWN_MAX_HEIGHT)

    def test_it_keeps_a_usable_minimum(self):
        self.assertGreaterEqual(hud_layout.dropdown_height(120), hud_layout.DROPDOWN_MIN_HEIGHT)

    def test_the_dropdown_fits_below_the_top_bar(self):
        for window in (480, 700, 1200):
            height = hud_layout.dropdown_height(window)
            self.assertLessEqual(height, max(window - hud_layout.DROPDOWN_TOP,
                                              hud_layout.DROPDOWN_MIN_HEIGHT))
