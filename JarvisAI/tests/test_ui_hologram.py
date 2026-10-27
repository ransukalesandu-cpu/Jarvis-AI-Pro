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
from unittest.mock import patch
import numpy as np

from PyQt6.QtCore import QSettings, QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication

# Ensure QApplication exists before testing Qt widgets
app = QApplication.instance() or QApplication(sys.argv)

from audio.visualizer_bridge import VisualizerBridge, get_visualizer_bridge
from ui.hologram.wireframe_head import NeuralWireframeHead
from ui.hologram.bihansa_hologram import BihansaHologramWidget
from ui.hologram.neural_heart_reactor import NeuralHeartReactor
from ui.panels.hybrid_brain_panel import HybridBrainPanel
from ui.panels.security_panel import SecurityPanel
from ui.panels.memory_panel import MemoryPanel
from ui.panels.scheduler_panel import SchedulerPanel
from ui.panels.system_telemetry_ring import SystemTelemetryRing
from ui.hud_main import HUDMainWindow, HologramHUDUI
from ui.panels.modern_dashboard import FloatingHolographicOrb, SkeletonLoader
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

        # Clear PRIVACY_LOCK
        self.bridge.update_auth_state("FULL_ACCESS")
        self.assertTrue(hud._lock_banner.isHidden())
        self.assertEqual(hud.bihansa_visualizer.get_state(), "SPEAKING")
        self.assertEqual(hud.wireframe_visualizer.get_state(), "SPEAKING")

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

    def test_hologram_hud_ui_adapter(self):
        """Test HologramHUDUI adapter class wrapping HUDMainWindow."""
        ui = HologramHUDUI(bridge=self.bridge)
        self._track_widget(ui._win)
        self.assertIsNotNone(ui)
        ui.set_state("SPEAKING")
        self.assertEqual(self.bridge.current_state, "SPEAKING")
        ui.set_audio_level(0.85)


if __name__ == "__main__":
    unittest.main()
