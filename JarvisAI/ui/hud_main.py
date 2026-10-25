"""
Main Neural Wireframe Hologram HUD Window Shell for Jarvis AI Pro.

Arranges modular glassmorphism telemetry panels around the central 3D wireframe visualizer.
Binds to real application state (Voice Biometrics, AuthState, Memory, Scheduler, and Hybrid Router).
"""

from __future__ import annotations

import os
import sys
import time

if sys.platform != "win32" and not os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import threading
from typing import Optional, Callable

from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGraphicsBlurEffect
)

from audio.visualizer_bridge import get_visualizer_bridge, VisualizerBridge
from ui.hologram.wireframe_head import NeuralWireframeHead
from ui.panels.hybrid_brain_panel import HybridBrainPanel
from ui.panels.security_panel import SecurityPanel
from ui.panels.memory_panel import MemoryPanel
from ui.panels.scheduler_panel import SchedulerPanel
from ui.panels.system_telemetry_ring import SystemTelemetryRing

try:
    from security.auth_manager import AuthManager, PRIVACY_LOCK, lock_workstation
    from core.security import get_auth_manager
except Exception:
    get_auth_manager = None
    lock_workstation = lambda: False
    PRIVACY_LOCK = "PRIVACY_LOCK"


class HUDMainWindow(QMainWindow):
    """
    Futuristic Neural Wireframe Hologram HUD Main Window.
    """

    sig_state_changed = pyqtSignal(str)

    def __init__(self, bridge: Optional[VisualizerBridge] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS AI PRO — NEURAL WIREFRAME HUD")
        self.resize(1280, 800)
        self.setMinimumSize(1024, 680)

        # Dark cyberpunk theme style
        self.setStyleSheet("""
            QMainWindow {
                background-color: #080b11;
            }
            QLabel {
                color: #c8d9d5;
            }
        """)

        self._bridge = bridge or get_visualizer_bridge()
        self._auth_manager = get_auth_manager() if callable(get_auth_manager) else None

        self._init_ui()
        self._wire_signals()

        # Update timer for periodic state polling (memory/scheduler/auth)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_real_states)
        self._poll_timer.start(1500)

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Header Bar
        hdr_layout = QHBoxLayout()
        hdr_title = QLabel("J.A.R.V.I.S  //  NEURAL HUD SYSTEM")
        hdr_title.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr_title.setStyleSheet("color: #00e5ff; letter-spacing: 2px;")
        hdr_layout.addWidget(hdr_title)

        hdr_layout.addStretch()

        self._lbl_clock = QLabel("--:--:--")
        self._lbl_clock.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._lbl_clock.setStyleSheet("color: #00e5ff;")
        hdr_layout.addWidget(self._lbl_clock)

        main_layout.addLayout(hdr_layout)

        # 2. Main Holographic Workspace (Left Panels, Central Hologram, Right Panels)
        body_layout = QHBoxLayout()
        body_layout.setSpacing(16)

        # --- LEFT TELEMETRY COLUMN ---
        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        self._panel_brain = HybridBrainPanel(self)
        self._panel_security = SecurityPanel(self)

        left_col.addWidget(self._panel_brain)
        left_col.addWidget(self._panel_security)
        left_col.addStretch()

        body_layout.addLayout(left_col, stretch=1)

        # --- CENTER WIREFRAME HOLOGRAM ---
        center_col = QVBoxLayout()
        center_col.setSpacing(8)

        self.wireframe_visualizer = NeuralWireframeHead(self)
        center_col.addWidget(self.wireframe_visualizer, stretch=1)

        # Status Banner underneath wireframe
        self._lbl_hud_status = QLabel("● SYSTEM STANDBY")
        self._lbl_hud_status.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._lbl_hud_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_hud_status.setStyleSheet("color: #00e5ff;")
        center_col.addWidget(self._lbl_hud_status)

        # Privacy Lock Banner Overlay (Hidden by default)
        self._lock_banner = QFrame(self)
        self._lock_banner.setStyleSheet("""
            QFrame {
                background-color: rgba(183, 28, 28, 0.92);
                border: 2px solid #ff1744;
                border-radius: 8px;
            }
        """)
        lb_layout = QVBoxLayout(self._lock_banner)
        lb_text = QLabel("SYSTEM PRIVACY LOCK ENGAGED — MUTED & LOCKED")
        lb_text.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        lb_text.setStyleSheet("color: #ffffff;")
        lb_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lb_layout.addWidget(lb_text)
        self._lock_banner.hide()

        body_layout.addLayout(center_col, stretch=2)

        # --- RIGHT TELEMETRY COLUMN ---
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        self._panel_memory = MemoryPanel(self)
        self._panel_scheduler = SchedulerPanel(self)
        self._panel_ring = SystemTelemetryRing(self)

        right_col.addWidget(self._panel_memory)
        right_col.addWidget(self._panel_scheduler)
        right_col.addWidget(self._panel_ring)
        right_col.addStretch()

        body_layout.addLayout(right_col, stretch=1)

        main_layout.addLayout(body_layout, stretch=1)

        # 3. Clock Timer
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(500)

    def _wire_signals(self):
        """Wire VisualizerBridge signals to UI components."""
        self._bridge.sig_audio_energy.connect(self.wireframe_visualizer.set_audio_energy)
        self._bridge.sig_state_changed.connect(self._on_state_changed)
        self._bridge.sig_auth_state_changed.connect(self._on_auth_state_changed)

    def _update_clock(self):
        self._lbl_clock.setText(time.strftime("%H:%M:%S"))

    @pyqtSlot(str)
    def _on_state_changed(self, state: str):
        st = str(state or "IDLE").upper()
        self.wireframe_visualizer.set_state(st)

        if st == "LISTENING":
            self._lbl_hud_status.setText("● LISTENING")
            self._lbl_hud_status.setStyleSheet("color: #00e676;")
        elif st == "THINKING":
            self._lbl_hud_status.setText("◈ THINKING")
            self._lbl_hud_status.setStyleSheet("color: #7c4dff;")
        elif st == "SPEAKING":
            self._lbl_hud_status.setText("● SPEAKING")
            self._lbl_hud_status.setStyleSheet("color: #00e5ff;")
        elif st in ("PRIVACY_LOCK", "LOCKDOWN"):
            self._handle_privacy_lock()
        else:
            self._lbl_hud_status.setText("○ STANDBY")
            self._lbl_hud_status.setStyleSheet("color: #00e5ff;")

    @pyqtSlot(str)
    def _on_auth_state_changed(self, auth_state: str):
        st = str(auth_state or "RESTRICTED").upper()
        failed_attempts = getattr(self._auth_manager, "failed_pin_attempts", 0) if self._auth_manager else 0
        method = getattr(self._auth_manager, "get_auth_method", lambda: "")() if self._auth_manager else ""

        self._panel_security.update_auth_state(st, failed_attempts, method or "Voice ID")

        if st in ("PRIVACY_LOCK", "LOCKDOWN"):
            self._handle_privacy_lock()
        else:
            self._clear_privacy_lock()

    def _handle_privacy_lock(self):
        """Engage privacy lockdown profile on HUD and trigger LockWorkStation."""
        self.wireframe_visualizer.set_state("PRIVACY_LOCK")
        self._lbl_hud_status.setText("⊘ PRIVACY LOCK ENGAGED")
        self._lbl_hud_status.setStyleSheet("color: #ff1744;")
        self._lock_banner.show()

        # Blur sensitive memory & scheduler telemetry
        blur_mem = QGraphicsBlurEffect()
        blur_mem.setBlurRadius(12)
        self._panel_memory.setGraphicsEffect(blur_mem)

        blur_sched = QGraphicsBlurEffect()
        blur_sched.setBlurRadius(12)
        self._panel_scheduler.setGraphicsEffect(blur_sched)

        # Hand focus to native Windows LockWorkStation call
        try:
            lock_workstation()
        except Exception:
            pass

    def _clear_privacy_lock(self):
        """Restore normal HUD view."""
        self._lock_banner.hide()
        self._panel_memory.setGraphicsEffect(None)
        self._panel_scheduler.setGraphicsEffect(None)

    def _poll_real_states(self):
        """Poll real backend state managers periodically."""
        if self._auth_manager:
            st = self._auth_manager.get_state()
            self._on_auth_state_changed(st)

        self._panel_memory.fetch_real_memory_state()
        self._panel_scheduler.fetch_real_scheduler_state()


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


class HologramHUDUI:
    """
    JARVIS UI Adapter launching the Neural Wireframe Hologram HUD window,
    fully compatible with JarvisLive requirements.
    """

    def __init__(self, bridge: Optional[VisualizerBridge] = None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self.bridge = bridge or get_visualizer_bridge()
        self._win = HUDMainWindow(bridge=self.bridge)
        self.root = _RootShim(self._app)
        self._win.show()

        self._muted = False
        self._ready = True
        self.on_text_command: Optional[Callable] = None
        self.on_remote_clicked: Optional[Callable] = None
        self.on_interrupt: Optional[Callable] = None
        self.on_voice_change: Optional[Callable] = None
        self.on_audio_device_change: Optional[Callable] = None
        self.on_voice_personality_change: Optional[Callable] = None
        self.on_voice_preview: Optional[Callable] = None
        self.on_voice_id_action: Optional[Callable] = None
        self.ptt_hold: Optional[Callable] = None
        self.on_push_to_talk: Optional[Callable] = None
        self.on_wake_toggle: Optional[Callable] = None
        self.on_wake_manual: Optional[Callable] = None
        self.wake_get_state: Optional[Callable] = None

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, v: bool):
        self._muted = bool(v)

    @property
    def current_file(self) -> Optional[str]:
        return None

    def write_log(self, text: str):
        print(f"[HUDLog] {text}")

    def set_state(self, state: str):
        st = str(state or "IDLE").upper()
        self.bridge.update_state(st)

    def set_audio_level(self, level: float):
        try:
            self.bridge.push_audio_energy(float(level))
        except Exception:
            pass

    def push_visemes(self, frames, hop: float, at: float):
        pass

    def react_avatar_text(self, text: str):
        pass

    def show_content(self, title: str, text: str):
        print(f"[HUDContent] {title}\n{text}")

    def show_confirm(self, title: str, detail: str):
        pass

    def hide_confirm(self):
        pass

    def start_camera_stream(self):
        pass

    def stop_camera_stream(self):
        pass

    def set_voice_id_enabled(self, enabled: bool):
        pass

    def notify_phone_connected(self):
        pass

    def hud_video_is_active(self) -> bool:
        return False

    def get_plugins(self):
        return []

    def get_plugin_settings(self):
        return {}

    def wait_for_api_key(self, stop_event=None) -> bool:
        return True

    def open_settings_drawer(self):
        pass

    def close_settings_drawer(self):
        pass

    def set_ui_color(self, color_hex: str):
        pass

    def set_hud_style(self, style_name: str):
        pass

    def toggle_side_panels(self, show: bool | None = None):
        pass

    def prompt_reconfig(self):
        pass

    def request_close(self):
        try:
            self._win.close()
        except Exception:
            pass
