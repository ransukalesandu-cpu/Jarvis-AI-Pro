"""Regression tests for premium HUD glass navigation motion."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
HUD_SOURCE = ROOT / "JarvisAI" / "ui" / "hud_main.py"


class TestHudGlassMotion(unittest.TestCase):
    def test_navigation_motion_uses_consistent_timing_constants(self):
        source = HUD_SOURCE.read_text(encoding="utf-8")
        self.assertIn("WORKSPACE_TRANSITION_MS = 300", source)
        self.assertIn("MENU_TRANSITION_MS = 190", source)
        self.assertIn("PANEL_FOCUS_DELAY_MS = 340", source)
        self.assertIn(
            "self._workspace_animation.setDuration(self.WORKSPACE_TRANSITION_MS)",
            source,
        )
        self.assertIn(
            "self._right_menu_animation.setDuration(self.MENU_TRANSITION_MS)",
            source,
        )

    def test_dashboard_shortcuts_wait_for_workspace_transition(self):
        source = HUD_SOURCE.read_text(encoding="utf-8")
        self.assertIn(
            "QTimer.singleShot(self.PANEL_FOCUS_DELAY_MS, "
            "lambda index=panel_index: self._focus_dashboard_panel(index))",
            source,
        )
        self.assertIn(
            "QTimer.singleShot(self.PANEL_FOCUS_DELAY_MS, self._dashboard.open_extra)",
            source,
        )

    def test_opengl_hologram_is_not_given_an_opacity_effect(self):
        source = HUD_SOURCE.read_text(encoding="utf-8")
        self.assertIn(
            "self._dashboard.setGraphicsEffect(self._dashboard_opacity_effect)",
            source,
        )
        self.assertNotIn(
            "self.wireframe_visualizer.setGraphicsEffect(self._dashboard_opacity_effect)",
            source,
        )


if __name__ == "__main__":
    unittest.main()
