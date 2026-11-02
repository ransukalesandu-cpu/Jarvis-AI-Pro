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

from typing import Optional, Callable

from PyQt6.QtCore import (
    Qt, QObject, QEvent, pyqtSlot, pyqtSignal, QTimer, QSettings,
    QPropertyAnimation, QEasingCurve,
)
from PyQt6.QtGui import QFont, QCursor
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

from core import failsoft

# The autonomous-task surface and the minimised status widget are optional: a
# failure to import them costs the owner the panel, never the HUD.
try:
    from ui.panels.autonomous_panel import AutonomousPanel
except Exception:  # pragma: no cover - defensive
    failsoft.suppress("ui.hud_main:import_autonomous_panel")
    AutonomousPanel = None
try:
    from ui.dynamic_island import DynamicIslandController
except Exception:  # pragma: no cover - defensive
    failsoft.suppress("ui.hud_main:import_dynamic_island")
    DynamicIslandController = None


def _agent_ui_enabled() -> bool:
    """Whether the autonomous HUD surfaces are switched on.

    Default off: the dashboard card, the rail button and the menu entries all
    change the HUD's composition, and the engine works without them. Enable
    with ``autonomous_ui_enabled`` in the config or ``JARVIS_AUTONOMOUS_UI=1``.
    """
    try:
        from agent.settings import AgentSettings

        return bool(AgentSettings.load().ui_enabled)
    except Exception:
        failsoft.suppress("ui.hud_main:_agent_ui_enabled")
        return False


try:
    from security.auth_manager import PRIVACY_LOCK, lock_workstation
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
    sig_setup_requested = pyqtSignal()

    def __init__(self, bridge: Optional[VisualizerBridge] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS AI PRO — NEURAL WIREFRAME HUD")
        self.resize(1280, 800)
        self.setMinimumSize(1024, 680)
        # The adapter clears this until Gemini and owner security setup finish.
        # JarvisLive also checks it when an invalid API key requests reconfiguration.
        self._ready = True

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
        # Let native Qt resize/layout processing finish before moving floating children.
        self._resize_layout_timer = QTimer(self)
        self._resize_layout_timer.setSingleShot(True)
        self._resize_layout_timer.timeout.connect(self._apply_deferred_resize_layout)
        self._init_ui()
        self._wire_signals()
        # Minimising must not leave a large empty frame on the desktop: the
        # Dynamic Island takes over while the HUD is minimised.
        self._island_controller = (
            DynamicIslandController(self) if DynamicIslandController is not None else None
        )
        self._settings = QSettings("JarvisAI", "JarvisAIPro")
        from memory.config_manager import get_assistant_mode, load_api_keys
        enabled = (get_assistant_mode() == "bihansa" if "assistant_mode" in load_api_keys()
                   else self._settings.value("bihansa/enabled", False, type=bool))
        self._bihansa_toggle.setChecked(enabled)
        self._bihansa_effects.setChecked(self._settings.value("bihansa/effects", True, type=bool))
        self._bihansa_voice_reactive.setChecked(self._settings.value("bihansa/voice_reactive", True, type=bool))
        self._reduced_motion_toggle.setChecked(self._settings.value("accessibility/reduced_motion", False, type=bool))
        self._apply_bihansa_preferences()
        self._set_bihansa_enabled(self._bihansa_toggle.isChecked())

        # Update timer for periodic state polling (memory/scheduler/auth)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_real_states)
        self._poll_timer.start(1500)

    def _init_ui(self):
        # Assigned first, because the right-hand menu and the dashboard read it.
        # Built only when the opt-in HUD flag is on, and only once the central
        # widget exists (a panel parented to the bare window would be a stray,
        # layout-less child).
        self._panel_agent = None
        self._agent_stop_button = None

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        if _agent_ui_enabled() and AutonomousPanel is not None:
            self._panel_agent = AutonomousPanel(central_widget)

        main_layout = QVBoxLayout(central_widget)
        self._main_layout = main_layout
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
        left_rail_entries = [
            ("◈", "Neural / Hybrid Brain"),
            ("⛨", "Security / Host verification"),
        ]
        if self._panel_agent is not None:
            left_rail_entries.append(("◉", "Autonomous task monitor"))
        for symbol, tooltip in left_rail_entries:
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
        self._reduced_motion_toggle = QCheckBox("Reduce hologram motion")
        self._reduced_motion_toggle.setToolTip("Reduce continuous movement and animation for a calmer display")
        self._reduced_motion_toggle.setStyleSheet("QCheckBox { color: #b9d7df; spacing: 6px; padding: 4px; }")
        right_menu_layout.addWidget(self._bihansa_effects)
        right_menu_layout.addWidget(self._bihansa_voice_reactive)
        right_menu_layout.addWidget(self._reduced_motion_toggle)
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
        if self._panel_agent is not None:
            agent_button = QPushButton("AUTONOMOUS TASKS", self._right_menu)
            agent_button.setCursor(Qt.CursorShape.PointingHandCursor)
            agent_button.setStyleSheet(
                "QPushButton { color: #c8d9e5; background: rgba(12,24,35,220); "
                "border: 1px solid #244857; border-radius: 8px; padding: 7px 10px; "
                "text-align: left; }"
                "QPushButton:hover { color: #ffffff; border-color: #00e5ff; background: #102a38; }"
            )
            agent_button.clicked.connect(self._open_agent_panel)
            right_menu_layout.addWidget(agent_button)
            self._agent_stop_button = QPushButton("STOP AUTONOMOUS TASK", self._right_menu)
            self._agent_stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._agent_stop_button.setStyleSheet(
                "QPushButton { color: #ffd6de; background: rgba(255,69,107,0.14); "
                "border: 1px solid rgba(255,69,107,0.55); border-radius: 8px; "
                "padding: 7px 10px; text-align: left; }"
                "QPushButton:hover { background: rgba(255,69,107,0.30); }"
            )
            self._agent_stop_button.clicked.connect(self._stop_agent_task)
            right_menu_layout.addWidget(self._agent_stop_button)
        self._right_menu_opacity = QGraphicsOpacityEffect(self._right_menu)
        self._right_menu_opacity.setOpacity(1.0)
        self._right_menu.setGraphicsEffect(self._right_menu_opacity)
        self._right_menu_animation = QPropertyAnimation(
            self._right_menu_opacity, b"opacity", self
        )
        self._right_menu_animation.setDuration(150)
        self._right_menu_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._right_menu_animation.finished.connect(self._finish_right_menu_transition)
        self._right_menu_hide_after_fade = False
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
        self._dashboard = ModernDashboard(
            dashboard_panels,
            parent=self._workspace_stack,
            extra_panel=self._panel_agent,
        )
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

        # Keep the home page clean while exposing a keyboard- and pointer-accessible edge trigger.
        self._left_menu_trigger = QToolButton(central_widget)
        self._left_menu_trigger.setObjectName("leftMegaMenuTrigger")
        self._left_menu_trigger.setText("›")
        self._left_menu_trigger.setToolTip("Hover or activate to open navigation")
        self._left_menu_trigger.setFixedSize(18, 58)
        self._left_menu_trigger.setStyleSheet(
            "QToolButton#leftMegaMenuTrigger { color: #ffbd7a; "
            "background: rgba(10,18,28,175); border: 1px solid #69462e; "
            "border-left: none; border-radius: 0 12px 12px 0; font-size: 22px; }"
            "QToolButton#leftMegaMenuTrigger:hover { color: #fff; "
            "background: rgba(70,40,25,220); border-color: #ffb066; }"
        )
        self._left_menu_trigger.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._left_menu_trigger.clicked.connect(self._show_left_rail)
        self._left_rail_hide_timer = QTimer(self)
        self._left_rail_hide_timer.setSingleShot(True)
        self._left_rail_hide_timer.timeout.connect(self._hide_left_rail_if_pointer_outside)
        self._left_menu_trigger.installEventFilter(self)
        self._left_rail.installEventFilter(self)
        for _button in self._left_icon_buttons:
            _button.installEventFilter(self)
        self._position_left_menu_trigger()
        self._left_menu_trigger.show()

        for index, button in enumerate(self._left_icon_buttons):
            if index >= 2 and self._panel_agent is not None:
                button.clicked.connect(
                    lambda checked=False: self._open_agent_panel()
                )
            else:
                button.clicked.connect(
                    lambda checked=False, selected=index: self._open_dashboard_panel(selected)
                )
        self._dashboard_button.clicked.connect(self._toggle_dashboard_page)
        self._right_menu_button.clicked.connect(self._toggle_right_dropdown)
        self._apply_compact_layout()


    def _apply_deferred_resize_layout(self) -> None:
        """Apply geometry and rendering budgets after native resize processing."""
        self._apply_compact_layout()
        self._apply_hologram_stage_budget()
        self._position_left_menu_trigger()
        if hasattr(self, "_right_menu") and self._right_menu.isVisible():
            self._position_right_menu()

    def _apply_compact_layout(self) -> None:
        """Adapt menus and spacing on narrow displays without replacing the face."""
        layout = getattr(self, "_main_layout", None)
        stage = getattr(self, "_hologram_stage", None)
        if layout is None or stage is None:
            return
        width = max(1, self.width())
        compact = width <= 560
        ultra_compact = width <= 420
        margin = 5 if ultra_compact else (7 if compact else 10)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(4 if compact else 6)
        self._dashboard_button.setVisible(not ultra_compact)
        self._right_menu.setFixedWidth(min(300, max(220, width - 28)))
        self._right_menu.setMaximumHeight(max(240, self.height() - 76))
        if compact:
            self._left_rail.hide()
            self._left_menu_trigger.setFixedSize(14, 48)
        else:
            self._left_menu_trigger.setFixedSize(18, 58)
        stage.setMinimumHeight(170 if ultra_compact else 210 if compact else 0)
        orb_size = 40 if compact else 48
        self._mini_orb.setFixedSize(orb_size, orb_size)
        self._position_left_menu_trigger()
        if self._right_menu.isVisible():
            self._position_right_menu()

    def _apply_hologram_stage_budget(self) -> None:
        """Scale procedural rendering work to the space available for the face."""
        stage = getattr(self, "_hologram_stage", None)
        if stage is None:
            return
        width, height = stage.width(), stage.height()
        if width <= 0 or height <= 0:
            return
        area = width * height
        if width < 720 or height < 420 or area < 300_000:
            frame_interval, particle_scale, glow_scale = 33, 0.62, 0.58
        elif area < 520_000:
            frame_interval, particle_scale, glow_scale = 24, 0.82, 0.78
        else:
            frame_interval, particle_scale, glow_scale = 16, 1.0, 1.0
        self.wireframe_visualizer.set_performance_budget(
            frame_interval, particle_scale, glow_scale
        )
        self.bihansa_visualizer.set_performance_budget(
            frame_interval, particle_scale, glow_scale
        )
        self._mini_orb.setFixedSize(40 if width < 720 or height < 420 else 48,
                                    40 if width < 720 or height < 420 else 48)
        self._heart_reactor.setGeometry(stage.rect())
        self._heart_reactor.raise_()

    def resizeEvent(self, event):
        """Schedule floating-child geometry after the native resize event returns."""
        super().resizeEvent(event)
        timer = getattr(self, "_resize_layout_timer", None)
        if timer is not None:
            timer.start(50)

    def changeEvent(self, event):
        """Swap the full HUD for the compact status widget while minimised."""
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowStateChange:
            return
        controller = getattr(self, "_island_controller", None)
        if controller is None:
            return
        try:
            controller.sync(self.isMinimized())
        except Exception:
            failsoft.suppress("ui.hud_main:changeEvent")

    def closeEvent(self, event):
        controller = getattr(self, "_island_controller", None)
        if controller is not None:
            try:
                controller.shutdown()
            except Exception:
                failsoft.suppress("ui.hud_main:closeEvent")
        super().closeEvent(event)

    def _position_left_menu_trigger(self) -> None:
        """Keep the edge trigger vertically centred in the central workspace."""
        trigger = getattr(self, "_left_menu_trigger", None)
        central = self.centralWidget()
        if trigger is not None and central is not None:
            trigger.move(0, max(24, (central.height() - trigger.height()) // 2))
            trigger.raise_()

    def _show_left_rail(self) -> None:
        """Reveal navigation when the edge trigger is activated."""
        if self._workspace_stack.currentWidget() is self._dashboard:
            return
        self._left_rail_hide_timer.stop()
        self._left_rail.show()
        self._left_rail.raise_()

    def _hide_left_rail_if_pointer_outside(self) -> None:
        """Collapse only when neither pointer nor keyboard focus uses navigation."""
        if self._workspace_stack.currentWidget() is self._dashboard:
            return
        focus = QApplication.focusWidget()
        while focus is not None:
            if focus is self._left_menu_trigger or focus is self._left_rail:
                return
            if any(focus is button for button in self._left_icon_buttons):
                return
            focus = focus.parentWidget()
        global_pos = QCursor.pos()
        if QApplication.platformName().lower() != "offscreen":
            widget = QApplication.widgetAt(global_pos)
            while widget is not None:
                if widget is self._left_rail or widget is self._left_menu_trigger:
                    return
                widget = widget.parentWidget()
        else:
            for candidate in (self._left_rail, self._left_menu_trigger):
                try:
                    if candidate.rect().contains(candidate.mapFromGlobal(global_pos)):
                        return
                except RuntimeError:
                    continue
        self._left_rail.hide()

    def eventFilter(self, watched, event):
        """Expand the home navigation on hover and dismiss it after pointer/focus exit."""
        navigation_widgets = (
            watched is self._left_menu_trigger
            or watched is self._left_rail
            or any(watched is button for button in self._left_icon_buttons)
        )
        if navigation_widgets:
            if event.type() in (QEvent.Type.Enter, QEvent.Type.FocusIn):
                self._left_rail_hide_timer.stop()
                if (
                    event.type() == QEvent.Type.Enter
                    and self._workspace_stack.currentWidget() is not self._dashboard
                ):
                    self._left_rail.show()
                    self._left_rail.raise_()
                return False
            if event.type() in (QEvent.Type.Leave, QEvent.Type.FocusOut):
                self._left_rail_hide_timer.start(180)
                return False
        return super().eventFilter(watched, event)

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
        self._hide_right_menu()
        self._left_rail.show()
        self._left_menu_trigger.hide()
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
        self._hide_right_menu()
        self._workspace_animation.setStartValue(self._dashboard_opacity_effect.opacity())
        self._workspace_animation.setEndValue(0.0)
        self._workspace_animation.start()

    def _finish_workspace_transition(self):
        """Finalize navigation state after a dashboard-only fade animation."""
        target = self._transition_target
        if target == "home":
            self._workspace_stack.setCurrentWidget(self._home_page)
            self._left_rail.hide()
            self._left_menu_trigger.show()
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
        self._hide_right_menu()
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

    def _open_agent_panel(self):
        """Open the dashboard and scroll to the autonomous task card."""
        self._hide_right_menu()
        if self._panel_agent is None:
            return
        if self._workspace_stack.currentWidget() is not self._dashboard:
            self._show_dashboard_page()
        QTimer.singleShot(280, self._dashboard.open_extra)

    def _stop_agent_task(self):
        """Immediate stop for a running autonomous task (no confirmation)."""
        try:
            from agent.integration import get_service

            get_service().stop("Stopped from the HUD menu.")
        except Exception:
            failsoft.suppress("ui.hud_main:_stop_agent_task")
        if self._panel_agent is not None:
            self._panel_agent.refresh()

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

    def _finish_right_menu_transition(self) -> None:
        """Hide the popup only after its closing fade has completed."""
        if self._right_menu_hide_after_fade:
            self._right_menu.hide()
            self._right_menu_opacity.setOpacity(1.0)
            self._right_menu_hide_after_fade = False

    def _show_right_menu(self) -> None:
        """Fade the settings popup in without changing the hologram workspace."""
        self._right_menu_animation.stop()
        self._right_menu_hide_after_fade = False
        self._position_right_menu()
        self._right_menu_opacity.setOpacity(0.0)
        self._right_menu.show()
        self._right_menu.raise_()
        self._right_menu_animation.setStartValue(0.0)
        self._right_menu_animation.setEndValue(1.0)
        self._right_menu_animation.start()

    def _hide_right_menu(self) -> None:
        """Fade the settings popup out while keeping it alive for the animation."""
        if not self._right_menu.isVisible():
            return
        self._right_menu_animation.stop()
        self._right_menu_hide_after_fade = True
        self._right_menu_animation.setStartValue(self._right_menu_opacity.opacity())
        self._right_menu_animation.setEndValue(0.0)
        self._right_menu_animation.start()

    def _toggle_right_dropdown(self):
        """Toggle the settings popup with a short opacity transition."""
        if self._right_menu.isVisible():
            self._hide_right_menu()
        else:
            self._show_right_menu()

    def _wire_signals(self):
        """Wire VisualizerBridge signals to UI components."""
        self._bridge.sig_audio_energy.connect(self.wireframe_visualizer.set_audio_energy)
        self._bridge.sig_audio_energy.connect(self._mini_orb.set_audio_energy)
        self._bridge.sig_audio_energy.connect(self._heart_reactor.set_audio_energy)
        self._bridge.sig_audio_energy.connect(self._dashboard.set_audio_energy)
        self._bridge.sig_state_changed.connect(self._on_state_changed)
        self._bridge.sig_auth_state_changed.connect(self._on_auth_state_changed)
        self._bridge.sig_audio_energy.connect(self.bihansa_visualizer.set_audio_energy)
        self.sig_viseme_schedule.connect(self._schedule_visemes)
        self.sig_avatar_text.connect(self._show_avatar_text)
        self.sig_hybrid_telemetry.connect(self._panel_brain.update_telemetry)
        self._bihansa_effects.toggled.connect(lambda value: self._settings.setValue("bihansa/effects", value) if hasattr(self, "_settings") else None)
        self._bihansa_voice_reactive.toggled.connect(lambda value: self._settings.setValue("bihansa/voice_reactive", value) if hasattr(self, "_settings") else None)
        self._reduced_motion_toggle.toggled.connect(self._set_reduced_motion)

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
        current_state = str(self._bridge.current_state or "IDLE").strip().upper()
        if current_state in ("IDLE", "READY", "STANDBY"):
            self._lbl_hud_status.setText(
                "✦ BIHANSA NEURAL MODE" if enabled else "● SYSTEM STANDBY"
            )
            self._lbl_hud_status.setStyleSheet(
                "color: #ff75d4;" if enabled else "color: #00e5ff;"
            )
        else:
            # Palette/persona changes must not erase a live warning or state.
            self._on_state_changed(current_state)

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

    def _set_reduced_motion(self, enabled: bool):
        """Apply the global accessibility preference to both hologram personas."""
        enabled = bool(enabled)
        if hasattr(self, "_settings"):
            self._settings.setValue("accessibility/reduced_motion", enabled)
        bihansa_prefs = BihansaModeSettings(self._settings)
        self.wireframe_visualizer.set_reduced_motion(enabled)
        self.bihansa_visualizer.set_reduced_motion(enabled or bihansa_prefs.reduced_motion)

    def _apply_bihansa_preferences(self):
        """Apply persisted appearance preferences to the active hologram widget."""
        prefs = BihansaModeSettings(self._settings)
        global_reduced_motion = self._settings.value("accessibility/reduced_motion", False, type=bool)
        self.wireframe_visualizer.set_reduced_motion(global_reduced_motion)
        self.bihansa_visualizer.set_reduced_motion(global_reduced_motion or prefs.reduced_motion)
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
        elif st in ("ERROR", "FAILED", "AUDIO_ERROR", "SESSION_ERROR"):
            self._lbl_hud_status.setText("⚠ SYSTEM ERROR")
            self._lbl_hud_status.setStyleSheet("color: #ff6b6b;")
        elif st in ("DISCONNECTED", "OFFLINE", "CONNECTION_LOST"):
            self._lbl_hud_status.setText("○ DISCONNECTED")
            self._lbl_hud_status.setStyleSheet("color: #ffb066;")
        elif st in ("PRIVACY_LOCK", "LOCKDOWN"):
            self._handle_privacy_lock()
        elif st in ("IDLE", "READY", "STANDBY"):
            self._lbl_hud_status.setText("○ STANDBY")
            self._lbl_hud_status.setStyleSheet("color: #00e5ff;")
        else:
            readable_state = st.replace("_", " ")[:32]
            self._lbl_hud_status.setText(f"● {readable_state}")
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
            failsoft.suppress('ui.hud_main:HUDMainWindow._handle_privacy_lock')

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


class _HudSetupController(QObject):
    """Keeps first-run credentials and owner-PIN enrollment inside the hologram HUD."""

    def __init__(self, ui, window: HUDMainWindow):
        super().__init__(window)
        self._ui = ui
        self._win = window
        self._overlay = None
        self._pending_voice_enrollment = False
        self._win.sig_setup_requested.connect(self.show_gemini_setup)

    def _api_configured(self) -> bool:
        """Match the live Gemini session's source of truth: the local config file.

        `JarvisLive._get_api_key` reads config/api_keys.json directly, so an
        environment-only key must not mark the HUD ready when that file is
        missing or has no usable key.
        """
        try:
            from memory.config_manager import load_api_keys
            key = load_api_keys().get("gemini_api_key", "")
            return isinstance(key, str) and len(key.strip()) > 15
        except Exception:
            return False

    @pyqtSlot()
    def start(self) -> None:
        self._win._ready = False
        self._ui._ready = False
        if not self._api_configured():
            self.show_gemini_setup()
            return
        self._show_owner_pin_setup_if_needed()

    @pyqtSlot()
    def show_gemini_setup(self) -> None:
        """Place the Gemini-only setup card over the HUD instead of swapping windows."""
        if self._overlay is not None:
            try:
                self._overlay.show()
                self._overlay.raise_()
                self._overlay._key_field.setFocus()
                return
            except RuntimeError:
                self._overlay = None

        try:
            from ui import SetupOverlay
            # This overlay is only used when the saved key is missing or rejected.
            # Never allow the rejected value to be silently re-submitted as "keep".
            overlay = SetupOverlay(
                self._win.centralWidget(),
                allow_keep_existing=False,
            )
            central = self._win.centralWidget()
            width, height = 480, 370
            overlay.setGeometry(
                max(12, (central.width() - width) // 2),
                max(12, (central.height() - height) // 2),
                min(width, max(300, central.width() - 24)),
                min(height, max(300, central.height() - 24)),
            )
            overlay.done.connect(self._save_gemini_key)
            self._overlay = overlay
            self._win._ready = False
            self._ui._ready = False
            self._win._lbl_hud_status.setText("● SETUP REQUIRED — GEMINI API KEY")
            self._win._lbl_hud_status.setStyleSheet("color: #d7bd7b;")
            overlay.show()
            overlay.raise_()
            overlay._key_field.setFocus()
        except Exception as exc:
            self._win._lbl_hud_status.setText("● SETUP ERROR — GEMINI KEY WINDOW UNAVAILABLE")
            self._win._lbl_hud_status.setStyleSheet("color: #e97869;")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self._win,
                "JARVIS Gemini setup",
                "The Gemini API-key form could not be opened. The Hologram HUD will remain open; "
                "the legacy UI will not be launched.\n\n"
                f"Details: {type(exc).__name__}: {exc}",
            )

    @pyqtSlot(object)
    def _save_gemini_key(self, payload: object) -> None:
        key = str(payload.get("gemini_api_key", "") if isinstance(payload, dict) else "").strip()
        if not key:
            if self._overlay is not None:
                self._overlay._error_label.setText("Enter a replacement Gemini API key to continue.")
                self._overlay._error_label.show()
                self._overlay._key_field.setFocus()
            return
        if len(key) <= 15:
            if self._overlay is not None:
                self._overlay._error_label.setText(
                    "This key is too short to be a valid Gemini API key. "
                    "Check the full key and try again."
                )
                self._overlay._error_label.show()
                self._overlay._key_field.setFocus()
            return
        try:
            # Use the shared config manager so the key is written to the same
            # config/api_keys.json that JarvisLive reads, preserving other settings.
            from memory.config_manager import save_api_keys
            save_api_keys(key)
        except Exception as exc:
            if self._overlay is not None:
                self._overlay._error_label.setText(
                    f"Could not save the API key ({type(exc).__name__}). Check file permissions and retry."
                )
                self._overlay._error_label.show()
            return

        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        self._win._lbl_hud_status.setText("● GEMINI KEY SAVED — CHECKING OWNER SECURITY")
        self._win._lbl_hud_status.setStyleSheet("color: #71d4c2;")
        QTimer.singleShot(0, self._show_owner_pin_setup_if_needed)

    @pyqtSlot()
    def _show_owner_pin_setup_if_needed(self) -> None:
        if not self._api_configured():
            self.show_gemini_setup()
            return
        try:
            auth = getattr(self._win, "_auth_manager", None)
            if auth is None:
                from core.security import get_auth_manager
                auth = get_auth_manager()
            if auth.is_pin_enrolled():
                self._mark_ready()
                return
        except Exception as exc:
            self._win._lbl_hud_status.setText("● SETUP ERROR — OWNER SECURITY UNAVAILABLE")
            self._win._lbl_hud_status.setStyleSheet("color: #e97869;")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self._win,
                "JARVIS owner security",
                "Owner security could not be initialized. JARVIS will not start without "
                "the existing PIN setup. The Hologram HUD remains active.\n\n"
                f"Details: {type(exc).__name__}: {exc}",
            )
            return
        self._show_owner_pin_setup(auth)

    def _show_owner_pin_setup(self, auth) -> None:
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QFormLayout, QCheckBox, QMessageBox,
            QLabel, QLineEdit, QPushButton,
        )

        dialog = QDialog(self._win)
        dialog.setWindowTitle("JARVIS — Privacy & Owner Security")
        dialog.setMinimumWidth(470)
        dialog.setModal(True)
        dialog.setStyleSheet("""
            QDialog { background: #080e12; color: #c8d9d5; }
            QLabel { color: #c8d9d5; }
            QLineEdit { color: #edf3e8; background: #151f22; padding: 9px;
                        border: 1px solid #34464a; border-radius: 5px; }
            QPushButton { padding: 9px 14px; border-radius: 5px; }
            QCheckBox { color: #9aafaa; spacing: 8px; }
        """)
        layout = QVBoxLayout(dialog)
        heading = QLabel("PRIVACY & OWNER SECURITY")
        heading.setStyleSheet("color: #71d4c2; font-size: 16px; font-weight: bold;")
        layout.addWidget(heading)
        explanation = QLabel(
            "Create your owner PIN/password. It is hashed and stored locally, never sent "
            "to Gemini. This step is required before JARVIS starts. The Hologram HUD stays open."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        pin_edit = QLineEdit(dialog)
        pin_edit.setEchoMode(QLineEdit.EchoMode.Password)
        pin_edit.setPlaceholderText("4–64 characters")
        confirm_edit = QLineEdit(dialog)
        confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
        confirm_edit.setPlaceholderText("Repeat PIN/password")
        form.addRow("Owner PIN / password", pin_edit)
        form.addRow("Confirm PIN / password", confirm_edit)
        layout.addLayout(form)

        voice_check = QCheckBox("Enroll my voice after JARVIS starts (optional)", dialog)
        voice_check.setToolTip("Voice ID enrollment begins after the live assistant is initialized.")
        layout.addWidget(voice_check)

        save_button = QPushButton("SAVE PIN & CONTINUE", dialog)
        save_button.setStyleSheet("background: #71d4c2; color: #061018; font-weight: bold;")
        layout.addWidget(save_button)

        def save_pin() -> None:
            pin = pin_edit.text()
            confirm = confirm_edit.text()
            if not 4 <= len(pin) <= 64:
                QMessageBox.warning(dialog, "Invalid PIN", "Use 4–64 characters for the PIN/password.")
                return
            if pin != confirm:
                QMessageBox.warning(dialog, "Does not match", "The two PIN/password entries do not match.")
                return
            try:
                auth.set_master_pin(pin)
            except Exception as exc:
                QMessageBox.critical(
                    dialog, "Setup failed",
                    f"Owner PIN could not be saved: {type(exc).__name__}: {exc}",
                )
                return
            pin_edit.clear()
            confirm_edit.clear()
            self._pending_voice_enrollment = voice_check.isChecked()
            dialog.accept()

        save_button.clicked.connect(save_pin)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._mark_ready()
            if self._pending_voice_enrollment:
                QTimer.singleShot(500, self._try_pending_voice_enrollment)
        else:
            self._win._lbl_hud_status.setText("● SETUP INCOMPLETE — OWNER PIN REQUIRED")
            self._win._lbl_hud_status.setStyleSheet("color: #d7bd7b;")

    def _mark_ready(self) -> None:
        self._win._ready = True
        self._ui._ready = True
        self._win._lbl_hud_status.setText("● SYSTEM STANDBY")
        self._win._lbl_hud_status.setStyleSheet("color: #00e5ff;")

    def _try_pending_voice_enrollment(self, attempt: int = 0) -> None:
        if not self._pending_voice_enrollment:
            return
        callback = getattr(self._ui, "on_voice_id_action", None)
        if callable(callback):
            self._pending_voice_enrollment = False
            try:
                result = callback("enroll_owner")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self._win,
                    "Voice ID enrollment",
                    str(result or "Voice ID enrollment started.")
                    + "\n\nIf secure live-speaker verification is unavailable, "
                      "JARVIS will fall back to your PIN/password.",
                )
            except Exception as exc:
                self._win._lbl_hud_status.setText("● VOICE ID SETUP FAILED — PIN REMAINS ACTIVE")
                self._win._lbl_hud_status.setStyleSheet("color: #d7bd7b;")
                self.write_log(f"Voice ID enrollment could not start: {type(exc).__name__}")
            return
        if attempt < 40:
            QTimer.singleShot(250, lambda: self._try_pending_voice_enrollment(attempt + 1))
        else:
            self._pending_voice_enrollment = False
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self._win,
                "Voice ID enrollment",
                "JARVIS is running with PIN protection. You can retry Voice ID enrollment "
                "from the Security controls.",
            )

    def write_log(self, text: str) -> None:
        print(f"[HUDSetup] {text}")


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
        self._ready = False
        self._win._ready = False
        self._setup_controller = _HudSetupController(self, self._win)
        self._win.sig_mode_changed.connect(
            lambda: self.on_voice_change() if callable(self.on_voice_change) else None
        )
        QTimer.singleShot(0, self._setup_controller.start)

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
            failsoft.suppress('ui.hud_main:HologramHUDUI.set_audio_level')

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
        """Wait until the HUD's Gemini-key and owner-PIN setup is complete."""
        while True:
            if stop_event is not None and stop_event.is_set():
                return False
            try:
                if self._win._ready:
                    return True
                if stop_event is not None:
                    stop_event.wait(0.1)
                else:
                    time.sleep(0.1)
            except RuntimeError:
                return False

    def prompt_reconfig(self):
        """Request key re-entry inside the existing HUD, never by swapping UI."""
        try:
            self._win._ready = False
            self._ready = False
            self._win.sig_setup_requested.emit()
        except RuntimeError:
            pass

    def request_close(self):
        try:
            self._win.close()
        except Exception:
            failsoft.suppress('ui.hud_main:HologramHUDUI.request_close')
