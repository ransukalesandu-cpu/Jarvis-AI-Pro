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

from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal, QTimer, QSettings, QEasingCurve, QPropertyAnimation
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGraphicsBlurEffect, QGraphicsOpacityEffect, QCheckBox, QStackedWidget
)

from audio.visualizer_bridge import get_visualizer_bridge, VisualizerBridge
from ui.hologram.wireframe_head import NeuralWireframeHead
from ui.hologram.bihansa_hologram import BihansaHologramWidget
from ui.hologram.bihansa_settings import BihansaModeSettings, BihansaSettingsDialog
from ui.panels.hybrid_brain_panel import HybridBrainPanel
from ui.panels.security_panel import SecurityPanel
from ui.panels.memory_panel import MemoryPanel
from ui.panels.scheduler_panel import SchedulerPanel
from ui.panels.system_telemetry_ring import SystemTelemetryRing
from ui.panels.modern_dashboard import ModernDashboard

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
    sig_mode_changed = pyqtSignal()
    sig_viseme_schedule = pyqtSignal(object, float, float)
    sig_avatar_text = pyqtSignal(str)
    sig_hybrid_telemetry = pyqtSignal(str, float, str, str)

    def __init__(self, bridge: Optional[VisualizerBridge] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS AI PRO — COMMAND CENTER")
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

        self._privacy_locked = False
        self._init_ui()
        self._wire_signals()
        self._settings = QSettings("JarvisAI", "JarvisAIPro")
        from memory.config_manager import get_assistant_mode, load_api_keys
        enabled = (get_assistant_mode() == "bihansa" if "assistant_mode" in load_api_keys()
                   else self._settings.value("bihansa/enabled", False, type=bool))
        self._bihansa_toggle.setChecked(enabled)
        self._bihansa_effects.setChecked(self._settings.value("bihansa/effects", True, type=bool))
        self._bihansa_voice_reactive.setChecked(self._settings.value("bihansa/voice_reactive", True, type=bool))
        self._apply_bihansa_preferences()
        self._set_bihansa_enabled(self._bihansa_toggle.isChecked())

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
        hdr_title = QLabel("J.A.R.V.I.S  //  COMMAND CENTER")
        hdr_title.setFont(QFont("Aptos Display", 12, QFont.Weight.Bold))
        hdr_title.setStyleSheet("color: #00e5ff; letter-spacing: 2px;")
        hdr_layout.addWidget(hdr_title)

        hdr_layout.addStretch()

        self._lbl_clock = QLabel("--:--:--")
        self._lbl_clock.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._lbl_clock.setStyleSheet("color: #00e5ff;")
        hdr_layout.addWidget(self._lbl_clock)

        self._bihansa_toggle = QPushButton("BIHANSA MODE: OFF")
        self._bihansa_toggle.setCheckable(True)
        self._bihansa_toggle.setStyleSheet(
            "QPushButton { color: #ff9be8; background: #21101f; border: 1px solid #ff4fc8; padding: 8px 12px; font-weight: bold; }"
            "QPushButton:checked { color: #100613; background: #ff75d4; }"
        )
        self._bihansa_toggle.toggled.connect(self._set_bihansa_enabled)
        hdr_layout.addWidget(self._bihansa_toggle)

        self._bihansa_settings_btn = QPushButton("⚙ SETTINGS")
        self._bihansa_settings_btn.setStyleSheet(
            "QPushButton { color: #c8d9d5; background: #101923; border: 1px solid #42606b; padding: 8px 12px; }"
            "QPushButton:hover { color: #ffb3e2; border-color: #ff4fc8; }"
        )
        self._bihansa_settings_btn.clicked.connect(self._open_bihansa_settings)
        hdr_layout.addWidget(self._bihansa_settings_btn)

        main_layout.addLayout(hdr_layout)

        # 2. Modern bento-grid dashboard. The large face renderer is now a
        # secondary view; the main screen uses a compact audio-reactive orb.
        self._panel_brain = HybridBrainPanel(self)
        self._panel_security = SecurityPanel(self)
        self._panel_memory = MemoryPanel(self)
        self._panel_scheduler = SchedulerPanel(self)
        self._panel_ring = SystemTelemetryRing(self)

        self._workspace_stack = QStackedWidget(self)
        self._workspace_stack.setObjectName("WorkspacePageStack")
        self._dashboard = ModernDashboard(
            (
                self._panel_brain,
                self._panel_memory,
                self._panel_security,
                self._panel_scheduler,
                self._panel_ring,
            ),
            self._workspace_stack,
        )
        self._dashboard.avatar_requested.connect(self._show_avatar_page)
        self._dashboard.refresh_requested.connect(self._poll_real_states)
        self._workspace_stack.addWidget(self._dashboard)

        # Traditional avatar view remains available on demand, but no longer
        # takes the main landing page's visual space.
        self._avatar_page = QWidget(self._workspace_stack)
        avatar_layout = QVBoxLayout(self._avatar_page)
        avatar_layout.setContentsMargins(4, 4, 4, 4)
        avatar_layout.setSpacing(10)

        avatar_header = QHBoxLayout()
        avatar_title = QLabel("AVATAR VISUALIZER  /  AUDIO-REACTIVE MODE")
        avatar_title.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        avatar_title.setStyleSheet("color: #68d9ff; letter-spacing: 1px;")
        avatar_header.addWidget(avatar_title)
        avatar_header.addStretch(1)
        self._btn_dashboard = QPushButton("← COMMAND CENTER")
        self._btn_dashboard.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_dashboard.setStyleSheet(
            "QPushButton { color:#c7e0e9; background:rgba(104,217,255,0.06); "
            "border:1px solid rgba(104,217,255,0.30); border-radius:10px; "
            "padding:9px 12px; font:700 8pt 'Consolas'; } "
            "QPushButton:hover { background:rgba(104,217,255,0.16); border-color:#80e7ff; }"
        )
        self._btn_dashboard.clicked.connect(self._show_dashboard_page)
        avatar_header.addWidget(self._btn_dashboard)
        avatar_layout.addLayout(avatar_header)

        self._visualizer_stack = QStackedWidget(self._avatar_page)
        self.wireframe_visualizer = NeuralWireframeHead(self._avatar_page)
        self.bihansa_visualizer = BihansaHologramWidget(self._avatar_page)
        self._visualizer_stack.addWidget(self.wireframe_visualizer)
        self._visualizer_stack.addWidget(self.bihansa_visualizer)
        self._visualizer_stack.setCurrentWidget(self.wireframe_visualizer)
        avatar_layout.addWidget(self._visualizer_stack, stretch=1)

        # Bihansa-only visual controls remain on the dedicated avatar page.
        controls_layout = QHBoxLayout()
        self._bihansa_effects = QCheckBox("NEURAL EFFECTS")
        self._bihansa_effects.setChecked(True)
        self._bihansa_effects.setStyleSheet("QCheckBox { color: #ff9be8; spacing: 6px; }")
        self._bihansa_voice_reactive = QCheckBox("VOICE REACTIVE VISUALS")
        self._bihansa_voice_reactive.setChecked(True)
        self._bihansa_voice_reactive.setStyleSheet("QCheckBox { color: #ff9be8; spacing: 6px; }")
        controls_layout.addWidget(self._bihansa_effects)
        controls_layout.addWidget(self._bihansa_voice_reactive)
        controls_layout.addStretch(1)
        avatar_layout.addLayout(controls_layout)
        self._bihansa_effects.toggled.connect(self.bihansa_visualizer.set_effects_enabled)
        self._bihansa_voice_reactive.toggled.connect(self.bihansa_visualizer.set_voice_reactive)

        self._lbl_hud_status = QLabel("● SYSTEM STANDBY")
        self._lbl_hud_status.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self._lbl_hud_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_hud_status.setStyleSheet("color: #68d9ff;")
        avatar_layout.addWidget(self._lbl_hud_status)

        self._lbl_avatar_text = QLabel("")
        self._lbl_avatar_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_avatar_text.setWordWrap(True)
        self._lbl_avatar_text.setStyleSheet("color: #ffb3e2; font-size: 10px; padding: 4px;")
        self._lbl_avatar_text.hide()
        avatar_layout.addWidget(self._lbl_avatar_text)
        self._workspace_stack.addWidget(self._avatar_page)
        self._workspace_stack.setCurrentWidget(self._dashboard)
        self._dashboard.set_state("IDLE")
        self._page_transition = None
        self._page_transition_widget = None

        # Visible on either page, but hidden unless the security layer engages.
        self._lock_banner = QFrame(central_widget)
        self._lock_banner.setStyleSheet("""
            QFrame {
                background-color: rgba(183, 28, 28, 0.92);
                border: 2px solid #ff1744;
                border-radius: 10px;
            }
        """)
        lock_layout = QVBoxLayout(self._lock_banner)
        lock_text = QLabel("SYSTEM PRIVACY LOCK ENGAGED — MUTED & LOCKED")
        lock_text.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        lock_text.setStyleSheet("color: #ffffff; background: transparent;")
        lock_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lock_layout.addWidget(lock_text)
        self._lock_banner.hide()
        main_layout.addWidget(self._lock_banner)

        main_layout.addWidget(self._workspace_stack, stretch=1)

        # 3. Clock Timer
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(500)

    def _wire_signals(self):
        """Wire VisualizerBridge signals to UI components."""
        self._bridge.sig_audio_energy.connect(self.wireframe_visualizer.set_audio_energy)
        self._bridge.sig_audio_energy.connect(self._dashboard.set_audio_energy)
        self._bridge.sig_state_changed.connect(self._on_state_changed)
        self._bridge.sig_auth_state_changed.connect(self._on_auth_state_changed)
        self._bridge.sig_audio_energy.connect(self.bihansa_visualizer.set_audio_energy)
        self.sig_viseme_schedule.connect(self._schedule_visemes)
        self.sig_avatar_text.connect(self._show_avatar_text)
        self.sig_hybrid_telemetry.connect(self._panel_brain.update_telemetry)
        self._bihansa_effects.toggled.connect(lambda value: self._settings.setValue("bihansa/effects", value) if hasattr(self, "_settings") else None)
        self._bihansa_voice_reactive.toggled.connect(lambda value: self._settings.setValue("bihansa/voice_reactive", value) if hasattr(self, "_settings") else None)

    def _switch_workspace(self, page: QWidget) -> None:
        """Switch dashboard/avatar pages with a short opacity transition."""
        if not hasattr(self, "_workspace_stack"):
            return
        current = getattr(self, "_page_transition", None)
        if current is not None:
            try:
                current.stop()
            except RuntimeError:
                pass
        previous_page = getattr(self, "_page_transition_widget", None)
        if previous_page is not None and previous_page is not page:
            previous_page.setGraphicsEffect(None)

        self._workspace_stack.setCurrentWidget(page)
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(260)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def finish_transition():
            if self._page_transition is animation:
                page.setGraphicsEffect(None)
                self._page_transition = None
                self._page_transition_widget = None

        animation.finished.connect(finish_transition)
        self._page_transition = animation
        self._page_transition_widget = page
        animation.start()

    def _show_dashboard_page(self) -> None:
        self._switch_workspace(self._dashboard)

    def _show_avatar_page(self) -> None:
        self._switch_workspace(self._avatar_page)

    @pyqtSlot(bool)
    def _set_bihansa_enabled(self, enabled: bool):
        """Switch only the central visualizer; normal JARVIS remains available."""
        enabled = bool(enabled)
        self._visualizer_stack.setCurrentWidget(
            self.bihansa_visualizer if enabled else self.wireframe_visualizer
        )
        self._dashboard.set_bihansa_mode(enabled)
        self._bihansa_toggle.setText("BIHANSA MODE: ON" if enabled else "BIHANSA MODE: OFF")
        # Keep BIHANSA-only controls out of the standard JARVIS view.
        self._bihansa_effects.setVisible(enabled)
        self._bihansa_voice_reactive.setVisible(enabled)
        self._settings.setValue("bihansa/enabled", enabled)
        from memory.config_manager import save_assistant_mode
        save_assistant_mode("bihansa" if enabled else "jarvis")
        self.sig_mode_changed.emit()
        self._lbl_hud_status.setText("✦ BIHANSA NEURAL MODE" if enabled else "● SYSTEM STANDBY")
        self._lbl_hud_status.setStyleSheet("color: #ff75d4;" if enabled else "color: #00e5ff;")

    @pyqtSlot(object, float, float)
    def _schedule_visemes(self, frames, hop: float, at: float):
        """Schedule 20 ms audio-derived mouth poses on the Qt UI thread."""
        try:
            frame_list = list(frames or [])
            frame_hop = max(0.005, min(0.1, float(hop)))
            start_at = float(at)
        except (TypeError, ValueError):
            return
        for index, frame in enumerate(frame_list):
            try:
                level, openness, width = (float(frame[0]), float(frame[1]), float(frame[2]))
                level = max(0.0, min(1.0, level))
                openness = max(0.0, min(1.0, openness))
                width = max(-1.0, min(1.0, width))
            except (TypeError, ValueError, IndexError):
                continue
            if openness >= 0.72:
                shape = "aa"
            elif width >= 0.32:
                shape = "ee"
            elif width <= -0.42:
                shape = "ou"
            elif openness >= 0.32:
                shape = "oh"
            else:
                shape = "m"
            delay_ms = max(0, int((start_at + index * frame_hop - time.time()) * 1000))
            def apply_frame(lvl=level, selected=shape):
                self.bihansa_visualizer.set_audio_energy(lvl)
                for viseme_id in ("aa", "ee", "oh", "ou", "ch", "m"):
                    self.bihansa_visualizer.set_viseme(
                        viseme_id, 0.85 if viseme_id == selected else 0.0
                    )
            QTimer.singleShot(delay_ms, apply_frame)

    @pyqtSlot(str)
    def _show_avatar_text(self, text: str):
        cleaned = " ".join(str(text or "").split())
        self._lbl_avatar_text.setText(cleaned)
        self._lbl_avatar_text.setVisible(bool(cleaned))
        if cleaned:
            QTimer.singleShot(5000, lambda expected=cleaned: (
                self._lbl_avatar_text.hide()
                if self._lbl_avatar_text.text() == expected else None
            ))

    def _open_bihansa_settings(self):
        """Open the real preferences dialog and apply changes to the live HUD."""
        prefs = BihansaModeSettings(self._settings)
        dialog = BihansaSettingsDialog(self, settings=prefs, on_applied=self._apply_bihansa_preferences)
        dialog.exec()

    def _apply_bihansa_preferences(self):
        """Apply persisted appearance preferences to the active hologram widget."""
        prefs = BihansaModeSettings(self._settings)
        self.bihansa_visualizer.set_reduced_motion(prefs.reduced_motion)
        self.bihansa_visualizer.set_glow_intensity(prefs.glow_intensity)
        self.bihansa_visualizer.set_animation_speed(prefs.animation_speed)
        self.bihansa_visualizer.set_effects_enabled(
            self._bihansa_effects.isChecked() if hasattr(self, "_bihansa_effects") else True
        )
        self.bihansa_visualizer.set_voice_reactive(
            self._bihansa_voice_reactive.isChecked() if hasattr(self, "_bihansa_voice_reactive") else True
        )
        if hasattr(self, "_bihansa_toggle"):
            desired = prefs.assistant_mode == "bihansa"
            if self._bihansa_toggle.isChecked() != desired:
                self._bihansa_toggle.setChecked(desired)

    def _update_clock(self):
        self._lbl_clock.setText(time.strftime("%H:%M:%S"))

    @pyqtSlot(str)
    def _on_state_changed(self, state: str):
        st = str(state or "IDLE").upper()
        visual_state = "PRIVACY_LOCK" if self._privacy_locked else st
        self.wireframe_visualizer.set_state(visual_state)
        self.bihansa_visualizer.set_state(visual_state)
        self._dashboard.set_state(visual_state)
        if self._privacy_locked:
            return

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
        self._privacy_locked = True
        self.wireframe_visualizer.set_state("PRIVACY_LOCK")
        self.bihansa_visualizer.set_state("PRIVACY_LOCK")
        self._dashboard.set_state("PRIVACY_LOCK")
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
        was_locked = self._privacy_locked
        self._privacy_locked = False
        self._lock_banner.hide()
        if was_locked:
            state = self._bridge.current_state
            self._on_state_changed("IDLE" if state in ("PRIVACY_LOCK", "LOCKDOWN") else state)
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
        self._win.sig_mode_changed.connect(
            lambda: self.on_voice_change() if callable(self.on_voice_change) else None
        )

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
        try:
            self._win.sig_viseme_schedule.emit(list(frames or []), float(hop), float(at))
        except (TypeError, ValueError):
            pass

    def react_avatar_text(self, text: str):
        self._win.sig_avatar_text.emit(str(text or ""))

    def update_hybrid_telemetry(self, route: str, latency_ms: float, language: str = "Auto", model: str = ""):
        """Publish real hybrid fallback telemetry safely from worker threads."""
        try:
            self._win.sig_hybrid_telemetry.emit(
                str(route or "Unknown"),
                max(0.0, float(latency_ms)),
                str(language or "Auto"),
                str(model or ""),
            )
        except (TypeError, ValueError, RuntimeError):
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

    def prompt_reconfig(self):
        pass

    def request_close(self):
        try:
            self._win.close()
        except Exception:
            pass
