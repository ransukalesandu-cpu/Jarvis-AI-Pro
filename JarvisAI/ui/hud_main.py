"""
Main Neural Wireframe Hologram HUD Window Shell for Jarvis AI Pro.

Arranges modular glassmorphism telemetry panels around the central 3D wireframe visualizer.
Binds to real application state (Voice Biometrics, AuthState, Memory, Scheduler, and Hybrid Router).
"""

from __future__ import annotations

import functools
import os
import sys
import time

if sys.platform != "win32" and not os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from dataclasses import replace
from typing import Optional, Callable

from PyQt6.QtCore import (
    Qt, QObject, QEvent, QRect, QTimer, QSettings, QPropertyAnimation, QEasingCurve,
    pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import QFont
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
from ui.dynamic_island import DynamicIsland
from ui.health_strip import HudStatusStrip, HudToast
from ui.task_panels import TaskKind, TaskPanelManager, TaskSpec, TaskState, kind_for_action
from ui.panels.battery_settings import BatteryThresholdsDialog

from core import failsoft, hud_layout
from core.battery_settings import load_thresholds, save_thresholds
from core.media_transport import TransportController
from core.task_sources import TaskSourceRegistry
from core.hologram_theme import VisualPreferences, backdrop_css, palette_for_mode
from core.subsystem_probes import SubsystemProber, default_probes
from core.system_status import (
    AdaptivePerformance,
    BatteryMonitor,
    BatteryReading,
    BatteryThresholds,
    HealthMonitor,
    Notification,
    NotificationCenter,
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
)

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

    Default off. The dashboard card, the rail button and the menu entries change
    the composition of a HUD that is deliberately clean; the engine, the
    ``autonomous_task`` voice tool and the report work without any of them.
    Enable with ``autonomous_ui_enabled`` in the config or
    ``JARVIS_AUTONOMOUS_UI=1``.
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


def _safe_slot(feature: str):
    """Make a Qt slot exception-proof.

    PyQt6 aborts the process when a Python exception escapes a slot invoked from
    the event loop, so every timer/signal handler that touches widgets must
    contain its own failures.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception:
                failsoft.suppress(feature)
                return None

        return wrapper

    return decorator


_SHARED_ISLAND = None
_SHARED_PROBER = None


def _shared_island(palette):
    """One always-on-top pill per process.

    There is exactly one HUD in the application, but tests (and any future
    multi-window preview) would otherwise leave several stray top-level pills
    behind. The pill holds no app state, so sharing it is safe.
    """
    global _SHARED_ISLAND
    if _SHARED_ISLAND is None:
        _SHARED_ISLAND = DynamicIsland(None, palette=palette)
    else:
        _SHARED_ISLAND.set_palette(palette)
    return _SHARED_ISLAND


def _shared_prober():
    """One background probe thread per process, started on first use."""
    global _SHARED_PROBER
    if _SHARED_PROBER is None:
        _SHARED_PROBER = SubsystemProber(default_probes())
        _SHARED_PROBER.start()
    return _SHARED_PROBER


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
    # Emitted from the live loop (any thread) around real tool execution.
    sig_command_started = pyqtSignal(str, str)
    sig_command_finished = pyqtSignal(str, str)

    def __init__(self, bridge: Optional[VisualizerBridge] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS AI PRO — NEURAL WIREFRAME HUD")
        self.resize(1280, 800)
        # The window may now shrink to a laptop-half width: the rail and the
        # dropdown adapt below this size instead of being pinned to constants.
        self.setMinimumSize(860, 620)
        # The adapter clears this until Gemini and owner security setup finish.
        # JarvisLive also checks it when an invalid API key requests reconfiguration.
        self._ready = True

        # Dark cyberpunk theme style. The window paints the same backdrop the
        # hologram clears to, so the face has no visible box around it.
        self.setStyleSheet(
            "QMainWindow, QWidget#JarvisCentral {"
            f" background-color: {backdrop_css()};"
            " }"
            " QLabel { color: #c8d9d5; }"
        )

        self._bridge = bridge or get_visualizer_bridge()
        self._auth_manager = get_auth_manager() if callable(get_auth_manager) else None

        self._privacy_locked = False
        # Settings must exist before the UI builds, because the palette, reduced
        # motion and battery-saver preferences are applied to every renderer.
        self._settings = QSettings("JarvisAI", "JarvisAIPro")
        self._prefs = VisualPreferences.from_settings(self._settings)
        self._palette = self._prefs.scaled_palette()
        self._budget_reason = ""
        self._init_ui()
        self._wire_signals()
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

        self._init_system_status()

    def _init_ui(self):
        # Assigned before anything that references it (the right-hand menu and
        # the dashboard's extra card both need it), but only *built* when the
        # opt-in HUD flag is on: the card, the rail button and the menu entries
        # change the composition of a screen that is meant to stay clean.
        self._panel_agent = (
            AutonomousPanel(self)
            if (AutonomousPanel is not None and _agent_ui_enabled())
            else None
        )
        self._agent_stop_button = None

        central_widget = QWidget(self)
        central_widget.setObjectName("JarvisCentral")
        central_widget.setAutoFillBackground(True)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(6)

        # Minimal top row: remove decorative title/clock; keep one compact menu control.
        top_row = QHBoxLayout()
        # Live subsystem health (mic / speaker / network / AI session). Unavailable
        # subsystems render as hollow rings — never a fabricated green dot.
        self._status_strip = HudStatusStrip(self, self._palette)
        top_row.addWidget(self._status_strip, 0, Qt.AlignmentFlag.AlignVCenter)
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
        # The stage must be see-through: the hologram floats on the HUD, it is
        # not a video panel with a black background.
        for _layer in (self._hologram_stage,):
            _layer.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            _layer.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            _layer.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
            _layer.setStyleSheet("background: transparent;")
        stage_layout = QVBoxLayout(self._hologram_stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(0)

        self._visualizer_stack = QStackedWidget(self._hologram_stage)
        self._visualizer_stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._visualizer_stack.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._visualizer_stack.setStyleSheet("background: transparent;")
        self.wireframe_visualizer = NeuralWireframeHead(self)
        self.bihansa_visualizer = BihansaHologramWidget(self)
        self._visualizer_stack.addWidget(self.wireframe_visualizer)
        self._visualizer_stack.addWidget(self.bihansa_visualizer)
        self._visualizer_stack.setCurrentWidget(self.wireframe_visualizer)
        stage_layout.addWidget(self._visualizer_stack, stretch=1)
        stage_layout.addWidget(self._mini_orb, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._heart_reactor = NeuralHeartReactor(self._hologram_stage)
        self._heart_reactor.raise_()
        # Context-aware task panels live on the same stage, above the conduits.
        # The manager gets the hologram's own rectangle as the blocked region, so
        # no panel can ever land on the face.
        self._task_panels = TaskPanelManager(self._hologram_stage, self._palette)
        self._task_panels.sig_task_action.connect(self._on_task_action)
        self._task_panels.raise_()
        # Music transport. The controller only exposes callbacks when this
        # machine can actually deliver a media key, so the panel grows buttons
        # only when pressing them would do something.
        self._transport = TransportController(on_change=self._on_transport_state)
        #: Set once the user dismisses the now-playing card, so a later command
        #: can bring it back but a sync cannot.
        self._now_playing_dismissed = False
        center_col.addWidget(self._hologram_stage, stretch=1)

        self._lbl_hud_status = QLabel("● SYSTEM STANDBY")
        self._lbl_hud_status.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._lbl_hud_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_hud_status.setStyleSheet(f"color: {self._palette_chrome()};")
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
        self._battery_settings_btn = QPushButton("BATTERY THRESHOLDS")
        self._battery_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._battery_settings_btn.setStyleSheet(
            "QPushButton { color: #ffd7a8; background: #101923; border: 1px solid #4a6070;"
            " padding: 8px 12px; border-radius: 8px; }"
            "QPushButton:hover { color: #ffffff; border-color: #ffb066; }"
        )
        self._battery_settings_btn.setToolTip(
            "Charge levels at which JARVIS warns you. Only fires when the machine "
            "actually reports a battery."
        )
        self._battery_settings_btn.clicked.connect(self._open_battery_settings)
        right_menu_layout.addWidget(self._battery_settings_btn)

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

        # Personalisation controls that do something real. Each one persists.
        self._reduced_motion_box = QCheckBox("Reduce motion (accessibility)")
        self._battery_saver_box = QCheckBox("Battery saver visuals")
        self._charging_effects_box = QCheckBox("Charging effects")
        # Inserted just above the action buttons rather than at a hard index, so
        # adding a button later cannot scatter the preferences through the menu.
        anchor_index = right_menu_layout.indexOf(self._battery_settings_btn)
        for offset, box in enumerate(
            (self._reduced_motion_box, self._battery_saver_box, self._charging_effects_box)
        ):
            box.setStyleSheet("QCheckBox { color: #ffd7a8; spacing: 6px; padding: 4px; }")
            right_menu_layout.insertWidget(anchor_index + offset, box)
        self._charging_effects_box.setToolTip(
            "Only applies when the machine actually reports a battery."
        )
        # Seed the boxes from persisted preferences *before* connecting, so
        # restoring a saved value does not re-enter the apply path mid-build.
        self._reduced_motion_box.setChecked(self._prefs.reduced_motion)
        self._battery_saver_box.setChecked(self._prefs.battery_saver)
        self._charging_effects_box.setChecked(self._prefs.charging_effects)
        self._reduced_motion_box.toggled.connect(self._on_reduced_motion_toggled)
        self._battery_saver_box.toggled.connect(self._on_battery_saver_toggled)
        self._charging_effects_box.toggled.connect(self._on_charging_effects_toggled)

        # In-HUD toast for notifications while the hologram is on screen.
        self._toast = HudToast(central_widget, self._palette)
        self._toast.sig_activated.connect(self._on_toast_activated)
        self._toast.hide()

        self._apply_palette()
        # First sizing pass, now that the rail and dropdown exist.
        self._apply_responsive_chrome()


    def resizeEvent(self, event):
        """Keep floating menus inside the central workspace after window resizes."""
        super().resizeEvent(event)
        # Chrome adapts before the menu is positioned: the dropdown's width is
        # one of the things that decides where it goes.
        self._apply_responsive_chrome()
        if hasattr(self, "_right_menu") and self._right_menu.isVisible():
            self._position_right_menu()
        self._sync_task_blocked_rect()
        if hasattr(self, "_toast") and self._toast.isVisible():
            host = self.centralWidget()
            if host is not None:
                self._toast.move(
                    max(12, (host.width() - self._toast.width()) // 2),
                    max(12, host.height() - self._toast.height() - 18),
                )

    @_safe_slot("ui.hud_main:_on_island_energy")
    def _on_island_energy(self, energy: float) -> None:
        """Mirror real audio energy onto the minimised pill."""
        if hasattr(self, "_island") and self._island.isVisible():
            self._island.set_energy(energy)

    def showEvent(self, event):
        """The stage has real geometry only once shown; re-place the overlays."""
        super().showEvent(event)
        self._sync_task_blocked_rect()

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
        self._right_menu.hide()
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
        self._right_menu.hide()
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
        self._size_right_menu(host.width(), host.height())
        x = hud_layout.dropdown_x(host.width(), self._right_menu.width())
        self._right_menu.move(x, hud_layout.DROPDOWN_TOP)
        self._right_menu.raise_()

    def _size_right_menu(self, window_width: int, window_height: int) -> None:
        """Fit the dropdown to the window instead of pinning it to 300 x 650.

        ``adjustSize`` is not optional here: the dropdown is a free-floating child
        rather than a layout member, so nothing ever gives it a height. Without
        this call it stayed at Qt's 30 px default and opened as a thin empty bar.
        """
        self._right_menu.setFixedWidth(hud_layout.dropdown_width(window_width))
        self._right_menu.setMaximumHeight(hud_layout.dropdown_height(window_height))
        layout = self._right_menu.layout()
        if layout is not None:
            layout.activate()
        self._right_menu.adjustSize()

    def _apply_responsive_chrome(self) -> None:
        """Resize the rails to the window: fixed widths only look right at one size.

        Called from ``resizeEvent`` and once after the UI is built, so the first
        paint already matches the real window size instead of 1280 x 800.
        """
        width, height = self.width(), self.height()
        if getattr(self, "_left_rail", None) is not None:
            rail = hud_layout.rail_width(width)
            if self._left_rail.width() != rail:
                self._left_rail.setFixedWidth(rail)
            size = hud_layout.rail_button_size(width)
            for button in getattr(self, "_left_icon_buttons", ()):
                if button.width() != size:
                    button.setFixedSize(size, size)
        if getattr(self, "_right_menu", None) is not None:
            self._size_right_menu(width, height)
            if self._right_menu.isVisible():
                self._position_right_menu()

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
        self._bridge.sig_audio_energy.connect(self._heart_reactor.set_energy)
        self._bridge.sig_audio_energy.connect(self._task_panels.set_energy)
        self._bridge.sig_audio_energy.connect(self._on_island_energy)
        self.sig_command_started.connect(self._on_command_started)
        self.sig_command_finished.connect(self._on_command_finished)
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
        # Persona drives the shared palette: copper for JARVIS, rose for Bihansa.
        # Voice/persona selection still happens through sig_mode_changed below, so
        # this changes appearance only — it never bypasses auth or Privacy Lock.
        self._prefs = replace(self._prefs, mode="bihansa" if enabled else "jarvis").validated()
        self._palette = self._prefs.scaled_palette()
        self._save_visual_prefs()
        self._apply_palette()
        self._bihansa_toggle.setText("BIHANSA MODE: ON" if enabled else "BIHANSA MODE: OFF")
        # Keep BIHANSA-only controls out of the standard JARVIS view.
        self._bihansa_effects.setVisible(enabled)
        self._bihansa_voice_reactive.setVisible(enabled)
        self._settings.setValue("bihansa/enabled", enabled)
        from memory.config_manager import save_assistant_mode
        save_assistant_mode("bihansa" if enabled else "jarvis")
        self.sig_mode_changed.emit()
        self._lbl_hud_status.setText("✦ BIHANSA NEURAL MODE" if enabled else "● SYSTEM STANDBY")
        self._lbl_hud_status.setStyleSheet(
            "color: #ff75d4;" if enabled else f"color: {self._palette_chrome()};"
        )

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

    # ── battery thresholds ──────────────────────────────────────────────────
    def _open_battery_settings(self):
        """Edit the four persisted warning bands; changes apply immediately."""
        dialog = BatteryThresholdsDialog(self._battery.thresholds, self)
        dialog.sig_saved.connect(self._apply_battery_thresholds)
        dialog.exec()
        return dialog

    @_safe_slot("ui.hud_main:_apply_battery_thresholds")
    def _apply_battery_thresholds(self, thresholds: BatteryThresholds) -> None:
        """Persist new bands and push them into the live monitors.

        The performance tiers follow the same numbers: if low now means 35 %,
        the visual battery saver has to start at 35 % too, otherwise the warning
        and the behaviour would disagree on screen.
        """
        clean = save_thresholds(self._settings, thresholds)
        if hasattr(self, "_battery"):
            self._battery.set_thresholds(clean)
        if hasattr(self, "_performance"):
            self._performance.saver_percent = int(clean.low)
            self._performance.balanced_percent = max(int(clean.low) + 1, int(clean.fifty))
        # Re-evaluate now so the user sees the new bands take effect rather than
        # waiting up to five seconds for the next tick.
        if hasattr(self, "_battery"):
            self._poll_system_status()

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
        if hasattr(self, "_island"):
            self._island.set_state(visual_state.lower())
        if self._privacy_locked:
            return

        if st == "LISTENING":
            self._lbl_hud_status.setText("● LISTENING")
            self._lbl_hud_status.setStyleSheet("color: #8ce6b0;")
        elif st == "THINKING":
            self._lbl_hud_status.setText("◈ THINKING")
            self._lbl_hud_status.setStyleSheet("color: #7c4dff;")
        elif st == "SPEAKING":
            self._lbl_hud_status.setText("● SPEAKING")
            self._lbl_hud_status.setStyleSheet(f"color: {self._palette_chrome()};")
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
            self._lbl_hud_status.setStyleSheet(f"color: {self._palette_chrome()};")
        else:
            # Unknown states are shown explicitly instead of being mislabeled
            # as standby; this keeps the UI honest when new states are added.
            readable_state = st.replace("_", " ")[:32]
            self._lbl_hud_status.setText(f"● {readable_state}")
            self._lbl_hud_status.setStyleSheet(f"color: {self._palette_chrome()};")

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
        if hasattr(self, "_island"):
            self._island.set_state("privacy")
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

    # ── system status: battery, health, adaptive performance, notifications ──
    def _init_system_status(self):
        """Create the Qt-free status engines and the island, then start polling."""
        # One reader for the persisted bands, shared with the settings dialog so
        # the HUD and the editor can never disagree about what was stored.
        thresholds = load_thresholds(self._settings)
        self._battery = BatteryMonitor(thresholds=thresholds)
        self._prober = _shared_prober()
        self._health = HealthMonitor(
            {name: (lambda probe_name=name: self._prober.get(probe_name)) for name in default_probes()}
        )
        self._performance = AdaptivePerformance(
            saver_percent=thresholds.low,
            balanced_percent=thresholds.fifty,
        )
        self._notifications = NotificationCenter()
        self._last_budget_tier = ""

        # Minimised representation. A pure view: it never touches audio or sessions.
        self._island = _shared_island(self._palette)
        for signal, slot in (
            (self._island.sig_restore_requested, self._restore_from_island),
            (self._island.sig_activated, self._on_island_activated),
        ):
            try:
                signal.connect(slot)
            except TypeError:
                # Already connected by an earlier window: the shared pill may be
                # reused after this HUD (and its slot) was destroyed.
                pass
        # The controller (from the autonomous-task work) owns show/hide and the
        # pause/stop/open actions; it adopts the same pill so battery, hologram
        # state and agent progress all land on one floating window.
        self._island_controller = (
            DynamicIslandController(self, island=self._island)
            if DynamicIslandController is not None else None
        )

        # Background producers: reminders and Steam downloads push their own
        # panels. Polled on the same tick as the battery, but only every fourth
        # tick (20 s) — these sources read files, they do not need 5 s freshness.
        self._task_sources = TaskSourceRegistry()
        self._source_tick = 0

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._poll_system_status)
        self._status_timer.start(5000)
        # Probes run in the shared background thread, so this first poll only
        # reads a snapshot — it never blocks or paints mid-frame.
        self._poll_system_status()

    def _palette_chrome(self) -> str:
        """Accent colour for the status text, from the active persona palette."""
        return "#%02x%02x%02x" % self._palette.accent

    @property
    def palette(self):
        """The active persona palette (JARVIS copper / Bihansa pink)."""
        return self._palette

    def preferences(self) -> VisualPreferences:
        return self._prefs

    def _save_visual_prefs(self) -> None:
        """Persist only the visual keys; everything else in settings is untouched."""
        for key, value in (
            ("visual/mode", self._prefs.mode),
            ("visual/glow", self._prefs.glow),
            ("visual/reduced_motion", self._prefs.reduced_motion),
            ("visual/battery_saver", self._prefs.battery_saver),
            ("visual/charging_effects", self._prefs.charging_effects),
        ):
            try:
                self._settings.setValue(key, value)
            except Exception:
                failsoft.suppress("ui.hud_main:_save_visual_prefs")

    def _apply_palette(self) -> None:
        """Push the persona palette into every renderer and piece of chrome."""
        palette = self._palette
        # Each face keeps its own identity: the JARVIS wireframe stays copper and
        # the Bihansa companion stays pink. Everything else (heart, orb, chrome,
        # task panels, island) follows the active persona palette.
        for name, mode in (("wireframe_visualizer", "jarvis"), ("bihansa_visualizer", "bihansa")):
            widget = getattr(self, name, None)
            if widget is not None and hasattr(widget, "set_palette"):
                try:
                    widget.set_palette(palette_for_mode(mode))
                except Exception:
                    failsoft.suppress("ui.hud_main:_apply_palette")
        widgets = [
            getattr(self, name, None)
            for name in (
                "_heart_reactor",
                "_mini_orb",
                "_dashboard",
                "_status_strip",
                "_toast",
                "_task_panels",
            )
        ]
        for widget in [w for w in widgets if w is not None]:
            setter = getattr(widget, "set_palette", None)
            if callable(setter):
                try:
                    setter(palette)
                except Exception:
                    failsoft.suppress("ui.hud_main:_apply_palette")
        if getattr(self, "_island", None) is not None:
            self._island.set_palette(palette)

    @_safe_slot("ui.hud_main:_reload_preferences")
    def _reload_preferences(self) -> None:
        """Re-read persisted preferences and re-apply them everywhere."""
        self._prefs = VisualPreferences.from_settings(
            self._settings, fallback_mode="bihansa" if self._bihansa_toggle.isChecked() else "jarvis"
        )
        self._palette = self._prefs.scaled_palette()
        for widget in (self.wireframe_visualizer, self.bihansa_visualizer, self._mini_orb):
            setter = getattr(widget, "set_reduced_motion", None)
            if callable(setter):
                try:
                    setter(self._prefs.reduced_motion)
                except Exception:
                    failsoft.suppress("ui.hud_main:_reload_preferences")
        self._heart_reactor.set_reduced_motion(self._prefs.reduced_motion)
        self._apply_palette()
        if hasattr(self, "_battery"):
            self._poll_system_status()

    @_safe_slot("ui.hud_main:_on_reduced_motion_toggled")
    def _on_reduced_motion_toggled(self, enabled: bool) -> None:
        self._prefs = replace(self._prefs, reduced_motion=bool(enabled)).validated()
        self._save_visual_prefs()
        self._reload_preferences()

    @_safe_slot("ui.hud_main:_on_battery_saver_toggled")
    def _on_battery_saver_toggled(self, enabled: bool) -> None:
        self._prefs = replace(self._prefs, battery_saver=bool(enabled)).validated()
        self._save_visual_prefs()
        self._reload_preferences()

    @_safe_slot("ui.hud_main:_on_charging_effects_toggled")
    def _on_charging_effects_toggled(self, enabled: bool) -> None:
        self._prefs = replace(self._prefs, charging_effects=bool(enabled)).validated()
        self._save_visual_prefs()
        self._poll_system_status()

    @_safe_slot("ui.hud_main:_sync_task_blocked_rect")
    def _orb_dock_rect(self) -> QRect:
        """Area occupied by the status orb and the reactor heart, in stage coords."""
        try:
            orb = self._mini_orb
            top_left = orb.mapTo(self._hologram_stage, orb.rect().topLeft())
            centre_x = self._hologram_stage.width() / 2.0
            return QRect(
                int(centre_x - 110),
                int(top_left.y() - 12),
                220,
                int(self._hologram_stage.height() - top_left.y()) + 12,
            )
        except (AttributeError, RuntimeError):
            return QRect()

    def _sync_task_blocked_rect(self) -> None:
        """Tell the task-panel overlay exactly where the hologram sits on the stage."""
        if not hasattr(self, "_task_panels"):
            return
        try:
            visual = self._visualizer_stack.currentWidget()
            face = visual.face_rect() if hasattr(visual, "face_rect") else visual.geometry()
            top_left = visual.mapTo(self._hologram_stage, face.topLeft())
            # The heart's filament anchors on the chin of that same face box.
            face_rect = QRect(top_left.x(), top_left.y(), face.width(), face.height())
            self._heart_reactor.set_face_rect(face_rect)
            # The orb + heart cluster is part of the hologram, so panels must not
            # land on it either. Unioning it with the face keeps the centre
            # column clear and pushes panels to the sides.
            dock = self._orb_dock_rect()
            self._task_panels.set_blocked_rect(face_rect.united(dock) if dock.isValid() else face_rect)
        except Exception:
            failsoft.suppress("ui.hud_main:_sync_task_blocked_rect")

    # -- battery / performance / health polling ------------------------------
    @_safe_slot("ui.hud_main:_poll_system_status")
    def _poll_system_status(self) -> None:
        """One 5 s tick: battery edges, health snapshot, render budget, alerts."""
        events = self._battery.poll()
        reading = self._battery.reading
        self._on_battery_update(reading, events)
        self._refresh_health()
        self._refresh_render_budget(reading)
        self._drain_notifications()
        self._source_tick += 1
        if self._source_tick % 4 == 0:
            self._sync_task_sources()

    # ── background task producers ───────────────────────────────────────────
    @_safe_slot("ui.hud_main:_sync_task_sources")
    def _sync_task_sources(self) -> None:
        """Let reminders/downloads own panels, exactly like a voice command does."""
        registry = getattr(self, "_task_sources", None)
        if registry is None:
            return
        try:
            tasks = registry.scan()
        except Exception:
            failsoft.suppress("ui.hud_main:_sync_task_sources")
            return
        if registry.errors:
            # A producer that failed is *unknown*, not empty. Say so in the log
            # rather than silently pretending there is nothing to show.
            print(f"[JARVIS HUD] task source unavailable: {registry.errors}")
        self._task_panels.sync_sources(tasks)
        self._sync_task_blocked_rect()

    # ── music transport ─────────────────────────────────────────────────────
    def _on_transport_state(self, playing: bool) -> None:
        """Reflect a media key that was actually delivered."""
        if not self._task_panels.has_task("media:now"):
            return
        self._task_panels.update_task("media:now", playing=bool(playing))

    @_safe_slot("ui.hud_main:_dismiss_now_playing")
    def _dismiss_now_playing(self) -> None:
        self._now_playing_dismissed = True
        self._task_panels.close_task("media:now", archive=False)

    def _show_now_playing(self, action_name: str, result: str) -> None:
        """Open the persistent music card for a command that really started playback.

        The card never claims the track is *playing*: the OS media keys are
        fire-and-forget, so there is no state to read. The play/pause glyph is a
        control, and it only flips after a press actually succeeds.
        """
        self._now_playing_dismissed = False
        title = " ".join(str(result or "").split()) or "Media playback"
        fields = {
            "kind": TaskKind.MUSIC,
            "title": title[:80],
            "subtitle": "MEDIA · SYSTEM MEDIA KEYS",
            # Nothing is "running" here: this card is a control surface for
            # playback someone else owns, so it must not sweep a progress bar.
            "state": TaskState.WAITING,
            "progress": None,
            "playing": self._transport.playing,
            "on_dismiss": self._dismiss_now_playing,
        }
        fields.update(self._transport.callbacks())
        if self._task_panels.has_task("media:now"):
            self._task_panels.update_task("media:now", **fields)
        else:
            self._task_panels.open_task(TaskSpec(task_id="media:now", **fields))
        if not self._transport.available():
            # Honest caption: no transport buttons exist on this machine.
            self._task_panels.update_task(
                "media:now", subtitle="MEDIA · CONTROLS UNAVAILABLE ON THIS SYSTEM"
            )
        self._sync_task_blocked_rect()

    @_safe_slot("ui.hud_main:_on_battery_update")
    def _on_battery_update(self, reading: BatteryReading, events) -> None:
        """Feed the *real* battery sample to the visuals; never invent one."""
        available = bool(reading.available and reading.percent is not None)
        percent = reading.percent if available else None
        plugged = bool(reading.plugged) if available else False
        charging_effects = self._prefs.charging_effects
        self._heart_reactor.set_battery(
            available, percent, plugged and charging_effects,
            low_threshold=float(self._battery.thresholds.low),
        )
        self._mini_orb.set_charging(plugged and charging_effects)
        if available:
            suffix = " ⚡" if plugged else ""
            self._island.set_battery_text(f"{percent:.0f}%{suffix}")
        else:
            # No sensor → no number. The island shows nothing rather than a fake.
            self._island.set_battery_text("")

        for event in events or ():
            title, body, priority = {
                "charging": ("Charging", f"Battery {event.percent:.0f}% — charging", PRIORITY_NORMAL),
                "unplugged": ("On battery", f"Battery {event.percent:.0f}% — charger removed", PRIORITY_NORMAL),
                "full": ("Battery full", f"Charged to {event.percent:.0f}%", PRIORITY_LOW),
            }.get(event.kind, (event.kind.title(), event.detail, PRIORITY_NORMAL))
            if event.kind == "threshold":
                priority = PRIORITY_CRITICAL if event.level == "critical" else PRIORITY_HIGH
                title = f"Battery {event.level}"
            self._notifications.push(
                Notification(f"battery:{event.kind}:{event.level}", title, body, priority)
            )

    @_safe_slot("ui.hud_main:_refresh_render_budget")
    def _refresh_render_budget(self, reading: BatteryReading) -> None:
        """Scale particles/glow/frame rate from battery + real CPU load."""
        budget = self._performance.decide(
            reading,
            reduced_motion=self._prefs.reduced_motion,
            battery_saver_enabled=self._prefs.battery_saver,
        )
        glow = budget.glow_scale * max(0.2, self._prefs.glow)
        self.wireframe_visualizer.set_performance_budget(
            budget.frame_interval_ms, budget.particle_scale, budget.glow_scale
        )
        self._mini_orb.set_performance_budget(
            budget.frame_interval_ms, budget.particle_scale, budget.glow_scale
        )
        self._heart_reactor.set_glow(glow)
        self._island.set_reduced_motion(self._prefs.reduced_motion or budget.tier == "saver")
        if budget.tier != self._last_budget_tier:
            self._last_budget_tier = budget.tier
            self._budget_reason = budget.reason

    @_safe_slot("ui.hud_main:_refresh_health")
    def _refresh_health(self) -> None:
        """Apply a real health snapshot to the strip and queue honest alerts."""
        try:
            state, notes = self._health.poll()
        except Exception:
            failsoft.suppress("ui.hud_main:_refresh_health")
            return
        self._status_strip.apply_health(state)
        for note in notes or ():
            self._notifications.push(note)
        # Audio-stream health feeds the island's state so a dead stream is visible.
        stream = state.audio_stream
        if stream.available and not stream.ok:
            self._island.set_state("error")

    @_safe_slot("ui.hud_main:_drain_notifications")
    def _drain_notifications(self) -> None:
        """Show at most one notification per tick, in the right surface."""
        note = self._notifications.pop()
        if note is None:
            return
        if self._island.isVisible():
            self._island.show_notification(note)
            return
        self._toast.show_notification(note)
        host = self.centralWidget()
        if host is not None:
            self._toast.move(
                max(12, (host.width() - self._toast.width()) // 2),
                max(12, host.height() - self._toast.height() - 18),
            )

    @_safe_slot("ui.hud_main:_on_toast_activated")
    def _on_toast_activated(self, source: str) -> None:
        """Clicking a notification goes somewhere real, or nowhere."""
        if source == "battery":
            self._open_dashboard_panel(4)
        elif source in {"microphone", "speaker", "audio_stream"}:
            self._open_dashboard_panel(4)
        elif source == "network":
            self._open_dashboard_panel(0)

    @_safe_slot("ui.hud_main:_on_island_activated")
    def _on_island_activated(self, reason: str) -> None:
        if reason == "settings":
            self._toggle_right_dropdown()
        elif reason == "task":
            self._open_dashboard_panel(3)

    # ── task panels + voice-command feedback ────────────────────────────────
    @_safe_slot("ui.hud_main:_on_task_action")
    def _on_task_action(self, task_id: str, action: str) -> None:
        """Dismiss/close requests coming from a panel's own controls."""
        if action == "dismiss":
            self._task_panels.close_task(task_id)

    def begin_command(self, action_name: str, summary: str = "") -> None:
        """Public, thread-safe: a real tool call has started.

        Emitted from the live loop; Qt queues it onto the UI thread.
        """
        self.sig_command_started.emit(str(action_name or ""), str(summary or ""))

    def finish_command(self, action_name: str, result: str = "") -> None:
        """Public, thread-safe: the same tool call returned (success or failure)."""
        self.sig_command_finished.emit(str(action_name or ""), str(result or ""))

    @pyqtSlot(str, str)
    @_safe_slot("ui.hud_main:_on_command_started")
    def _on_command_started(self, action_name: str, summary: str) -> None:
        action = action_name or "action"
        task_id = f"cmd:{action}"
        kind = kind_for_action(action)
        title = summary.strip() or action.replace("_", " ").title()
        if self._task_panels.has_task(task_id):
            self._task_panels.update_task(
                task_id, state=TaskState.RUNNING, title=title, progress=None, detail=""
            )
        else:
            self._task_panels.open_task(
                TaskSpec(
                    task_id=task_id,
                    kind=kind,
                    title=title,
                    subtitle="VOICE COMMAND",
                    state=TaskState.RUNNING,
                    progress=None,
                )
            )
        self._task_panels.flash(task_id)
        self._sync_task_blocked_rect()

    @pyqtSlot(str, str)
    @_safe_slot("ui.hud_main:_on_command_finished")
    def _on_command_finished(self, action_name: str, result: str) -> None:
        task_id = f"cmd:{action_name or 'action'}"
        if not self._task_panels.has_task(task_id):
            return
        ok = self._result_ok(result)
        self._task_panels.update_task(
            task_id,
            state=TaskState.COMPLETED if ok else TaskState.FAILED,
            progress=1.0 if ok else None,
            detail=result[:120],
        )
        if not ok:
            self._notifications.push(
                Notification(
                    f"command:{action_name}",
                    f"{str(action_name).replace('_', ' ').title()} did not complete",
                    result[:120] or "The action reported no result.",
                    PRIORITY_HIGH,
                )
            )
        if ok and kind_for_action(action_name) == TaskKind.MUSIC:
            # Real playback was requested, so offer real transport controls for
            # whatever the OS is now playing.
            self._show_now_playing(str(action_name or ""), result)
        # Terminal panels shrink but stay dismissible, then archive themselves.
        # The timer is parented to this window, so a closed HUD cancels it
        # instead of firing into deleted widgets.
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda tid=task_id: self._archive_task(tid))
        timer.start(9000)

    def _archive_task(self, task_id: str) -> None:
        """Retire a finished panel. Never raises: this runs from a Qt timer."""
        try:
            panel = self._task_panels.panel(task_id)
            if panel is not None and panel.spec.is_terminal:
                self._task_panels.close_task(task_id)
        except (RuntimeError, AttributeError):
            failsoft.suppress("ui.hud_main:_archive_task")

    @staticmethod
    def _result_ok(result: str) -> bool:
        """Did the tool actually succeed? Derived from its own returned text.

        Actions return a user-facing confirmation on success and an explanation
        containing an error word on failure. Anything we cannot classify counts
        as *not confirmed*, so the HUD never claims success it cannot verify.
        """
        text = str(result or "").strip().lower()
        if not text:
            return False
        failures = (
            "error", "failed", "failure", "could not", "cannot", "can't", "unable",
            "denied", "blocked", "not available", "no permission", "timed out",
            "not found", "invalid", "refused", "unsupported",
        )
        return not any(marker in text for marker in failures)

    # ── window state: island minimise, escape, close ────────────────────────
    def _enter_island_mode(self) -> None:
        """Replace the minimised window with the Dynamic Island pill."""
        self._island.set_palette(self._palette)
        self._island.set_state(self._bridge.current_state.lower())
        self._island.set_energy(self._bridge.current_energy)
        live = self._task_panels.specs() if hasattr(self, "_task_panels") else []
        running = [spec for spec in live if spec.state == TaskState.RUNNING]
        if running:
            self._island.set_task_summary(running[0].title)
        else:
            self._island.set_task_summary("")
        # The controller places the pill (top-centre, clamped to the screen) and
        # refreshes the autonomous-task summary.
        controller = getattr(self, "_island_controller", None)
        if controller is not None:
            controller.sync(True)
        else:  # pragma: no cover - only when the island module failed to import
            self._island.move_to_default_position()
            self._island.show()
            self._island.raise_()
        # Nothing is stopped: the poll timers, the bridge and the live session all
        # keep running. Only the big window goes away.
        self.hide()

    @pyqtSlot()
    @_safe_slot("ui.hud_main:_restore_from_island")
    def _restore_from_island(self) -> None:
        self._island.clear_notification()
        controller = getattr(self, "_island_controller", None)
        if controller is not None:
            controller.restore_window()
            return
        self._island.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event):
        """Minimising swaps the HUD for the Dynamic Island; restoring swaps back."""
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowStateChange:
            return
        controller = getattr(self, "_island_controller", None)
        island = getattr(self, "_island", None)
        if controller is None or island is None:
            return
        try:
            if self.isMinimized():
                if not island.isVisible():
                    self._enter_island_mode()
            elif island.isVisible():
                island.hide()
        except Exception:
            failsoft.suppress("ui.hud_main:changeEvent")

    def keyPressEvent(self, event):
        """Escape closes whatever overlay is open, innermost first."""
        if event.key() == Qt.Key.Key_Escape:
            if self._right_menu.isVisible():
                self._right_menu.hide()
                return
            if self._toast.isVisible():
                self._toast.dismiss()
                return
            if hasattr(self, "_island") and self._island.isVisible() and self._island._expanded:
                self._island.collapse()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        """Stop this window's timers and the pill. The probe thread is shared."""
        try:
            self._status_timer.stop()
            self._poll_timer.stop()
        except Exception:
            failsoft.suppress("ui.hud_main:HUDMainWindow.closeEvent")
        controller = getattr(self, "_island_controller", None)
        if controller is not None:
            try:
                controller.shutdown()
            except Exception:
                failsoft.suppress("ui.hud_main:closeEvent")
        super().closeEvent(event)

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

    def begin_command(self, action_name: str, summary: str = ""):
        """Live loop → HUD: a real tool call started (thread-safe via signals)."""
        try:
            self._win.begin_command(action_name, summary)
        except RuntimeError:
            pass

    def finish_command(self, action_name: str, result: str = ""):
        """Live loop → HUD: that tool call returned; shown truthfully."""
        try:
            self._win.finish_command(action_name, result)
        except RuntimeError:
            pass

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
