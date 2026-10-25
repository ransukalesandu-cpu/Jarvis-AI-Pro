"""
Automated UI Hologram Smoke Tests for Jarvis AI Pro Neural Wireframe HUD.
Verifies widget creation, state transitions, audio energy calculations, signal handling, and Bihansa Hologram mode.
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
import numpy as np

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

# Ensure QApplication exists before testing Qt widgets
app = QApplication.instance() or QApplication(sys.argv)

from audio.visualizer_bridge import VisualizerBridge, get_visualizer_bridge
from ui.hologram.wireframe_head import NeuralWireframeHead
from ui.hologram.bihansa_hologram import BihansaHologramWidget
from ui.panels.hybrid_brain_panel import HybridBrainPanel
from ui.panels.security_panel import SecurityPanel
from ui.panels.memory_panel import MemoryPanel
from ui.panels.scheduler_panel import SchedulerPanel
from ui.panels.system_telemetry_ring import SystemTelemetryRing
from ui.hud_main import HUDMainWindow, HologramHUDUI


class TestUIHologram(unittest.TestCase):

    def setUp(self):
        self.bridge = VisualizerBridge()

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
        """Test Bihansa 2.5D Neural Face Visualizer widget states, options, visemes, and fallback."""
        widget = BihansaHologramWidget()
        self.assertIsNotNone(widget)
        self.assertEqual(widget.get_state(), "IDLE")

        # Test state transitions
        for st in ["LISTENING", "THINKING", "SPEAKING", "IDLE"]:
            widget.set_state(st)
            self.assertEqual(widget.get_state(), st)

        # Test audio energy and visemes
        widget.set_audio_energy(0.85)
        self.assertEqual(widget._target_energy, 0.85)

        widget.set_viseme("open")
        self.assertEqual(widget._current_viseme, "open")

        widget.set_effects_enabled(False)
        self.assertFalse(widget._effects_enabled)

        widget.set_voice_reactive(False)
        self.assertFalse(widget._voice_reactive)
        self.assertEqual(widget._energy, 0.0)

        # Test fallback rendering when portrait pixmap is null
        widget._portrait = QPixmap()
        widget.resize(400, 400)
        widget.repaint()

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

    def test_hud_main_window_shell_and_bihansa_toggle(self):
        """Test HUD Main Window shell, Bihansa toggle, and Privacy Lock state handling."""
        hud = HUDMainWindow(bridge=self.bridge)
        hud.show()
        self.assertIsNotNone(hud)

        # Confirm default OFF mode uses normal JARVIS wireframe visualizer
        self.assertEqual(hud._visualizer_stack.currentWidget(), hud.wireframe_visualizer)

        # Toggle Bihansa Mode ON
        hud._bihansa_toggle.setChecked(True)
        self.assertEqual(hud._visualizer_stack.currentWidget(), hud.bihansa_visualizer)

        # Simulate state and energy changes via bridge
        self.bridge.update_state("SPEAKING")
        self.bridge.push_audio_energy(0.65)
        self.assertEqual(hud.wireframe_visualizer.get_state(), "SPEAKING")
        self.assertEqual(hud.bihansa_visualizer.get_state(), "SPEAKING")

        # Toggle Bihansa Mode OFF
        hud._bihansa_toggle.setChecked(False)
        self.assertEqual(hud._visualizer_stack.currentWidget(), hud.wireframe_visualizer)

        # Simulate PRIVACY_LOCK auth state change
        self.bridge.update_auth_state("PRIVACY_LOCK")
        self.assertFalse(hud._lock_banner.isHidden())

        # Clear PRIVACY_LOCK
        self.bridge.update_auth_state("FULL_ACCESS")
        self.assertTrue(hud._lock_banner.isHidden())

    def test_hologram_hud_ui_adapter(self):
        """Test HologramHUDUI adapter class wrapping HUDMainWindow."""
        ui = HologramHUDUI(bridge=self.bridge)
        self.assertIsNotNone(ui)
        ui.set_state("SPEAKING")
        self.assertEqual(self.bridge.current_state, "SPEAKING")
        ui.set_audio_level(0.85)


if __name__ == "__main__":
    unittest.main()
