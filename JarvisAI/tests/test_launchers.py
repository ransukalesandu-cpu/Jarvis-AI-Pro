import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

class TestLaunchersAndImports(unittest.TestCase):
    def test_sys_path_contains_required_directories(self):
        root_dir = str(ROOT)
        jarvis_dir = str(ROOT / "JarvisAI")
        voice_dir = str(ROOT / "voice")

        # Import main module to trigger sys.path initialization
        import main as root_main

        self.assertIn(root_dir, sys.path)
        self.assertIn(jarvis_dir, sys.path)
        self.assertIn(voice_dir, sys.path)

    def test_import_voice_persona(self):
        import voice.persona as persona
        self.assertTrue(hasattr(persona, "JARVIS_SPOKEN_SYSTEM_PROMPT"))

    def test_root_launchers_exist(self):
        self.assertTrue((ROOT / "run.py").exists())
        self.assertTrue((ROOT / "main.py").exists())
        self.assertTrue((ROOT / "setup.py").exists())
        self.assertTrue((ROOT / "requirements.txt").exists())


if __name__ == "__main__":
    unittest.main()
