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

from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal, QTimer, QSettings, QEvent, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QToolButton, QFrame, QGraphicsBlurEffect, QGraphicsOpacityEffect, QCheckBox, QStackedWidget
)

from audio.visualizer_bridge import get_visualizer_bridge, VisualizerBridge
from ui.hologram.wireframe_head import NeuralWireframeHead
from ui.hologram.bihansa_hologram import BihansaHologramWidget
from ui.hologram.neural_heart_reactor import NeuralHeartReactor
from ui.hologram.bihansa_settings import BihansaModeSettings, BihansaSettingsDialog
from ui.panels.hybrid_brain_panel import HybridBrainPanel
from ui.panels.security_panel import SecurityPanel
from ui.panels.memory_panel import MemoryPanel
from ui.panels.scheduler_panel import SchedulerPanel
from ui.panels.system_telemetry_ring import SystemTelemetryRing
from ui.panels.modern_dashboard import FloatingHolographicOrb, ModernDashboard
from ui.panels.hud_surface import BentoPanelSurface

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
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(6)

        # Minimal top row: remove decorative title/clock; keep one compact menu control.
        top_row = QHBoxLayout()
        top_row.addStretch()
        self._dashboard_button = QToolButton(self)
        self._dashboard_button.setText("▦")
        self._dashboard_button.setToolTip("Open Bento dashboard")
        self._dashboard_button.setFixedSize(38, 38)
        self._dashboard_button.setStyleSheet(
            "QToolButton { color: #00e5ff; background: rgba(10,18,28,190); "
            "border: 1px solid #17485a; border-radius: 19px; font-size: 20px; }"
            "QToolButton:hover { background: #102a38; border-color: #00e5ff; }"
        )
        top_row.addWidget(self._dashboard_button)
        self._right_menu_button = QToolButton(self)
        self._right_menu_button.setText("⋮")
        self._right_menu_button.setToolTip("JARVIS menu and settings")
        self._right_menu_button.setFixedSize(38, 38)
        self._right_menu_button.setStyleSheet(
            "QToolButton { color: #00e5ff; background: rgba(10,18,28,190); "
            "border: 1px solid #17485a; border-radius: 19px; font-size: 23px; }"
            "QToolButton:hover { background: #102a38; border-color: #00e5ff; }"
        )
        top_row.addWidget(self._right_menu_button)
        main_layout.addLayout(top_row)

        self._mini_orb = FloatingHolographicOrb(self, size_px=48)
        self._mini_orb.setToolTip("JARVIS live status")

        # --- Existing panels remain available, but collapse into icon-first menus. ---
        self._panel_brain = HybridBrainPanel(self)
        self._panel_security = SecurityPanel(self)
        self._panel_memory = MemoryPanel(self)
        self._panel_scheduler = SchedulerPanel(self)
        self._panel_ring = SystemTelemetryRing(self)
        self._surface_brain = BentoPanelSurface(self._panel_brain, self)
        self._surface_security = BentoPanelSurface(self._panel_security, self)
        self._surface_memory = BentoPanelSurface(self._panel_memory, self)
        self._surface_scheduler = BentoPanelSurface(self._panel_scheduler, self)
        self._surface_ring = BentoPanelSurface(self._panel_ring, self)

        body_layout = QHBoxLayout()
        body_layout.setSpacing(8)

        # Left icon rail. Text labels are intentionally replaced with tooltips.
        left_rail = QWidget(self)
        left_rail.setFixedWidth(44)
        self._left_rail = left_rail
        left_rail_layout = QVBoxLayout(left_rail)
        left_rail_layout.setContentsMargins(0, 8, 0, 8)
        left_rail_layout.setSpacing(8)
        self._left_icon_buttons = []
        for symbol, tooltip in (("◈", "Neural / Hybrid Brain"), ("⛨", "Security / Host verification")):
            button = QToolButton(left_rail)
            button.setText(symbol)
            button.setToolTip(tooltip)
            button.setFixedSize(40, 40)
            button.setStyleSheet(
                "QToolButton { color: #00d9f5; background: #0b131d; border: 1px solid #183544; "
                "border-radius: 12px; font-size: 20px; }"
                "QToolButton:hover { color: #ffffff; background: #123044; border-color: #00e5ff; }"
            )
            left_rail_layout.addWidget(button)
            self._left_icon_buttons.append(button)
        left_rail_layout.addStretch()



        # Center hologram stack is preserved; only surrounding navigation changes.
        center_col = QVBoxLayout()
        center_col.setSpacing(6)
        # Stage wrapper gives the heart/circuit graphics a transparent overlay layer.
        # The original hologram widget and its paint implementation are untouched.
        self._hologram_stage = QWidget(self)
        stage_layout = QVBoxLayout(self._hologram_stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(0)

        self._visualizer_stack = QStackedWidget(self._hologram_stage)
        self.wireframe_visualizer = NeuralWireframeHead(self)
        self.bihansa_visualizer = BihansaHologramWidget(self)
        self._visualizer_stack.addWidget(self.wireframe_visualizer)
        self._visualizer_stack.addWidget(self.bihansa_visualizer)
        self._visualizer_stack.setCurrentWidget(self.wireframe_visualizer)
        stage_layout.addWidget(self._visualizer_stack, stretch=1)
        stage_layout.addWidget(self._mini_orb, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._heart_reactor = NeuralHeartReactor(self._hologram_stage)
        self._heart_reactor.raise_()
        center_col.addWidget(self._hologram_stage, stretch=1)

        self._lbl_hud_status = QLabel("● SYSTEM STANDBY")
        self._lbl_hud_status.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._lbl_hud_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_hud_status.setStyleSheet("color: #00e5ff;")
        center_col.addWidget(self._lbl_hud_status)

        self._lbl_avatar_text = QLabel("")
        self._lbl_avatar_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_avatar_text.setWordWrap(True)
        self._lbl_avatar_text.setStyleSheet("color: #ffb3e2; font-size: 10px; padding: 4px;")
        self._lbl_avatar_text.hide()
        center_col.addWidget(self._lbl_avatar_text)

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

        # Right-side dropdown contains secondary telemetry and settings controls.
        self._right_menu = QFrame(central_widget)
        self._right_menu.setObjectName("rightDropdownMenu")
        self._right_menu.setFixedWidth(300)
        self._right_menu.setMaximumHeight(650)
        self._right_menu.setStyleSheet(
            "QFrame#rightDropdownMenu { background: rgba(9,17,27,248); border: 1px solid #17485a; border-radius: 14px; }"
        )
        right_menu_layout = QVBoxLayout(self._right_menu)
        right_menu_layout.setContentsMargins(10, 10, 10, 10)
        right_menu_layout.setSpacing(8)

        self._bihansa_toggle = QPushButton("BIHANSA MODE: OFF")
        self._bihansa_toggle.setCheckable(True)
        self._bihansa_toggle.setStyleSheet(
            "QPushButton { color: #ff9be8; background: #21101f; border: 1px solid #ff4fc8; padding: 8px 12px; font-weight: bold; border-radius: 8px; }"
            "QPushButton:checked { color: #100613; background: #ff75d4; }"
        )
        self._bihansa_toggle.toggled.connect(self._set_bihansa_enabled)
        right_menu_layout.addWidget(self._bihansa_toggle)

        self._bihansa_settings_btn = QPushButton("⚙  BIHANSA SETTINGS")
        self._bihansa_settings_btn.setStyleSheet(
            "QPushButton { color: #c8d9d5; background: #101923; border: 1px solid #42606b; padding: 8px 12px; border-radius: 8px; }"
            "QPushButton:hover { color: #ffb3e2; border-color: #ff4fc8; }"
        )
        self._bihansa_settings_btn.clicked.connect(self._open_bihansa_settings)
        right_menu_layout.addWidget(self._bihansa_settings_btn)

        self._bihansa_effects = QCheckBox("Neural effects")
        self._bihansa_effects.setChecked(True)
        self._bihansa_effects.setStyleSheet("QCheckBox { color: #ff9be8; spacing: 6px; padding: 4px; }")
        self._bihansa_voice_reactive = QCheckBox("Voice-reactive visuals")
        self._bihansa_voice_reactive.setChecked(True)
        self._bihansa_voice_reactive.setStyleSheet("QCheckBox { color: #ff9be8; spacing: 6px; padding: 4px; }")
        right_menu_layout.addWidget(self._bihansa_effects)
        right_menu_layout.addWidget(self._bihansa_voice_reactive)
        # Keep the popup lightweight; open real telemetry widgets on the dashboard.
        for label, panel_index in (
            ("OPEN BRAIN PANEL", 0),
            ("OPEN SECURITY PANEL", 1),
            ("OPEN MEMORY PANEL", 2),
            ("OPEN SCHEDULER", 3),
            ("OPEN SYSTEM TELEMETRY", 4),
        ):
            panel_button = QPushButton(label, self._right_menu)
            panel_button.setCursor(Qt.CursorShape.PointingHandCursor)
            panel_button.setStyleSheet(
                "QPushButton { color: #c8d9e5; background: rgba(12,24,35,220); "
                "border: 1px solid #244857; border-radius: 8px; padding: 7px 10px; text-align: left; }"
                "QPushButton:hover { color: #ffffff; border-color: #00e5ff; background: #102a38; }"
            )
            panel_button.clicked.connect(
                lambda checked=False, selected=panel_index: self._open_dashboard_panel(selected)
            )
            right_menu_layout.addWidget(panel_button)
        self._right_menu.hide()

        self._bihansa_effects.toggled.connect(self.bihansa_visualizer.set_effects_enabled)
        self._bihansa_voice_reactive.toggled.connect(self.bihansa_visualizer.set_voice_reactive)

        # The home page stays clean and centered. Telemetry lives on a distinct page.
        self._home_page = QWidget()
        self._home_page.setObjectName("HologramHomePage")
        self._home_page.setStyleSheet("QWidget#HologramHomePage { background: transparent; }")
        self._home_page.setLayout(center_col)

        self._workspace_stack = QStackedWidget(central_widget)
        self._workspace_stack.setObjectName("JarvisWorkspaceStack")
        self._workspace_stack.addWidget(self._home_page)

        dashboard_panels = (
            self._surface_brain,
            self._surface_security,
            self._surface_memory,
            self._surface_scheduler,
            self._surface_ring,
        )
        self._dashboard = ModernDashboard(dashboard_panels, parent=self._workspace_stack)
        # Preserve ModernDashboard objectName: its stylesheet selectors rely on it.
        self._workspace_stack.addWidget(self._dashboard)
        self._workspace_stack.setCurrentWidget(self._home_page)

        # Only the dashboard is faded; the live OpenGL hologram is never placed
        # under a graphics opacity effect, avoiding black flashes on GPU canvases.
        self._dashboard_opacity_effect = QGraphicsOpacityEffect(self._dashboard)
        self._dashboard_opacity_effect.setOpacity(1.0)
        self._dashboard.setGraphicsEffect(self._dashboard_opacity_effect)
        self._workspace_animation = QPropertyAnimation(
            self._dashboard_opacity_effect, b"opacity", self
        )
        self._workspace_animation.setDuration(220)
        self._workspace_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._workspace_animation.finished.connect(self._finish_workspace_transition)
        self._transition_target = None
        self._dashboard.avatar_requested.connect(self._show_hologram_page)
        self._dashboard.refresh_requested.connect(self._refresh_dashboard)

        body_layout.addWidget(left_rail, 0)
        body_layout.addWidget(self._workspace_stack, 1)
        main_layout.addLayout(body_layout, stretch=1)
        self._left_rail.hide()

        for index, button in enumerate(self._left_icon_buttons):
            button.clicked.connect(
                lambda checked=False, selected=index: self._open_dashboard_panel(selected)
            )
        self._dashboard_button.clicked.connect(self._toggle_dashboard_page)
        self._right_menu_button.clicked.connect(self._toggle_right_dropdown)


    def resizeEvent(self, event):
        """Keep floating menus inside the central workspace after window resizes."""
        super().resizeEvent(event)
        if hasattr(self, "_right_menu") and self._right_menu.isVisible():
            self._position_right_menu()

    def _toggle_dashboard_page(self):
        """Switch between a clean hologram home and the separate Bento dashboard."""
        if self._workspace_stack.currentWidget() is self._home_page:
            self._show_dashboard_page()
        else:
            self._show_hologram_page()

    def _show_dashboard_page(self):
        """Reveal the telemetry dashboard without applying effects to the OpenGL hologram."""
        self._workspace_animation.stop()
        self._transition_target = "dashboard"
        self._right_menu.hide()
        self._left_rail.show()
        self._dashboard_opacity_effect.setOpacity(0.0)
        self._workspace_stack.setCurrentWidget(self._dashboard)
        self._dashboard_button.setText("⌂")
        self._dashboard_button.setToolTip("Return to hologram home")
        self._workspace_animation.setStartValue(0.0)
        self._workspace_animation.setEndValue(1.0)
        self._workspace_animation.start()

    def _show_hologram_page(self):
        """Return to the hologram-only home using a safe dashboard fade-out."""
        self._workspace_animation.stop()
        if self._workspace_stack.currentWidget() is self._home_page:
            self._finish_workspace_transition()
            return
        self._transition_target = "home"
        self._right_menu.hide()
        self._workspace_animation.setStartValue(self._dashboard_opacity_effect.opacity())
        self._workspace_animation.setEndValue(0.0)
        self._workspace_animation.start()

    def _finish_workspace_transition(self):
        """Finalize navigation state after a dashboard-only fade animation."""
        target = self._transition_target
        if target == "home":
            self._workspace_stack.setCurrentWidget(self._home_page)
            self._left_rail.hide()
            self._dashboard_opacity_effect.setOpacity(1.0)
            self._dashboard_button.setText("▦")
            self._dashboard_button.setToolTip("Open Bento dashboard")
        elif target == "dashboard":
            self._dashboard_button.setText("⌂")
            self._dashboard_button.setToolTip("Return to hologram home")
        self._transition_target = None

    def _open_dashboard_panel(self, panel_index: int):
        """Open the separate dashboard and scroll to one existing live telemetry panel."""
        if panel_index < 0 or panel_index >= len(self._dashboard._cards):
            return
        if self._workspace_stack.currentWidget() is not self._dashboard:
            self._show_dashboard_page()
        QTimer.singleShot(280, lambda index=panel_index: self._focus_dashboard_panel(index))

    def _focus_dashboard_panel(self, panel_index: int):
        """Scroll to the selected panel when a navigation shortcut is used."""
        if panel_index < 0 or panel_index >= len(self._dashboard._cards):
            return
        scroll = self._dashboard.findChild(QWidget, "DashboardScroll")
        if scroll is not None and hasattr(scroll, "ensureWidgetVisible"):
            scroll.ensureWidgetVisible(self._dashboard._cards[panel_index], 10, 10)

    def _refresh_dashboard(self):
        """Refresh the existing telemetry sources without replacing their live widgets."""
        self._poll_real_states()
        try:
            self._panel_ring.update_metrics()
        except Exception as exc:
            print(f"[JARVIS HUD] Telemetry refresh failed: {type(exc).__name__}: {exc}")
        self._dashboard.finish_loading()

    def _position_right_menu(self):
        """Anchor the dropdown to the right edge without clipping on narrow windows."""
        host = self.centralWidget()
        if host is None:
            return
        x = max(8, host.width() - self._right_menu.width() - 12)
        self._right_menu.move(x, 50)
        self._right_menu.raise_()

    def _toggle_right_dropdown(self):
        """Show a floating right dropdown without shrinking the hologram workspace."""
        should_show = not self._right_menu.isVisible()
        if should_show:
            self._position_right_menu()
        self._right_menu.setVisible(should_show)

    def _wire_signals(self):
        """Wire VisualizerBridge signals to UI components."""
        self._bridge.sig_audio_energy.connect(self.wireframe_visualizer.set_audio_energy)
        self._bridge.sig_audio_energy.connect(self._mini_orb.set_audio_energy)
        self._bridge.sig_audio_energy.connect(self._dashboard.set_audio_energy)
        self._bridge.sig_state_changed.connect(self._on_state_changed)
        self._bridge.sig_auth_state_changed.connect(self._on_auth_state_changed)
        self._bridge.sig_audio_energy.connect(self.bihansa_visualizer.set_audio_energy)
        self.sig_viseme_schedule.connect(self._schedule_visemes)
        self.sig_avatar_text.connect(self._show_avatar_text)
        self.sig_hybrid_telemetry.connect(self._panel_brain.update_telemetry)
        self._bihansa_effects.toggled.connect(lambda value: self._settings.setValue("bihansa/effects", value) if hasattr(self, "_settings") else None)
        self._bihansa_voice_reactive.toggled.connect(lambda value: self._settings.setValue("bihansa/voice_reactive", value) if hasattr(self, "_settings") else None)

    @pyqtSlot(bool)
    def _set_bihansa_enabled(self, enabled: bool):
        """Switch only the central visualizer; normal JARVIS remains available."""
        enabled = bool(enabled)
        self._visualizer_stack.setCurrentWidget(
            self.bihansa_visualizer if enabled else self.wireframe_visualizer
        )
        self._mini_orb.set_bihansa_mode(enabled)
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
        self._mini_orb.set_state(visual_state)
        self._dashboard.set_state(visual_state)
        self._heart_reactor.set_state(visual_state)
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
        self._mini_orb.set_state("PRIVACY_LOCK")
        self._dashboard.set_state("PRIVACY_LOCK")
        self._heart_reactor.set_state("PRIVACY_LOCK")
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
