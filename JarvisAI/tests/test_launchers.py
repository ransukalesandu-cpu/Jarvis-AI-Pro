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

    def test_windows_launcher_delegates_to_the_python_installer(self):
        """The BAT files are thin wrappers around a testable module.

        This replaces the old assertion that the launcher hardcoded Python 3.12
        and deleted ``.venv`` with ``rmdir /s /q``: that behaviour was the bug
        (3.11 and 3.13 are supported too, and a broken venv may hold the user's
        optional packages). The logic now lives in ``tools/windows_setup.py``
        and is covered by ``tests/test_windows_setup.py``.
        """
        launcher = (ROOT / "JarvisAI" / "Run_Jarvis.bat").read_text(encoding="utf-8")
        self.assertIn("tools\\windows_setup.py", launcher)
        self.assertIn("launch", launcher)
        self.assertNotIn('rmdir /s /q ".venv"', launcher)
        self.assertNotIn("sys.version_info[:2] == (3, 12)", launcher)

    def test_windows_launcher_resolves_its_own_folder_and_keeps_the_window(self):
        launcher = (ROOT / "JarvisAI" / "Run_Jarvis.bat").read_text(encoding="utf-8")
        # Its own folder, not the caller's current directory (spaces included).
        self.assertIn('set "PROJECT_DIR=%~dp0"', launcher)
        self.assertIn('cd /d "%PROJECT_DIR%"', launcher)
        self.assertIn("pause", launcher)
        # The exit code of the real app must survive to the caller.
        self.assertIn("exit /b %JARVIS_EXIT%", launcher)

    def test_windows_installer_offers_the_four_menu_options(self):
        setup = (ROOT / "JarvisAI" / "Jarvis_Setup.bat").read_text(encoding="utf-8")
        self.assertIn("Install / Repair", setup)
        self.assertIn("Verify installation", setup)
        self.assertIn("Launch JARVIS", setup)
        self.assertIn("Exit", setup)
        for command in ("install", "verify", "status", "launch", "interpreters"):
            self.assertIn(command, setup)

    def test_windows_installer_never_deletes_a_virtualenv(self):
        for name in ("Jarvis_Setup.bat", "Run_Jarvis.bat"):
            text = (ROOT / "JarvisAI" / name).read_text(encoding="utf-8")
            for destructive in ('rmdir /s /q ".venv"', "rmdir /s /q .venv", 'del /f /q ".venv"'):
                self.assertNotIn(destructive, text, f"{name} must not delete .venv")
            self.assertIn('cd /d "%PROJECT_DIR%"', text)

    def test_windows_installer_quotes_paths_but_not_the_interpreter_command(self):
        """`py -3.12` is a command prefix: quoting it would break the lookup.

        Every path passed to it must still be quoted so a project folder with a
        space in its name works.
        """
        setup = (ROOT / "JarvisAI" / "Jarvis_Setup.bat").read_text(encoding="utf-8")
        self.assertNotIn('"%PYTHON_CMD%"', setup)
        self.assertIn('%PYTHON_CMD% "%SETUP_PY%"', setup)
        self.assertIn('set "PROJECT_DIR=%~dp0"', setup)
        # A project extracted to a drive root must still cd correctly.
        self.assertIn('if "%PROJECT_DIR:~-1%"==":" set "PROJECT_DIR=%PROJECT_DIR%\\"', setup)

    def test_windows_bat_files_do_not_embed_credentials(self):
        """No keys, PINs, tokens or Supabase credentials may live in a .bat file."""
        forbidden = ("AIza", "api_key=", "SUPABASE_SERVICE", "service_role",
                     "sk-proj-", "BEGIN PRIVATE KEY", "password=")
        for name in ("Jarvis_Setup.bat", "Run_Jarvis.bat"):
            text = (ROOT / "JarvisAI" / name).read_text(encoding="utf-8")
            for needle in forbidden:
                self.assertNotIn(needle, text, f"{name} appears to embed a secret ({needle})")

    def test_windows_installer_does_not_require_administrator_rights(self):
        for name in ("Jarvis_Setup.bat", "Run_Jarvis.bat"):
            text = (ROOT / "JarvisAI" / name).read_text(encoding="utf-8").lower()
            self.assertNotIn("runas", text)
            self.assertNotIn("net session", text)
            self.assertNotIn("takeown", text)

    def test_windows_installer_checks_exit_codes_before_continuing(self):
        """Install, verify and launch must all branch on the exit code."""
        setup = (ROOT / "JarvisAI" / "Jarvis_Setup.bat").read_text(encoding="utf-8")
        self.assertGreaterEqual(setup.count("if errorlevel 1"), 4)
        self.assertIn('set "JARVIS_EXIT=%ERRORLEVEL%"', setup)
        # A plain "install" with no error check would let a failed pip look fine.
        install_call = next(line for line in setup.splitlines()
                            if '"%SETUP_PY%" install' in line)
        following = setup.split(install_call, 1)[1].strip().splitlines()[0]
        self.assertIn("errorlevel", following)

    def test_root_launchers_exist(self):
        self.assertTrue((ROOT / "run.py").exists())
        self.assertTrue((ROOT / "main.py").exists())
        self.assertTrue((ROOT / "setup.py").exists())
        self.assertTrue((ROOT / "requirements.txt").exists())


if __name__ == "__main__":
    unittest.main()
