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

    def test_desktop_ui_selects_original_interface_when_available(self):
        import main as root_main
        self.assertEqual(
            root_main._select_desktop_ui_mode(legacy_ui_available=True),
            "original",
        )

    def test_desktop_ui_fails_closed_when_original_interface_is_unavailable(self):
        import main as root_main
        self.assertEqual(
            root_main._select_desktop_ui_mode(legacy_ui_available=False),
            "unavailable",
        )

    def test_desktop_launcher_uses_original_jarvis_ui(self):
        source = (ROOT / "JarvisAI" / "main.py").read_text(encoding="utf-8")
        self.assertIn('ui = JarvisUI("face.png")', source)
        self.assertNotIn("HologramHUDUI", source)

    def test_content_workspace_opens_in_glass_side_panel_beside_hologram(self):
        source = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('self._stage_split = QSplitter(Qt.Orientation.Horizontal)', source)
        self.assertIn('self._stage_split.addWidget(self._hud_cam_stack)', source)
        self.assertIn('self._stage_split.addWidget(self._workspace_side)', source)
        self.assertIn('QFrame#WorkspaceGlassPanel', source)
        self.assertIn('self._center_split.addWidget(self._stage_split)', source)
        self.assertNotIn('self._hud_cam_stack.addWidget(self._workspace)', source)
        self.assertNotIn('self._hud_cam_stack.setCurrentWidget(self._workspace)', source)

    def test_smart_panel_has_html_css_assets_and_safe_local_navigation(self):
        html_asset = ROOT / "JarvisAI" / "ui" / "assets" / "smart_panel.html"
        css_asset = ROOT / "JarvisAI" / "ui" / "assets" / "smart_panel.css"
        module = (ROOT / "JarvisAI" / "ui" / "smart_panel.py").read_text(encoding="utf-8")
        html = html_asset.read_text(encoding="utf-8")
        css = css_asset.read_text(encoding="utf-8")
        self.assertIn("{{STYLE}}", html)
        self.assertIn("{{NAV_ITEMS}}", html)
        self.assertIn(".nav-item.active", css)
        self.assertIn("setOpenExternalLinks(False)", module)
        self.assertIn('url.scheme().casefold() != "jarvis"', module)
        for key in ("timers", "music", "news", "media", "system"):
            self.assertIn(f'("{key}",', module)

    def test_smart_panel_review_regressions(self):
        ui = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        workspace = (ROOT / "JarvisAI" / "core" / "hud_workspace.py").read_text(encoding="utf-8")
        panel = (ROOT / "JarvisAI" / "ui" / "smart_panel.py").read_text(encoding="utf-8")

        self.assertIn("self._workspace._web_view.urlChanged.connect(", ui)
        self.assertIn("def _sync_workspace_web_header(self, url: QUrl)", ui)
        select = workspace.split("    def _select(self, key: str, title: str | None = None):", 1)[1]
        self.assertLess(select.index("self._view_title.setText("), select.index("self.tabs.setCurrentIndex("))
        self.assertIn("'<style>{{STYLE}}</style>'", panel)
        self.assertIn("Qt.TextInteractionFlag.LinksAccessibleByKeyboard", panel)
        self.assertIn("Qt.TextInteractionFlag.LinksAccessibleByMouse", panel)

    def test_smart_panel_shortcuts_use_existing_workspace_views(self):
        source = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("def _on_workspace_shortcut(self, key: str)", source)
        self.assertIn('self._workspace.show_view("timers", "TIMERS / REMINDERS")', source)
        self.assertIn('self._workspace.show_webpage("https://music.youtube.com/", "YOUTUBE MUSIC")', source)
        self.assertIn('self._workspace.show_system_panel("overview")', source)

    def test_command_center_keeps_advanced_visual_controls_in_settings_drawer(self):
        source = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        header = source.split("    def _build_header(self)", 1)[1].split(
            "    def _tick_clock(self)", 1
        )[0]
        drawer = source.split("    def _build_quick_drawer(self)", 1)[1].split(
            "    def _", 1
        )[0]
        self.assertNotIn("lay.addWidget(self._neural_view_btn)", header)
        self.assertNotIn("lay.addWidget(self._neural_hand_btn)", header)
        self.assertIn("lay.addWidget(self._neural_view_btn)", drawer)
        self.assertIn("lay.addWidget(self._neural_hand_btn)", drawer)
        # The existing actions remain wired to their original handlers.
        self.assertIn('self._enter_immersive_view("neural")', header)
        self.assertIn("self._toggle_neural_hand_control", header)

    def test_command_center_starts_hologram_first_with_optional_telemetry(self):
        source = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        init = source.split("        self._left_panel = self._build_left_panel()", 1)[1].split(
            "        # Center column:", 1
        )[0]
        header = source.split("    def _build_header(self)", 1)[1].split(
            "    def _tick_clock(self)", 1
        )[0]
        self.assertIn("self._left_panel.hide()", init)
        self.assertIn('self._telemetry_btn = QPushButton("▤")', header)
        self.assertIn("self._telemetry_btn.clicked.connect(self._toggle_telemetry_panel)", header)
        self.assertIn("def _toggle_telemetry_panel(self, checked: bool)", source)
        self.assertIn("panel.setVisible(bool(checked))", source)

    def test_command_center_keeps_history_optional_and_command_bar_persistent(self):
        source = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        init = source.split("        self._right_panel = self._build_right_panel()", 1)[1].split(
            "        root.addLayout(body, stretch=1)", 1
        )[0]
        right = source.split("    def _build_right_panel(self)", 1)[1].split(
            "    def _build_quick_drawer(self)", 1
        )[0]
        footer = source.split("    def _build_footer(self)", 1)[1].split(
            "    def _on_file_selected", 1
        )[0]
        self.assertIn("self._right_panel.hide()", init)
        self.assertIn("self._activity_btn.clicked.connect(self._toggle_activity_panel)", source)
        self.assertIn("def _toggle_activity_panel(self, checked: bool)", source)
        self.assertNotIn("lay.addLayout(self._build_input_row())", right)
        self.assertIn("self._command_input_row = self._build_input_row()", right)
        self.assertIn("command.addLayout(self._command_input_row, 1)", footer)
        self.assertIn("command.addWidget(self._interrupt_btn)", footer)
        self.assertIn("command.addWidget(self._mute_btn)", footer)

    def test_escape_closes_open_drawers_before_interrupting(self):
        source = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('QShortcut(QKeySequence("Escape"), self)', source)
        self.assertIn("sc_intr.activated.connect(self._handle_escape)", source)
        handler = source.split("    def _handle_escape(self)", 1)[1].split(
            "    def _build_left_panel(self)", 1
        )[0]
        self.assertIn('("_quick_drawer", "_drawer_btn")', handler)
        self.assertIn('("_right_panel", "_activity_btn")', handler)
        self.assertIn('("_left_panel", "_telemetry_btn")', handler)
        self.assertIn("self._toggle_telemetry_panel(False)", handler)
        self.assertIn("self._do_interrupt()", handler)

    def test_hover_navigation_routes_to_glass_workspace_shortcuts(self):
        source = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("class _HoverMenuButton(QToolButton)", source)
        self.assertIn("self.showMenu()", source)
        self.assertIn("self._nav_menu_btn = _HoverMenuButton()", source)
        for key in ("timers", "music", "news", "media", "system"):
            self.assertIn(f'("{key}",', source)
        self.assertIn("self._on_workspace_shortcut(view)", source)
        self.assertIn("self._show_workspace_side(key)", source)

    def test_hidden_telemetry_does_not_poll_until_opened(self):
        source = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        init = source.split("        self._metric_tmr = QTimer(self)", 1)[1].split(
            "        self._close_sig.connect", 1
        )[0]
        toggle = source.split("    def _toggle_telemetry_panel(self, checked: bool)", 1)[1].split(
            "    def _toggle_activity_panel", 1
        )[0]
        self.assertIn("if self._left_panel.isVisible():", init)
        self.assertIn("timer.start(2000)", toggle)
        self.assertIn("if timer is not None:", toggle)
        self.assertIn("timer.stop()", toggle)

    def test_bento_dashboard_is_separate_and_refreshes_only_while_open(self):
        source = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        header = source.split("    def _build_header(self)", 1)[1].split(
            "    def _tick_clock(self)", 1
        )[0]
        dashboard = source.split("    def _open_bento_dashboard(self)", 1)[1].split(
            "    def _on_workspace_shortcut(self)", 1
        )[0]
        self.assertIn('self._nav_menu.addAction("▦   BENTO DASHBOARD")', header)
        self.assertIn("dialog = QDialog(self)", dashboard)
        self.assertIn("dialog.setModal(False)", dashboard)
        self.assertIn("self._bento_timer.setInterval(3000)", dashboard)
        self.assertIn("dialog.finished.connect(self._bento_timer.stop)", dashboard)
        self.assertIn("self._refresh_bento_dashboard()", dashboard)
        self.assertIn('("TIMER", "timers")', dashboard)
        self.assertIn('("MUSIC", "music")', dashboard)
        self.assertIn('("NEWS", "news")', dashboard)
        self.assertIn('("MEDIA", "media")', dashboard)
        self.assertIn("if timer is not None and not timer.isActive():", dashboard)
        self.assertIn("QGraphicsOpacityEffect(dialog)", dashboard)
        self.assertIn('QPropertyAnimation(fade, b"opacity", dialog)', dashboard)
        self.assertIn("self._bento_fade.setDuration(220)", dashboard)
        self.assertIn("self._bento_fade.start()", dashboard)

    def test_right_quick_controls_menu_exposes_panels_and_assistant_modes(self):
        source = (ROOT / "JarvisAI" / "ui" / "__init__.py").read_text(encoding="utf-8")
        header = source.split("    def _build_header(self)", 1)[1].split(
            "    def _tick_clock(self)", 1
        )[0]
        self.assertIn("self._right_menu_btn = QToolButton()", header)
        self.assertIn('"▦  Bento Dashboard"', header)
        self.assertIn('"▤  Toggle Telemetry"', header)
        self.assertIn('"☷  Toggle Activity"', header)
        self.assertIn('"⚙  Settings & Controls"', header)
        self.assertIn('"JARVIS Mode"', header)
        self.assertIn('"BIHANSA Mode"', header)
        self.assertIn("self._mode_btn.setCurrentIndex(1)", header)

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
