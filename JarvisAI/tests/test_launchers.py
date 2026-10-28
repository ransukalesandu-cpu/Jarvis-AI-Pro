import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


class TestLaunchersAndImports(unittest.TestCase):
    def test_sys_path_contains_required_directories(self):
        root_dir = str(ROOT)
        jarvis_dir = str(ROOT / "JarvisAI")
        voice_dir = str(ROOT / "voice")

        # Importing main is the point of this test: it initialises sys.path.
        import main as root_main  # noqa: F401

        self.assertIn(root_dir, sys.path)
        self.assertIn(jarvis_dir, sys.path)
        self.assertIn(voice_dir, sys.path)

    def test_desktop_ui_uses_hologram_when_setup_is_complete(self):
        import main as root_main
        self.assertEqual(
            root_main._select_desktop_ui_mode(
                hud_available=True, api_configured=True, pin_enrolled=True
            ),
            "hologram",
        )

    def test_desktop_ui_keeps_hologram_when_gemini_key_is_missing(self):
        import main as root_main
        self.assertEqual(
            root_main._select_desktop_ui_mode(
                hud_available=True, api_configured=False, pin_enrolled=True
            ),
            "hologram",
        )

    def test_desktop_ui_keeps_hologram_when_owner_pin_is_missing(self):
        import main as root_main
        self.assertEqual(
            root_main._select_desktop_ui_mode(
                hud_available=True, api_configured=True, pin_enrolled=False
            ),
            "hologram",
        )

    def test_desktop_ui_keeps_hologram_when_both_setup_steps_are_missing(self):
        import main as root_main
        self.assertEqual(
            root_main._select_desktop_ui_mode(
                hud_available=True, api_configured=False, pin_enrolled=False
            ),
            "hologram",
        )

    def test_desktop_ui_fails_closed_instead_of_opening_legacy_ui_if_hud_is_unavailable(self):
        import main as root_main
        self.assertEqual(
            root_main._select_desktop_ui_mode(
                hud_available=False, api_configured=False, pin_enrolled=False
            ),
            "unavailable",
        )

    def test_import_voice_persona(self):
        import voice.persona as persona
        self.assertTrue(hasattr(persona, "JARVIS_SPOKEN_SYSTEM_PROMPT"))

    def test_windows_launcher_rebuilds_virtualenv_when_python_is_not_312(self):
        launcher = (ROOT / "JarvisAI" / "Run_Jarvis.bat").read_text(
            encoding="utf-8"
        )
        self.assertIn("sys.version_info[:2] == (3, 12)", launcher)
        self.assertIn('rmdir /s /q ".venv"', launcher)
        self.assertIn("Existing virtual environment is not Python 3.12", launcher)
        self.assertIn("Existing virtual environment is incomplete", launcher)

    def test_root_launchers_exist(self):
        self.assertTrue((ROOT / "run.py").exists())
        self.assertTrue((ROOT / "main.py").exists())
        self.assertTrue((ROOT / "setup.py").exists())
        self.assertTrue((ROOT / "requirements.txt").exists())


if __name__ == "__main__":
    unittest.main()
