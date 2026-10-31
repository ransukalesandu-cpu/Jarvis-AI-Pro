"""
Automated UI Hologram Smoke Tests for Jarvis AI Pro Neural Wireframe HUD.
Verifies widget creation, state transitions, audio energy calculations, and signal handling.
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
import tempfile
from unittest.mock import Mock, patch
import numpy as np

from PyQt6.QtCore import QSettings, QCoreApplication, QEvent, QTimer, Qt, QPoint
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton
from PyQt6.QtTest import QTest

# Ensure QApplication exists before testing Qt widgets
app = QApplication.instance() or QApplication(sys.argv)

from audio.visualizer_bridge import VisualizerBridge
from ui.hologram.wireframe_head import NeuralWireframeHead
from ui.hologram.bihansa_hologram import BihansaHologramWidget
from ui.hologram.neural_heart_reactor import NeuralHeartReactor
from ui.panels.hybrid_brain_panel import HybridBrainPanel
from ui.panels.security_panel import SecurityPanel
from ui.panels.memory_panel import MemoryPanel
from ui.panels.scheduler_panel import SchedulerPanel
from ui.panels.system_telemetry_ring import SystemTelemetryRing
from ui.hud_main import HUDMainWindow, HologramHUDUI
from ui import SetupOverlay
from ui.panels.modern_dashboard import FloatingHolographicOrb, SkeletonLoader, ModernDashboard
from ui.panels.hud_surface import BentoPanelSurface


class TestUIHologram(unittest.TestCase):

    def setUp(self):
        self.bridge = VisualizerBridge()
        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        config_patch = patch("memory.config_manager.CONFIG_FILE", Path(settings_dir.name) / "api_keys.json")
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.settings = QSettings(
            str(Path(settings_dir.name) / "settings.ini"), QSettings.Format.IniFormat
        )
        settings_patch = patch("ui.hud_main.QSettings", return_value=self.settings)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

    def _track_widget(self, widget):
        def dispose():
            widget.close()
            widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.addCleanup(dispose)
        return widget

    def test_visualizer_bridge_rms_and_signals(self):
        """Test RMS energy computation, lerp, and Qt signal emissions."""
        received_energy = []
        self.bridge.sig_audio_energy.connect(lambda e: received_energy.append(e))

        # Test empty audio
        self.assertEqual(self.bridge.calculate_rms(b""), 0.0)

        # Test 16-bit PCM buffer
        pcm_data = (np.sin(np.linspace(0, 100, 1600)) * 16000).astype(np.int16).tobytes()
        rms = self.bridge.calculate_rms(pcm_data)
        self.assertGreater(rms, 0.0)

        # Test audio buffer tap
        energy = self.bridge.tap_audio_buffer(pcm_data)
        self.assertGreater(energy, 0.0)
        self.assertTrue(len(received_energy) > 0)

        # Test state updates
        received_states = []
        self.bridge.sig_state_changed.connect(lambda s: received_states.append(s))
        self.bridge.update_state("THINKING")
        self.assertEqual(self.bridge.current_state, "THINKING")
        self.assertIn("THINKING", received_states)

    def test_hud_status_keeps_errors_and_disconnections_truthful(self):
        """Provider failures must not be displayed as a healthy standby state."""
        hud = self._track_widget(HUDMainWindow(bridge=self.bridge))
        for state in ("ERROR", "FAILED", "AUDIO_ERROR", "SESSION_ERROR"):
            with self.subTest(state=state):
                hud._on_state_changed(state)
                self.assertIn("ERROR", hud._lbl_hud_status.text())
                self.assertNotIn("STANDBY", hud._lbl_hud_status.text())
        for state in ("DISCONNECTED", "OFFLINE", "CONNECTION_LOST"):
            with self.subTest(state=state):
                hud._on_state_changed(state)
                self.assertIn("DISCONNECTED", hud._lbl_hud_status.text())
                self.assertNotIn("STANDBY", hud._lbl_hud_status.text())
        hud._on_state_changed("CUSTOM_PROVIDER_STATE")
        self.assertEqual(hud._lbl_hud_status.text(), "● CUSTOM PROVIDER STATE")
        hud._on_state_changed("IDLE")
        self.assertIn("STANDBY", hud._lbl_hud_status.text())

    def test_persona_switch_does_not_hide_active_warning(self):
        """Switching Bihansa mode preserves the current error/offline message."""
        hud = self._track_widget(HUDMainWindow(bridge=self.bridge))
        for state in ("ERROR", "DISCONNECTED"):
            with self.subTest(state=state):
                self.bridge.update_state(state)
                before = hud._lbl_hud_status.text()
                self.assertIn(state, before)
                hud._set_bihansa_enabled(True)
                self.assertEqual(hud._lbl_hud_status.text(), before)
                hud._set_bihansa_enabled(False)
                self.assertEqual(hud._lbl_hud_status.text(), before)

    def test_neural_wireframe_head_widget(self):
        """Test 3D Wireframe Visualizer creation, state switching, and audio energy updates."""
        head = NeuralWireframeHead()
        self.assertIsNotNone(head)
        self.assertEqual(head.get_state(), "IDLE")

        # Test state switching across all required states
        states = ["IDLE", "LISTENING", "THINKING", "SPEAKING", "PRIVACY_LOCK"]
        for st in states:
            head.set_state(st)
            self.assertEqual(head.get_state(), st)

        # Test audio energy update
        head.set_audio_energy(0.75)
        self.assertEqual(head._target_energy, 0.75)

    def test_neural_face_landmarks_are_aligned_and_sculpted(self):
        """The high-resolution mesh has readable facial landmarks, not a sphere."""
        head = self._track_widget(NeuralWireframeHead())
        self.assertGreaterEqual(len(head._feature_edges), 25)
        self.assertEqual(len(head._eyes), 2)
        left_eye = head._vertices[head._eyes[0]]
        right_eye = head._vertices[head._eyes[1]]
        self.assertLess(left_eye[0], 0.0)
        self.assertGreater(right_eye[0], 0.0)
        self.assertAlmostEqual(left_eye[0], -right_eye[0], delta=1e-6)
        self.assertAlmostEqual(left_eye[1], right_eye[1], delta=1e-6)
        self.assertAlmostEqual(left_eye[2], right_eye[2], delta=1e-6)

        eye_socket = NeuralWireframeHead._head_surface(0.40, 0.18)[2]
        brow = NeuralWireframeHead._head_surface(0.40, 0.33)[2]
        upper_lip = NeuralWireframeHead._head_surface(0.0, -0.30)[2]
        mouth_crease = NeuralWireframeHead._head_surface(0.0, -0.37)[2]
        baseline_upper_lip = NeuralWireframeHead._head_surface(
            0.0, -0.30, sculpt=False
        )[2]
        baseline_mouth_crease = NeuralWireframeHead._head_surface(
            0.0, -0.37, sculpt=False
        )[2]
        self.assertLess(eye_socket, brow)
        self.assertLess(mouth_crease, upper_lip)
        self.assertLess(mouth_crease, baseline_mouth_crease)
        self.assertGreater(
            upper_lip - mouth_crease,
            baseline_upper_lip - baseline_mouth_crease,
        )
        crown = NeuralWireframeHead._head_surface(0.0, 1.0)
        chin = NeuralWireframeHead._head_surface(0.0, -1.0)
        self.assertGreater(crown[1] - chin[1], 2.0)

    def test_bihansa_hologram_widget(self):
        """Test Bihansa 3D Neural Face visualizer creation, states, energy, visemes, and effects."""
        bihansa = BihansaHologramWidget()
        self.assertIsNotNone(bihansa)
        self.assertEqual(bihansa.get_state(), "IDLE")

        # Test state transitions
        for st in ["IDLE", "LISTENING", "THINKING", "SPEAKING", "PRIVACY_LOCK"]:
            bihansa.set_state(st)
            self.assertEqual(bihansa.get_state(), st)

        # Test audio energy update
        bihansa.set_audio_energy(0.85)
        self.assertEqual(bihansa._target_energy, 0.85)

        # Test viseme blend weights extension API
        bihansa.set_viseme("aa", 0.9)
        self.assertEqual(bihansa._viseme_weights["aa"], 0.9)

        # Test toggling effects & voice reactivity
        bihansa.set_effects_enabled(False)
        self.assertFalse(bihansa._effects_enabled)
        bihansa.set_voice_reactive(False)
        self.assertFalse(bihansa._voice_reactive)
        self.assertEqual(bihansa._target_energy, 0.0)

    def test_telemetry_panels_creation_and_updates(self):
        """Test modular telemetry panels."""
        # 1. Hybrid Brain Panel
        brain = HybridBrainPanel()
        self.assertIsNotNone(brain)
        brain.update_telemetry("Cloud AI", 45.2, "Sinhala", "Gemini-2.5")
        self.assertEqual(brain._language_mode, "Sinhala")

        # 2. Security Panel
        security = SecurityPanel()
        self.assertIsNotNone(security)
        security.update_auth_state("PRIVACY_LOCK", 3, "PIN")
        self.assertEqual(security._auth_state, "PRIVACY_LOCK")

        # 3. Memory Panel
        memory = MemoryPanel()
        self.assertIsNotNone(memory)
        memory.update_memory_stats(42, "user_name", "ONLINE")
        self.assertEqual(memory._indexed_count, 42)

        # 4. Scheduler Panel
        scheduler = SchedulerPanel()
        self.assertIsNotNone(scheduler)
        scheduler.update_scheduler_stats("Meeting at 3PM", True, "22:00 - 07:00")
        self.assertEqual(scheduler._dnd_status, "ON")

        # 5. System Telemetry Ring
        ring = SystemTelemetryRing()
        self.assertIsNotNone(ring)
        ring.update_metrics()

    def test_hud_main_window_shell(self):
        """Test HUD Main Window creation and Privacy Lock state handling."""
        hud = self._track_widget(HUDMainWindow(bridge=self.bridge))
        hud.show()
        self.assertIsNotNone(hud)

        # Simulate state changes via bridge
        self.bridge.update_state("LISTENING")
        self.assertEqual(hud.wireframe_visualizer.get_state(), "LISTENING")
        self.assertEqual(hud.bihansa_visualizer.get_state(), "LISTENING")

        # Default mode is JARVIS (Bihansa toggle OFF)
        self.assertFalse(hud._bihansa_toggle.isChecked())
        self.assertEqual(hud._visualizer_stack.currentWidget(), hud.wireframe_visualizer)

        # Switch to Bihansa Mode
        hud._bihansa_toggle.setChecked(True)
        self.assertTrue(hud._bihansa_toggle.isChecked())
        self.assertEqual(hud._visualizer_stack.currentWidget(), hud.bihansa_visualizer)

        # Simulate PRIVACY_LOCK auth state change
        self.bridge.update_auth_state("PRIVACY_LOCK")
        self.assertFalse(hud._lock_banner.isHidden())
        self.assertEqual(hud.wireframe_visualizer.get_state(), "PRIVACY_LOCK")
        self.assertEqual(hud.bihansa_visualizer.get_state(), "PRIVACY_LOCK")
        self.assertEqual(hud._mini_orb._state, "PRIVACY_LOCK")
        self.assertEqual(hud._heart_reactor._state, "PRIVACY_LOCK")

        # Audio state updates must not override an auth-only lock.
        self.bridge.update_state("SPEAKING")
        self.assertEqual(hud.bihansa_visualizer.get_state(), "PRIVACY_LOCK")
        self.assertEqual(hud.wireframe_visualizer.get_state(), "PRIVACY_LOCK")
        self.assertEqual(hud._mini_orb._state, "PRIVACY_LOCK")
        self.assertEqual(hud._heart_reactor._state, "PRIVACY_LOCK")

        # Clear PRIVACY_LOCK
        self.bridge.update_auth_state("FULL_ACCESS")
        self.assertTrue(hud._lock_banner.isHidden())
        self.assertEqual(hud.bihansa_visualizer.get_state(), "SPEAKING")
        self.assertEqual(hud.wireframe_visualizer.get_state(), "SPEAKING")

    def test_left_mega_menu_is_accessible_and_pointer_safe(self):
        """The edge trigger opens the rail; pointer and focus guards prevent flicker."""
        hud = self._track_widget(HUDMainWindow(bridge=self.bridge))
        self.assertTrue(hud._left_rail.isHidden())
        self.assertFalse(hud._left_menu_trigger.isHidden())
        self.assertEqual(
            hud._left_menu_trigger.focusPolicy(), Qt.FocusPolicy.StrongFocus
        )

        hud.eventFilter(hud._left_menu_trigger, QEvent(QEvent.Type.Enter))
        self.assertFalse(hud._left_rail.isHidden())
        hud.eventFilter(hud._left_menu_trigger, QEvent(QEvent.Type.Leave))
        self.assertTrue(hud._left_rail_hide_timer.isActive())
        hud.eventFilter(hud._left_rail, QEvent(QEvent.Type.Enter))
        self.assertFalse(hud._left_rail_hide_timer.isActive())

        with (
            patch("ui.hud_main.QApplication.focusWidget", return_value=None),
            patch("ui.hud_main.QApplication.platformName", return_value="windows"),
            patch(
                "ui.hud_main.QApplication.widgetAt",
                side_effect=[hud._left_rail, hud._home_page],
            ),
            patch("ui.hud_main.QCursor") as cursor,
        ):
            cursor.pos.return_value = QPoint(100, 100)
            hud._hide_left_rail_if_pointer_outside()
            self.assertFalse(hud._left_rail.isHidden())
            hud._hide_left_rail_if_pointer_outside()
        self.assertTrue(hud._left_rail.isHidden())

        hud._left_menu_trigger.click()
        self.assertFalse(hud._left_rail.isHidden())

    def test_first_run_setup_asks_only_for_gemini_api_key(self):
        """The first-run credentials card must expose one Gemini key field only."""
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "api_keys.json"
            config_path.write_text(
                '{"groq_api_key":"keep-groq","openai_api_key":"keep-openai"}',
                encoding="utf-8",
            )
            with patch("ui.API_FILE", config_path):
                overlay = self._track_widget(SetupOverlay())

        self.assertEqual(list(overlay._key_fields), ["gemini_api_key"])
        self.assertIs(overlay._key_fields["gemini_api_key"], overlay._key_field)
        self.assertEqual(overlay._key_field.echoMode(), QLineEdit.EchoMode.Password)

        payloads = []
        overlay.done.connect(payloads.append)
        overlay._key_field.setText("  test-gemini-key  ")
        overlay._submit()
        self.assertEqual(payloads, [{"gemini_api_key": "test-gemini-key"}])
        self.assertNotIn("groq_api_key", payloads[0])
        self.assertNotIn("openai_api_key", payloads[0])
        self.assertNotIn("anthropic_api_key", payloads[0])

        overlay._show_key_button.setChecked(True)
        self.assertEqual(overlay._key_field.echoMode(), QLineEdit.EchoMode.Normal)
        self.assertEqual(overlay._show_key_button.text(), "HIDE")
        overlay._show_key_button.setChecked(False)
        self.assertEqual(overlay._key_field.echoMode(), QLineEdit.EchoMode.Password)

    def test_first_run_setup_can_keep_existing_gemini_key(self):
        """A reconfiguration with a stored key may leave the field blank."""
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "api_keys.json"
            config_path.write_text(
                '{"gemini_api_key":"existing-gemini-key","groq_api_key":"preserve-me"}',
                encoding="utf-8",
            )
            with patch("ui.API_FILE", config_path):
                overlay = self._track_widget(SetupOverlay())

        payloads = []
        overlay.done.connect(payloads.append)
        overlay._submit()
        self.assertEqual(payloads, [{"gemini_api_key": "existing-gemini-key"}])

    def test_first_run_setup_rejects_empty_key_when_not_configured(self):
        """A fresh setup cannot continue without the one required Gemini key."""
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "api_keys.json"
            config_path.write_text("{}", encoding="utf-8")
            with patch("ui.API_FILE", config_path):
                overlay = self._track_widget(SetupOverlay())

        payloads = []
        overlay.done.connect(payloads.append)
        overlay._submit()
        self.assertEqual(payloads, [])
        self.assertFalse(overlay._error_label.isHidden())

    def test_recovery_setup_requires_replacement_even_when_old_key_exists(self):
        """An invalid stored key must not be accepted by the keep-existing shortcut."""
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "api_keys.json"
            config_path.write_text(
                '{"gemini_api_key":"known-invalid-old-key"}',
                encoding="utf-8",
            )
            with patch("ui.API_FILE", config_path):
                overlay = self._track_widget(
                    SetupOverlay(allow_keep_existing=False)
                )

        payloads = []
        overlay.done.connect(payloads.append)
        overlay._submit()
        self.assertEqual(payloads, [])
        self.assertFalse(overlay._error_label.isHidden())

        replacement = "AIzaSyNewReplacementKeyLongEnough"
        overlay._key_field.setText(replacement)
        overlay._submit()
        self.assertEqual(payloads, [{"gemini_api_key": replacement}])

    def test_hologram_visualizers_use_transparent_backgrounds(self):
        """Both original hologram renderers must preserve transparent pixels."""
        for widget_type in (NeuralWireframeHead, BihansaHologramWidget):
            widget = self._track_widget(widget_type())
            self.assertTrue(
                widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            )
            self.assertFalse(
                widget.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
            )

    def test_bento_side_panels_keep_original_hologram_unchanged(self):
        """Modern side surfaces must not replace or reconfigure the original hologram."""
        hud = self._track_widget(HUDMainWindow(bridge=self.bridge))
        self.assertIsInstance(hud.wireframe_visualizer, NeuralWireframeHead)
        self.assertIsInstance(hud.bihansa_visualizer, BihansaHologramWidget)
        self.assertEqual(hud._visualizer_stack.currentWidget(), hud.wireframe_visualizer)

        # The status orb remains below the hologram; the heart is a separate
        # transparent overlay and does not replace either original visualizer.
        self.assertIsInstance(hud._mini_orb, FloatingHolographicOrb)
        self.assertEqual(hud._mini_orb.size().width(), 48)
        self.assertEqual(hud._mini_orb.size().height(), 48)
        self.assertIsInstance(hud._heart_reactor, NeuralHeartReactor)
        self.assertIs(hud._heart_reactor.parentWidget(), hud._hologram_stage)
        self.assertIsInstance(hud._surface_brain, BentoPanelSurface)
        self.assertIsInstance(hud._surface_security, BentoPanelSurface)
        self.assertIsInstance(hud._surface_memory, BentoPanelSurface)
        self.assertIsInstance(hud._surface_scheduler, BentoPanelSurface)
        self.assertIsInstance(hud._surface_ring, BentoPanelSurface)

        surfaces = (
            ("brain", hud._panel_brain),
            ("security", hud._panel_security),
            ("memory", hud._panel_memory),
            ("scheduler", hud._panel_scheduler),
            ("ring", hud._panel_ring),
        )
        for name, panel in surfaces:
            surface = getattr(hud, f"_surface_{name}")
            self.assertIs(surface.panel, panel)
            surface.show_panel()
            self.assertIs(surface._stack.currentWidget(), panel)

        # State/audio flow reaches the added orb and the original visualizers.
        self.bridge.update_state("LISTENING")
        self.bridge.push_audio_energy(0.75)
        self.assertEqual(hud._mini_orb._state, "LISTENING")
        self.assertEqual(hud._heart_reactor._state, "LISTENING")
        self.assertEqual(hud.wireframe_visualizer.get_state(), "LISTENING")
        self.assertEqual(hud.bihansa_visualizer.get_state(), "LISTENING")

        # Existing mode switching remains intact.
        hud._bihansa_toggle.setChecked(True)
        self.assertEqual(hud._visualizer_stack.currentWidget(), hud.bihansa_visualizer)
        self.assertTrue(hud._mini_orb._bihansa)
        hud._bihansa_toggle.setChecked(False)
        self.assertEqual(hud._visualizer_stack.currentWidget(), hud.wireframe_visualizer)

    def test_hologram_home_is_clean_and_dashboard_is_a_separate_page(self):
        """The main page stays hologram-first; bento telemetry is opened separately."""
        hud = self._track_widget(HUDMainWindow(bridge=self.bridge))
        hud.show()
        app.processEvents()

        self.assertIs(hud._workspace_stack.currentWidget(), hud._home_page)
        self.assertTrue(hud._left_rail.isHidden())
        self.assertIsInstance(hud._home_page.findChild(NeuralWireframeHead), NeuralWireframeHead)
        self.assertIsInstance(hud._dashboard, ModernDashboard)
        self.assertEqual(len(hud._dashboard._cards), 5)
        self.assertIsInstance(hud._dashboard._skeleton, SkeletonLoader)

        hud._toggle_dashboard_page()
        app.processEvents()
        self.assertIs(hud._workspace_stack.currentWidget(), hud._dashboard)
        self.assertFalse(hud._left_rail.isHidden())
        self.assertEqual(hud._dashboard_button.text(), "⌂")

        # Dashboard fades are completed only on the dashboard widget; the
        # OpenGL hologram page remains outside the graphics-opacity effect.
        self.assertIs(hud._dashboard.graphicsEffect(), hud._dashboard_opacity_effect)
        hud._show_hologram_page()
        hud._workspace_animation.stop()
        hud._finish_workspace_transition()
        app.processEvents()
        self.assertIs(hud._workspace_stack.currentWidget(), hud._home_page)
        self.assertTrue(hud._left_rail.isHidden())
        self.assertEqual(hud._dashboard_button.text(), "▦")

    def test_dashboard_skeletons_start_when_dashboard_opens(self):
        """Hidden home time must not consume the dashboard loading animation."""
        hud = self._track_widget(HUDMainWindow(bridge=self.bridge))
        hud.show()
        app.processEvents()

        self.assertFalse(hud._dashboard._loaded)
        self.assertFalse(hud._dashboard._loading_timer.isActive())
        surfaces = (
            hud._surface_brain, hud._surface_security, hud._surface_memory,
            hud._surface_scheduler, hud._surface_ring,
        )
        for surface in surfaces:
            self.assertIs(surface._stack.currentWidget(), surface._skeleton)
            self.assertFalse(surface._reveal_timer.isActive())

        hud._show_dashboard_page()
        QTest.qWait(1050)
        app.processEvents()
        self.assertTrue(hud._dashboard._loaded)
        for surface in surfaces:
            self.assertIs(surface._stack.currentWidget(), surface.panel)

    def test_left_icon_click_opens_and_prioritizes_selected_panel(self):
        """Panel shortcuts open the separate dashboard and focus the selected live card."""
        hud = self._track_widget(HUDMainWindow(bridge=self.bridge))
        hud.show()
        app.processEvents()

        hud._open_dashboard_panel(0)
        self.assertIs(hud._workspace_stack.currentWidget(), hud._dashboard)
        self.assertFalse(hud._left_rail.isHidden())
        self.assertIs(hud._dashboard._cards[0].findChild(BentoPanelSurface), hud._surface_brain)

        hud._open_dashboard_panel(1)
        self.assertIs(hud._workspace_stack.currentWidget(), hud._dashboard)
        self.assertIs(hud._dashboard._cards[1].findChild(BentoPanelSurface), hud._surface_security)

    def test_right_dropdown_repositions_after_resize(self):
        """The floating settings menu must remain anchored inside the window."""
        hud = self._track_widget(HUDMainWindow(bridge=self.bridge))
        hud.resize(1100, 760)
        hud.show()
        app.processEvents()
        hud._toggle_right_dropdown()
        self.assertTrue(hud._right_menu.isVisible())

        hud.resize(1024, 700)
        app.processEvents()
        expected_x = max(
            8, hud.centralWidget().width() - hud._right_menu.width() - 12
        )
        self.assertEqual(hud._right_menu.x(), expected_x)
        self.assertLessEqual(
            hud._right_menu.x() + hud._right_menu.width(),
            hud.centralWidget().width(),
        )

    def test_hologram_stays_visible_with_setup_overlay_when_gemini_key_is_missing(self):
        """A fresh install displays the Gemini form over the HUD, not a legacy window."""
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "api_keys.json"
            config_path.write_text("{}", encoding="utf-8")
            auth = Mock()
            auth.is_pin_enrolled.return_value = False
            with (
                patch("memory.config_manager.CONFIG_FILE", config_path),
                patch("ui.API_FILE", config_path),
                patch("ui.hud_main.get_auth_manager", return_value=auth),
            ):
                hud_ui = HologramHUDUI(bridge=self.bridge)
                self._track_widget(hud_ui._win)
                app.processEvents()

                self.assertTrue(hud_ui._win.isVisible())
                self.assertIsInstance(hud_ui._setup_controller._overlay, SetupOverlay)
                self.assertIs(
                    hud_ui._setup_controller._overlay.parentWidget(),
                    hud_ui._win.centralWidget(),
                )
                self.assertFalse(hud_ui._win._ready)
                self.assertFalse(hud_ui._ready)

    def test_hologram_first_run_saves_key_and_enables_live_core_when_pin_exists(self):
        """The key submitted over the HUD is written to the shared config before core starts."""
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory) / "config"
            config_path = config_dir / "api_keys.json"
            auth = Mock()
            auth.is_pin_enrolled.return_value = True
            with (
                patch("memory.config_manager.CONFIG_DIR", config_dir),
                patch("memory.config_manager.CONFIG_FILE", config_path),
                patch("ui.API_FILE", config_path),
                patch.dict(os.environ, {"GEMINI_API_KEY": ""}),
                patch("ui.hud_main.get_auth_manager", return_value=auth),
            ):
                hud_ui = HologramHUDUI(bridge=self.bridge)
                self._track_widget(hud_ui._win)
                app.processEvents()

                overlay = hud_ui._setup_controller._overlay
                self.assertIsInstance(overlay, SetupOverlay)
                self.assertFalse(hud_ui._win._ready)

                key = "AIzaSyLongEnoughTestGeminiApiKey123"
                overlay._key_field.setText(key)
                overlay._submit()
                app.processEvents()

                self.assertTrue(config_path.exists())
                import json
                self.assertEqual(
                    json.loads(config_path.read_text(encoding="utf-8"))["gemini_api_key"],
                    key,
                )
                self.assertTrue(hud_ui._setup_controller._api_configured())
                # Allow the zero-delay Qt callback to finish the setup transition.
                QTest.qWait(50)
                self.assertTrue(hud_ui._win._ready)
                self.assertTrue(hud_ui._ready)
                self.assertIsNone(hud_ui._setup_controller._overlay)

    def test_hologram_first_run_requires_and_saves_owner_pin_before_starting(self):
        """Gemini setup must flow into owner PIN enrollment on the same HUD."""
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory) / "config"
            config_path = config_dir / "api_keys.json"
            auth = Mock()
            auth.is_pin_enrolled.return_value = False

            def save_master_pin(pin):
                auth.is_pin_enrolled.return_value = True

            auth.set_master_pin.side_effect = save_master_pin
            with (
                patch("memory.config_manager.CONFIG_DIR", config_dir),
                patch("memory.config_manager.CONFIG_FILE", config_path),
                patch("ui.API_FILE", config_path),
                patch.dict(os.environ, {"GEMINI_API_KEY": ""}),
                patch("ui.hud_main.get_auth_manager", return_value=auth),
            ):
                hud_ui = HologramHUDUI(bridge=self.bridge)
                self._track_widget(hud_ui._win)
                app.processEvents()
                self.assertFalse(hud_ui._win._ready)

                overlay = hud_ui._setup_controller._overlay
                self.assertIsInstance(overlay, SetupOverlay)
                overlay._key_field.setText("AIzaSyLongEnoughTestGeminiApiKey123")

                attempts = [0]
                pin_dialog_seen = []
                readiness_before_pin_saved = []
                unexpected_dialog = []

                def fill_owner_pin_dialog():
                    attempts[0] += 1
                    dialog = app.activeModalWidget()
                    if dialog is None:
                        if attempts[0] < 30:
                            QTimer.singleShot(10, fill_owner_pin_dialog)
                        return
                    if not isinstance(dialog, QDialog):
                        unexpected_dialog.append(type(dialog).__name__)
                        dialog.reject()
                        return

                    # The assistant must remain blocked while PIN enrollment is pending.
                    pin_dialog_seen.append(True)
                    readiness_before_pin_saved.append(hud_ui._win._ready)
                    fields = dialog.findChildren(QLineEdit)
                    save_button = next(
                        (
                            button for button in dialog.findChildren(QPushButton)
                            if button.text() == "SAVE PIN & CONTINUE"
                        ),
                        None,
                    )
                    if len(fields) < 2 or save_button is None:
                        unexpected_dialog.append("PIN dialog missing expected fields/save button")
                        dialog.reject()
                        return
                    fields[0].setText("test-owner-pin")
                    fields[1].setText("test-owner-pin")
                    save_button.click()

                # The key callback schedules the modal PIN dialog on the Qt loop.
                QTimer.singleShot(0, fill_owner_pin_dialog)
                overlay._submit()
                QTest.qWait(400)

                self.assertEqual(unexpected_dialog, [])
                self.assertEqual(pin_dialog_seen, [True], "Owner PIN dialog did not appear")
                self.assertEqual(
                    readiness_before_pin_saved,
                    [False],
                    "JARVIS became ready before owner PIN enrollment completed",
                )
                auth.set_master_pin.assert_called_once_with("test-owner-pin")
                self.assertTrue(hud_ui._win.isVisible())
                self.assertTrue(hud_ui._win._ready)
                self.assertTrue(hud_ui._ready)
                self.assertIsNone(hud_ui._setup_controller._overlay)
                self.assertGreater(attempts[0], 0)

    def test_hologram_api_reconfiguration_keeps_the_same_hud_window(self):
        """An invalid key opens the Gemini form on top of the current HUD."""
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "api_keys.json"
            config_path.write_text('{"gemini_api_key":"existing-gemini-key"}', encoding="utf-8")
            auth = Mock()
            auth.is_pin_enrolled.return_value = True
            with (
                patch("memory.config_manager.CONFIG_FILE", config_path),
                patch("ui.API_FILE", config_path),
                patch("ui.hud_main.get_auth_manager", return_value=auth),
            ):
                hud_ui = HologramHUDUI(bridge=self.bridge)
                self._track_widget(hud_ui._win)
                app.processEvents()
                self.assertTrue(hud_ui._win._ready)

                original_window = hud_ui._win
                hud_ui.prompt_reconfig()
                app.processEvents()

                self.assertIs(hud_ui._win, original_window)
                self.assertTrue(hud_ui._win.isVisible())
                overlay = hud_ui._setup_controller._overlay
                self.assertIsInstance(overlay, SetupOverlay)
                self.assertFalse(overlay._allow_keep_existing)
                self.assertFalse(hud_ui._win._ready)

                # Blank submit cannot silently recycle the rejected stored key.
                payloads = []
                overlay.done.connect(payloads.append)
                overlay._submit()
                self.assertEqual(payloads, [])
                self.assertFalse(overlay._error_label.isHidden())

                # A clearly malformed/short key is rejected before it is saved.
                with patch("memory.config_manager.save_api_keys") as save_keys:
                    hud_ui._setup_controller._save_gemini_key(
                        {"gemini_api_key": "short"}
                    )
                    save_keys.assert_not_called()
                self.assertTrue(overlay._error_label.isVisible())
                self.assertFalse(hud_ui._win._ready)

    def test_hologram_hud_ui_adapter(self):
        """The configured adapter starts the live core without opening setup."""
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "api_keys.json"
            config_path.write_text(
                '{"gemini_api_key":"AIzaSyLongEnoughTestGeminiApiKey123"}',
                encoding="utf-8",
            )
            auth = Mock()
            auth.is_pin_enrolled.return_value = True
            with (
                patch("memory.config_manager.CONFIG_FILE", config_path),
                patch("ui.API_FILE", config_path),
                patch("ui.hud_main.get_auth_manager", return_value=auth),
            ):
                hud_ui = HologramHUDUI(bridge=self.bridge)
                self._track_widget(hud_ui._win)
                app.processEvents()
                self.assertTrue(hud_ui._win._ready)
                self.assertIsNone(hud_ui._setup_controller._overlay)
                self.assertIsNotNone(hud_ui)
                hud_ui.set_state("SPEAKING")
                self.assertEqual(self.bridge.current_state, "SPEAKING")
                hud_ui.set_audio_level(0.85)

    def test_hud_compact_layout_adapts_to_narrow_windows(self):
        hud = self._track_widget(HUDMainWindow(bridge=self.bridge))
        hud.resize(390, 620)
        app.processEvents()
        self.assertTrue(hud._dashboard_button.isHidden())
        self.assertEqual(hud._right_menu.width(), 300 if hud.width() > 328 else hud.width() - 28)
        self.assertEqual(hud._mini_orb.width(), 40)
        self.assertTrue(hud._left_rail.isHidden())

        hud.resize(900, 700)
        app.processEvents()
        self.assertFalse(hud._dashboard_button.isHidden())
        self.assertEqual(hud._mini_orb.width(), 48)


if __name__ == "__main__":
    unittest.main()
