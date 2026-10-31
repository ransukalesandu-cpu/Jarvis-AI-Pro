"""Tests that the UI package stays cheap to import.

Qt WebEngine (Chromium) is the heaviest optional dependency in the project, and
its only consumers are the immersive neural-hand view, the Earth globe and the
document workspace. Importing the Hologram HUD used to pull all of them in, so
every launch paid for features most sessions never open.

These tests pin the boundary: importing ``ui`` / ``ui.hud_main`` must not import
or even *attempt* to import Qt WebEngine or the two WebEngine-backed panels. The
lazy path is then checked separately, so the deferral cannot silently break the
features it defers.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

if sys.platform != "win32" and not os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import unittest

#: Modules that must not be imported (or even attempted) by a HUD-only start.
_DEFERRED_PREFIXES = (
    "PyQt6.QtWebEngine", "core.earth_globe", "core.hud_workspace", "cv2",
)


def _import_probe(source: str) -> tuple[list[str], list[str]]:
    """Run ``source`` in a fresh interpreter and report deferred imports.

    A meta-path finder records every *attempt*, so the check holds on machines
    where Chromium is not installed at all (the import fails there either way,
    but it must not be attempted).
    """
    script = textwrap.dedent(
        """
        import sys
        ATTEMPTS = []

        class Recorder:
            def find_spec(self, name, path=None, target=None):
                if name.startswith(PREFIXES):
                    ATTEMPTS.append(name)
                return None

        PREFIXES = %r
        sys.meta_path.insert(0, Recorder())
        %s
        loaded = [m for m in sys.modules if m.startswith(PREFIXES)]
        print("ATTEMPTS=" + ",".join(sorted(set(ATTEMPTS))))
        print("LOADED=" + ",".join(sorted(set(loaded))))
        """
        % (_DEFERRED_PREFIXES, textwrap.dedent(source))
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=180,
        cwd=str(JARVIS_DIR), env=dict(os.environ),
    )
    if proc.returncode != 0:
        raise AssertionError(f"probe failed:\n{proc.stdout}\n{proc.stderr}")
    out = dict(
        line.split("=", 1) for line in proc.stdout.strip().splitlines() if "=" in line
    )
    attempts = [m for m in out.get("ATTEMPTS", "").split(",") if m]
    loaded = [m for m in out.get("LOADED", "").split(",") if m]
    return loaded, attempts


class TestUIPackageIsLazy(unittest.TestCase):
    def test_importing_ui_does_not_touch_webengine(self):
        loaded, attempts = _import_probe("import ui")
        self.assertEqual(loaded, [], "importing ui loaded a deferred module")
        self.assertEqual(attempts, [], "importing ui attempted to load a deferred module")

    def test_importing_the_hologram_hud_does_not_touch_webengine(self):
        loaded, attempts = _import_probe("import ui.hud_main")
        self.assertEqual(loaded, [])
        self.assertEqual(attempts, [])

    def test_screen_processing_does_not_drag_in_opencv(self):
        """The camera is optional; screen capture itself only needs mss."""
        loaded, attempts = _import_probe("import actions.screen_processor")
        self.assertEqual(loaded, [])
        self.assertEqual(attempts, [])

    def test_the_lazy_axes_are_still_reachable(self):
        """The deferral must not remove the feature, only delay it.

        Load WebEngine-backed classes in a clean child interpreter. Other UI tests
        can have OpenCV/Qt GUI DLLs mapped in-process, and importing Chromium there
        can trigger native Windows loader failures during process shutdown. The
        subprocess still asserts the real deferred imports succeed; it isolates
        their optional native libraries from the rest of the test runner.
        """
        source = textwrap.dedent(
            """
            import os
            import sys
            from ui import _earth_panel_class
            earth_panel = _earth_panel_class()
            assert earth_panel.__name__ == "EarthGlobePanel"
            print("EARTH_PANEL=" + earth_panel.__name__, flush=True)

            from ui import _workspace_class
            workspace = _workspace_class()
            assert workspace.__name__ == "HudWorkspace"
            print("WORKSPACE=" + workspace.__name__, flush=True)

            # Qt WebEngine may fault during DLL teardown on Windows runners.
            # Import success is already verified; exit without native cleanup.
            sys.stdout.flush()
            os._exit(0)
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", source],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(JARVIS_DIR),
            env=dict(os.environ),
        )
        self.assertEqual(
            proc.returncode, 0,
            f"lazy WebEngine-backed imports failed in an isolated process:\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
        )
        self.assertIn("EARTH_PANEL=EarthGlobePanel", proc.stdout)
        self.assertIn("WORKSPACE=HudWorkspace", proc.stdout)


class TestCameraLazyImport(unittest.TestCase):
    """The deferral must not silently disable the camera."""

    def test_the_camera_reports_a_missing_opencv_clearly(self):
        from actions import screen_processor as sp

        if sp._load_cv2():
            self.skipTest("OpenCV is installed here; the missing-camera path cannot run")
        with self.assertRaises(RuntimeError) as caught:
            sp._capture_camera()
        self.assertIn("OpenCV", str(caught.exception))

    def test_camera_backend_zero_means_unavailable(self):
        from actions import screen_processor as sp

        if sp._load_cv2():
            self.skipTest("OpenCV is installed here")
        self.assertEqual(sp._cv2_backend(), 0)
        self.assertFalse(sp._probe_camera(0, 0))


class TestWebEngineHelper(unittest.TestCase):
    def setUp(self):
        from core import qt_webengine

        self.helper = qt_webengine
        self.helper.reset_for_tests()

    def tearDown(self):
        self.helper.reset_for_tests()

    def test_ensure_is_truthful_about_availability(self):
        available = self.helper.ensure()
        self.assertIsInstance(available, bool)
        self.assertEqual(self.helper.available(), available)
        loaded = self.helper.classes()
        if available:
            self.assertEqual(
                set(loaded),
                {"QWebEnginePage", "QWebEngineProfile", "QWebEngineSettings",
                 "QWebEngineUrlRequestInterceptor", "QWebEngineView"},
            )
        else:
            self.assertEqual(loaded, {})

    def test_ensure_is_idempotent_and_cached(self):
        first = self.helper.ensure()
        self.assertEqual(self.helper.ensure(), first)
        self.assertEqual(self.helper.load(), self.helper.classes())

    def test_reset_for_tests_clears_the_cache(self):
        before = self.helper.ensure()
        self.helper.reset_for_tests()
        self.assertEqual(self.helper.ensure(), before)


class TestUIModuleStillWorks(unittest.TestCase):
    """The lazy boundary must not disturb the classes the app and tests use."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_legacy_entry_points_are_still_importable(self):
        from ui import JarvisUI, MainWindow, SetupOverlay  # noqa: F401

        self.assertTrue(callable(JarvisUI))
        self.assertTrue(callable(MainWindow))
        self.assertTrue(callable(SetupOverlay))

    def test_graphics_backend_helper_is_available_without_webengine(self):
        from ui import configure_qt_graphics_backend

        self.assertIsInstance(configure_qt_graphics_backend(), bool)


if __name__ == "__main__":
    unittest.main()
