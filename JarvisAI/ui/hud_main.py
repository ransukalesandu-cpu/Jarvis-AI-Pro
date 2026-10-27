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

from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal, QTimer, QSettings, QUrl, QEvent
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGraphicsBlurEffect, QCheckBox, QStackedWidget,
    QTextBrowser, QSizePolicy
)

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    _WEB_ENGINE_AVAILABLE = True
except Exception:
    QWebEngineView = None
    QWebEngineSettings = None
    _WEB_ENGINE_AVAILABLE = False

from urllib.parse import urlparse
import html as _html

from audio.visualizer_bridge import get_visualizer_bridge, VisualizerBridge
from ui.hologram.wireframe_head import NeuralWireframeHead
from ui.hologram.bihansa_hologram import BihansaHologramWidget
from ui.hologram.bihansa_settings import BihansaModeSettings, BihansaSettingsDialog
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




class FloatingTaskCard(QFrame):
    """Draggable glass task card with an embedded JavaScript-capable browser."""

    sig_closed = pyqtSignal(int)

    def __init__(self, task_id: int, title: str, url: str = "",
                 html_content: str = "", parent=None):
        super().__init__(parent)
        self.task_id = int(task_id)
        self.title = str(title or "JARVIS TASK")[:72]
        self._drag_offset = None
        self._collapsed = False
        self.setObjectName("FloatingTaskCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            QFrame#FloatingTaskCard {
                background-color: rgba(4, 17, 29, 226);
                border: 1px solid rgba(66, 234, 255, 205);
                border-radius: 12px;
            }
            QLabel#TaskTitle {
                color: #bffaff; font: bold 10pt "Courier New";
                background: transparent; border: none;
            }
            QPushButton#TaskAction {
                color: #a9f7ff; background: rgba(8, 36, 51, 210);
                border: 1px solid rgba(66, 234, 255, 120);
                border-radius: 5px; min-width: 24px; max-width: 24px;
                min-height: 22px; max-height: 22px; padding: 0;
                font: bold 10pt "Courier New";
            }
            QPushButton#TaskAction:hover {
                color: white; background: rgba(0, 151, 186, 180);
                border-color: #bffaff;
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 7, 8, 8)
        outer.setSpacing(6)

        self._title_bar = QFrame(self)
        self._title_bar.setStyleSheet("background: rgba(4, 17, 29, 245); border: none;")
        bar = QHBoxLayout(self._title_bar)
        bar.setContentsMargins(5, 2, 2, 2)
        bar.setSpacing(6)

        self._title_label = QLabel("◇  " + self.title, self._title_bar)
        self._title_label.setObjectName("TaskTitle")
        self._title_label.setMinimumWidth(0)
        self._title_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        bar.addWidget(self._title_label, 1)

        self._collapse_button = QPushButton("—", self._title_bar)
        self._collapse_button.setObjectName("TaskAction")
        self._collapse_button.setToolTip("Collapse / expand task card")
        self._collapse_button.clicked.connect(self._toggle_collapsed)
        bar.addWidget(self._collapse_button)

        close_button = QPushButton("×", self._title_bar)
        close_button.setObjectName("TaskAction")
        close_button.setToolTip("Close task card")
        close_button.clicked.connect(lambda: self.sig_closed.emit(self.task_id))
        bar.addWidget(close_button)
        outer.addWidget(self._title_bar)

        self._body = QWidget(self)
        self._body.setStyleSheet("background: transparent; border: none;")
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.web_view = None
        if _WEB_ENGINE_AVAILABLE:
            self.web_view = QWebEngineView(self._body)
            self.web_view.setStyleSheet("background: #06111b; border: none;")
            try:
                self.web_view.settings().setAttribute(
                    QWebEngineSettings.WebAttribute.JavascriptEnabled, True
                )
                self.web_view.settings().setAttribute(
                    QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True
                )
            except Exception:
                pass
            if url:
                self.web_view.setUrl(QUrl(url))
            elif html_content:
                self.web_view.setHtml(html_content, QUrl("about:blank"))
            else:
                self.web_view.setHtml(self._empty_html(), QUrl("about:blank"))
            body_layout.addWidget(self.web_view)
        else:
            self.web_view = None
            fallback = QTextBrowser(self._body)
            fallback.setOpenExternalLinks(False)
            fallback.setStyleSheet(
                "QTextBrowser { background: rgba(3, 12, 21, 225); color: #c5faff; "
                "border: none; font: 10pt 'Courier New'; }"
            )
            if html_content:
                fallback.setHtml(html_content)
            elif url:
                fallback.setHtml(
                    "<h3>Embedded browser unavailable</h3><p>Install PyQt6-WebEngine to "
                    "show this task inside JARVIS.</p><p>" + _html.escape(url) + "</p>"
                )
            else:
                fallback.setHtml(self._empty_html())
            body_layout.addWidget(fallback)

        outer.addWidget(self._body, 1)
        self.setMinimumSize(290, 180)
        self._title_bar.installEventFilter(self)
        self._title_label.installEventFilter(self)

    @staticmethod
    def _empty_html() -> str:
        return (
            "<html><body style='background:#06111b;color:#a9f7ff;"
            "font:12px Consolas;padding:18px'>"
            "<h3>JARVIS TASK SPACE</h3><p>Waiting for task content…</p></body></html>"
        )

    def _toggle_collapsed(self):
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        self._collapse_button.setText("□" if self._collapsed else "—")
        self.setFixedHeight(44 if self._collapsed else self._expanded_height())

    def _expanded_height(self) -> int:
        parent = self.parentWidget()
        if parent is None:
            return 260
        return max(190, min(330, int(parent.height() * 0.30)))

    def eventFilter(self, watched, event):
        if watched in (self._title_bar, self._title_label):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return False
            if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    parent = self.parentWidget()
                    if parent is not None:
                        target = event.globalPosition().toPoint() - self._drag_offset
                        local = parent.mapFromGlobal(target)
                        x = max(0, min(local.x(), max(0, parent.width() - self.width())))
                        y = max(56, min(local.y(), max(56, parent.height() - self.height())))
                        self.move(x, y)
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
        return super().eventFilter(watched, event)


class HUDMainWindow(QMainWindow):
    """
    Futuristic Neural Wireframe Hologram HUD Main Window.
    """

    sig_state_changed = pyqtSignal(str)
    sig_mode_changed = pyqtSignal()
    sig_viseme_schedule = pyqtSignal(object, float, float)
    sig_avatar_text = pyqtSignal(str)
    sig_hybrid_telemetry = pyqtSignal(str, float, str, str)
    sig_task_tab_requested = pyqtSignal(str, str, str)

    def __init__(self, bridge: Optional[VisualizerBridge] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS AI PRO — NEURAL HOLOGRAM")
        self.resize(1280, 800)
        self.setMinimumSize(800, 520)
        self._task_cards = {}
        self._task_order = []
        self._next_task_id = 1

        # Dark cyberpunk theme style
        self.setStyleSheet("""
            QMainWindow { background-color: #030911; }
            QLabel { color: #c8d9d5; }
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
        """Build a full-canvas transparent hologram with floating task windows."""
        workspace = QWidget(self)
        workspace.setObjectName("HologramWorkspace")
        workspace.setStyleSheet("""
            QWidget#HologramWorkspace {
                background-color: #030911;
                background-image: radial-gradient(ellipse at center,
                    rgba(3, 38, 56, 0.36) 0%, rgba(3, 14, 25, 0.96) 57%, #02060b 100%);
            }
        """)
        self.setCentralWidget(workspace)
        self._workspace = workspace

        # Background telemetry models remain alive and current; their old side-column
        # layout is replaced by task-oriented mini cards around the central hologram.
        self._panel_brain = HybridBrainPanel(workspace)
        self._panel_security = SecurityPanel(workspace)
        self._panel_memory = MemoryPanel(workspace)
        self._panel_scheduler = SchedulerPanel(workspace)
        self._panel_ring = SystemTelemetryRing(workspace)
        for panel in (self._panel_brain, self._panel_security, self._panel_memory,
                      self._panel_scheduler, self._panel_ring):
            panel.hide()

        # The face stack spans the entire screen, painting only emissive lines.
        self._visualizer_stack = QStackedWidget(workspace)
        self._visualizer_stack.setStyleSheet("background: transparent; border: none;")
        self._visualizer_stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._visualizer_stack.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.wireframe_visualizer = NeuralWireframeHead(self._visualizer_stack)
        self.bihansa_visualizer = BihansaHologramWidget(self._visualizer_stack)
        self._visualizer_stack.addWidget(self.wireframe_visualizer)
        self._visualizer_stack.addWidget(self.bihansa_visualizer)
        self._visualizer_stack.setCurrentWidget(self.wireframe_visualizer)

        # Slim floating control bar; the hologram remains the dominant surface.
        self._hud_topbar = QFrame(workspace)
        self._hud_topbar.setObjectName("HudTopbar")
        self._hud_topbar.setStyleSheet("""
            QFrame#HudTopbar {
                background: rgba(3, 15, 26, 185);
                border: 1px solid rgba(42, 205, 232, 95);
                border-radius: 12px;
            }
            QLabel { color: #82f3ff; background: transparent; border: none; }
            QPushButton {
                color: #a6f7ff; background: rgba(8, 33, 48, 210);
                border: 1px solid rgba(66, 234, 255, 135);
                border-radius: 6px; padding: 6px 10px; font: bold 9pt "Courier New";
            }
            QPushButton:hover { color: white; border-color: #c8fbff; }
            QPushButton:checked { color: #061019; background: #53eaff; }
            QCheckBox { color: #a6f7ff; spacing: 5px; background: transparent; }
        """)
        hdr_layout = QHBoxLayout(self._hud_topbar)
        hdr_layout.setContentsMargins(12, 5, 10, 5)
        hdr_layout.setSpacing(9)

        hdr_title = QLabel("J.A.R.V.I.S  //  NEURAL HOLOGRAM", self._hud_topbar)
        hdr_title.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        hdr_layout.addWidget(hdr_title)
        hdr_layout.addStretch()

        self._lbl_clock = QLabel("--:--:--", self._hud_topbar)
        self._lbl_clock.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        hdr_layout.addWidget(self._lbl_clock)

        self._bihansa_toggle = QPushButton("BIHANSA: OFF", self._hud_topbar)
        self._bihansa_toggle.setCheckable(True)
        self._bihansa_toggle.toggled.connect(self._set_bihansa_enabled)
        hdr_layout.addWidget(self._bihansa_toggle)

        self._bihansa_settings_btn = QPushButton("⚙", self._hud_topbar)
        self._bihansa_settings_btn.setToolTip("Neural face appearance settings")
        self._bihansa_settings_btn.clicked.connect(self._open_bihansa_settings)
        hdr_layout.addWidget(self._bihansa_settings_btn)

        self._lbl_hud_status = QLabel("● NEURAL LINK ONLINE", workspace)
        self._lbl_hud_status.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._lbl_hud_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_hud_status.setStyleSheet(
            "color: #63efff; background: rgba(3, 17, 29, 170); "
            "border: 1px solid rgba(66, 234, 255, 65); border-radius: 10px; padding: 5px 12px;"
        )

        self._lbl_avatar_text = QLabel("", workspace)
        self._lbl_avatar_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_avatar_text.setWordWrap(True)
        self._lbl_avatar_text.setStyleSheet(
            "color: #aaf8ff; font: 10pt 'Courier New'; "
            "background: rgba(3, 17, 29, 190); border: 1px solid rgba(66,234,255,95); "
            "border-radius: 10px; padding: 8px;"
        )
        self._lbl_avatar_text.hide()

        # These controls belong to Bihansa mode only; hidden in JARVIS default mode.
        self._bihansa_effects = QCheckBox("NEURAL EFFECTS", workspace)
        self._bihansa_effects.setChecked(True)
        self._bihansa_voice_reactive = QCheckBox("VOICE REACTIVE", workspace)
        self._bihansa_voice_reactive.setChecked(True)
        self._bihansa_effects.toggled.connect(self.bihansa_visualizer.set_effects_enabled)
        self._bihansa_voice_reactive.toggled.connect(self.bihansa_visualizer.set_voice_reactive)
        self._bihansa_effects.hide()
        self._bihansa_voice_reactive.hide()

        # Keep the visible privacy shield above all task and hologram layers.
        self._lock_banner = QFrame(workspace)
        self._lock_banner.setStyleSheet("""
            QFrame {
                background-color: rgba(100, 5, 20, 235);
                border: 2px solid #ff365f; border-radius: 12px;
            }
        """)
        lb_layout = QVBoxLayout(self._lock_banner)
        lb_text = QLabel("SYSTEM PRIVACY LOCK ENGAGED — MUTED & LOCKED", self._lock_banner)
        lb_text.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        lb_text.setStyleSheet("color: #ffffff; background: transparent; border: none;")
        lb_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lb_layout.addWidget(lb_text)
        self._lock_banner.hide()

        self.sig_task_tab_requested.connect(self._open_task_tab_on_ui)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(500)
        self._layout_hologram_workspace()

    def _layout_hologram_workspace(self):
        """Resize the hologram to the full canvas and lay task cards around its edges."""
        if not hasattr(self, "_workspace"):
            return
        width = max(1, self._workspace.width())
        height = max(1, self._workspace.height())
        self._visualizer_stack.setGeometry(0, 0, width, height)

        top_h = 52
        self._hud_topbar.setGeometry(14, 12, max(420, width - 28), top_h)
        self._hud_topbar.raise_()

        status_w = min(340, max(230, int(width * 0.27)))
        self._lbl_hud_status.setGeometry(
            int((width - status_w) / 2), max(58, height - 43), status_w, 28
        )
        if self._lbl_avatar_text.isVisible():
            text_w = min(760, int(width * 0.62))
            self._lbl_avatar_text.setGeometry(
                int((width - text_w) / 2), max(64, height - 100), text_w, 48
            )

        self._bihansa_effects.adjustSize()
        self._bihansa_voice_reactive.adjustSize()
        if self._bihansa_effects.isVisible():
            self._bihansa_effects.move(24, height - 76)
            self._bihansa_voice_reactive.move(24, height - 48)

        banner_w, banner_h = min(560, width - 48), 100
        self._lock_banner.setGeometry(
            int((width - banner_w) / 2), int((height - banner_h) / 2),
            max(320, banner_w), banner_h
        )

        self._place_task_cards()
        # Face mesh is the front visual layer; its paint is transparent, so task
        # cards remain visible through/around it while click events reach the cards.
        self._visualizer_stack.raise_()
        for overlay in (self._hud_topbar, self._lbl_hud_status):
            overlay.raise_()
        if self._lbl_avatar_text.isVisible():
            self._lbl_avatar_text.raise_()
        if self._lock_banner.isVisible():
            self._lock_banner.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_hologram_workspace()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
            event.accept()
            return
        super().keyPressEvent(event)

    @pyqtSlot(str, str, str)
    def _open_task_tab_on_ui(self, title: str, url: str, html_content: str):
        """Create an embedded task card; all pages stay inside the HUD window."""
        title = " ".join(str(title or "JARVIS TASK").split())[:72] or "JARVIS TASK"
        url = str(url or "").strip()
        html_content = str(html_content or "")

        if url:
            try:
                parsed = urlparse(url)
            except Exception:
                return
            if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
                return
        if not url and not html_content:
            html_content = FloatingTaskCard._empty_html()

        task_id = self._next_task_id
        self._next_task_id += 1
        card = FloatingTaskCard(task_id, title, url, html_content, self._workspace)
        card.sig_closed.connect(self._remove_task_card)
        card_width = max(300, min(440, int(self._workspace.width() * 0.30)))
        card_height = max(190, min(330, int(self._workspace.height() * 0.30)))
        card.resize(card_width, card_height)
        self._task_cards[task_id] = card
        self._task_order.append(task_id)
        self._place_task_cards()
        card.show()
        card.raise_()
        self._visualizer_stack.raise_()
        self._hud_topbar.raise_()
        self._lbl_hud_status.raise_()
        if self._lbl_avatar_text.isVisible():
            self._lbl_avatar_text.raise_()
        if self._lock_banner.isVisible():
            self._lock_banner.raise_()

    def _place_task_cards(self):
        """Arrange mini task windows in a spatial ring, never as a vertical list."""
        if not hasattr(self, "_task_order") or not hasattr(self, "_workspace"):
            return
        width, height = max(1, self._workspace.width()), max(1, self._workspace.height())
        card_width = max(300, min(440, int(width * 0.30)))
        card_height = max(190, min(330, int(height * 0.30)))
        x_left = max(12, int(width * 0.095))
        x_right = max(x_left, width - card_width - int(width * 0.095))
        y_top = max(78, int(height * 0.145))
        y_bottom = max(y_top + 18, height - card_height - int(height * 0.09))
        positions = [
            (x_left, y_top), (x_right, y_top),
            (x_left, y_bottom), (x_right, y_bottom),
            (max(12, int(width * 0.025)), int(height * 0.36)),
            (max(12, width - card_width - int(width * 0.025)), int(height * 0.36)),
        ]
        for index, task_id in enumerate(self._task_order):
            card = self._task_cards.get(task_id)
            if card is None:
                continue
            card.resize(card_width, 44 if card._collapsed else card_height)
            x, y = positions[index % len(positions)]
            offset = 12 * (index // len(positions))
            x = max(0, min(width - card_width, x + offset))
            y = max(58, min(height - card.height(), y + offset))
            card.move(x, y)

    @pyqtSlot(int)
    def _remove_task_card(self, task_id: int):
        card = self._task_cards.pop(int(task_id), None)
        if card is None:
            return
        if int(task_id) in self._task_order:
            self._task_order.remove(int(task_id))
        card.hide()
        card.deleteLater()
        self._place_task_cards()

    def _wire_signals(self):
        """Wire VisualizerBridge signals to UI components."""
        self._bridge.sig_audio_energy.connect(self.wireframe_visualizer.set_audio_energy)
        self._bridge.sig_state_changed.connect(self._on_state_changed)
        self._bridge.sig_auth_state_changed.connect(self._on_auth_state_changed)
        self._bridge.sig_audio_energy.connect(self.bihansa_visualizer.set_audio_energy)
        self.sig_viseme_schedule.connect(self._schedule_visemes)
        self.sig_avatar_text.connect(self._show_avatar_text)
        self.sig_hybrid_telemetry.connect(self._panel_brain.update_telemetry)
        self._bihansa_effects.toggled.connect(
            lambda value: self._settings.setValue("bihansa/effects", value)
            if hasattr(self, "_settings") else None
        )
        self._bihansa_voice_reactive.toggled.connect(
            lambda value: self._settings.setValue("bihansa/voice_reactive", value)
            if hasattr(self, "_settings") else None
        )

    @pyqtSlot(bool)
    def _set_bihansa_enabled(self, enabled: bool):
        """Switch only the central visualizer; normal JARVIS remains available."""
        enabled = bool(enabled)
        self._visualizer_stack.setCurrentWidget(
            self.bihansa_visualizer if enabled else self.wireframe_visualizer
        )
        self._bihansa_toggle.setText("BIHANSA: ON" if enabled else "BIHANSA: OFF")
        # Keep BIHANSA-only controls out of the standard JARVIS view.
        self._bihansa_effects.setVisible(enabled)
        self._bihansa_voice_reactive.setVisible(enabled)
        self._layout_hologram_workspace()
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

    def open_task_tab(self, title: str, url: str = "") -> bool:
        """Open a URL inside a draggable mini task card; no external browser is launched."""
        value = str(url or "").strip()
        if not value:
            return False
        try:
            parsed = urlparse(value)
        except Exception:
            return False
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            return False
        self._win.sig_task_tab_requested.emit(str(title or "JARVIS TASK"), value, "")
        return True

    def close_task_tabs(self):
        """Close all mini task cards while leaving the full-screen hologram active."""
        try:
            for task_id in list(self._win._task_order):
                card = self._win._task_cards.get(task_id)
                if card:
                    card.sig_closed.emit(task_id)
        except Exception:
            pass

    def show_content(self, title: str, text: str):
        """Display assistant-generated content as an in-HUD task card instead of console output."""
        content = str(text or "")
        safe = _html.escape(content)
        html_content = (
            "<html><body style='margin:0;background:#06111b;color:#c8faff;"
            "font:12px Consolas,monospace;padding:16px'>"
            "<div style='color:#53eaff;font-weight:bold;margin-bottom:12px'>JARVIS OUTPUT</div>"
            "<pre style='white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.45'>"
            + safe + "</pre></body></html>"
        )
        self._win.sig_task_tab_requested.emit(str(title or "JARVIS OUTPUT"), "", html_content)

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
