"""Modern bento-grid home surface for the JARVIS desktop HUD.

The traditional avatar visualizers remain available on a separate page; the
home dashboard uses a compact, audio-reactive orb so telemetry gets the space.
"""
from __future__ import annotations

import math


def dashboard_grid_positions(width: int, card_count: int = 5) -> tuple[tuple[int, int], ...]:
    """Return stable card positions for wide two-column and compact one-column layouts."""
    count = max(0, int(card_count))
    columns = 1 if int(width) <= 760 else 2
    return tuple((index // columns, index % columns) for index in range(count))

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)


class FloatingHolographicOrb(QWidget):
    """A small painter-based holographic orb with audio-reactive breathing."""

    def __init__(self, parent: QWidget | None = None, size_px: int = 144):
        super().__init__(parent)
        self.setObjectName("FloatingHolographicOrb")
        diameter = max(28, min(156, int(size_px)))
        self.setFixedSize(diameter, diameter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._state = "IDLE"
        self._energy = 0.0
        self._phase = 0.0
        self._bihansa = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(32)

    def set_state(self, state: str) -> None:
        self._state = str(state or "IDLE").upper()
        self.update()

    def set_audio_energy(self, energy: float) -> None:
        try:
            self._energy = max(0.0, min(1.0, float(energy)))
        except (TypeError, ValueError):
            self._energy = 0.0

    def set_bihansa_mode(self, enabled: bool) -> None:
        self._bihansa = bool(enabled)
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + (1.8 + self._energy * 3.5)) % 360.0
        self._energy *= 0.91
        self.update()

    def _accent(self) -> QColor:
        if self._state in {"PRIVACY_LOCK", "LOCKDOWN"}:
            return QColor("#ff456b")
        if self._bihansa:
            return QColor("#ff78d2")
        if self._state == "LISTENING":
            return QColor("#6dffbb")
        if self._state == "THINKING":
            return QColor("#ad8bff")
        if self._state == "SPEAKING":
            return QColor("#72f6ff")
        return QColor("#68d9ff")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        size = min(w, h)
        accent = self._accent()
        breathing = 1.0 + 0.045 * math.sin(math.radians(self._phase * 2.0)) + self._energy * 0.12
        radius = size * 0.265 * breathing

        # Diffuse halo and luminous center.
        halo = QRadialGradient(QPointF(cx, cy), size * 0.48)
        halo.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 52))
        halo.setColorAt(0.46, QColor(accent.red(), accent.green(), accent.blue(), 16))
        halo.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QRectF(cx - size * 0.48, cy - size * 0.48, size * 0.96, size * 0.96))

        # Three orbit rings. Their angles move at different speeds for depth.
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._phase)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        ring_pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 145), 1.15)
        ring_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(ring_pen)
        painter.drawEllipse(QRectF(-radius * 1.55, -radius * 0.66, radius * 3.1, radius * 1.32))
        painter.rotate(62.0)
        ring_pen.setColor(QColor(accent.red(), accent.green(), accent.blue(), 100))
        ring_pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(ring_pen)
        painter.drawEllipse(QRectF(-radius * 1.3, -radius * 0.84, radius * 2.6, radius * 1.68))
        painter.restore()

        core = QRadialGradient(QPointF(cx - radius * 0.28, cy - radius * 0.34), radius * 1.65)
        core.setColorAt(0.0, QColor("#ffffff"))
        core.setColorAt(0.16, QColor(accent.red(), accent.green(), accent.blue(), 245))
        core.setColorAt(0.52, QColor(accent.red(), accent.green(), accent.blue(), 170))
        core.setColorAt(0.82, QColor(22, 53, 75, 225))
        core.setColorAt(1.0, QColor(6, 13, 28, 235))
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 220), 1.0))
        painter.setBrush(core)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        # A bright specular point and subtle ring around the core.
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 180), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - radius * 1.16, cy - radius * 1.16, radius * 2.32, radius * 2.32))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(cx - radius * 0.39, cy - radius * 0.48, radius * 0.16, radius * 0.16))
        painter.end()


class MagneticCard(QFrame):
    """Layout-safe hover card with cursor-directed glow and smooth spring-back."""

    def __init__(self, content: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("MagneticCard")
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setStyleSheet("""
            QFrame#MagneticCard {
                background: rgba(14, 24, 34, 225);
                border: 1px solid rgba(94, 173, 199, 0.30);
                border-radius: 18px;
            }
            QFrame#MagneticCard:hover {
                border: 1px solid rgba(104, 217, 255, 0.62);
                background: rgba(17, 31, 43, 238);
            }
        """)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(15)
        self._shadow.setOffset(0, 4)
        self._shadow.setColor(QColor(34, 159, 205, 52))
        self.setGraphicsEffect(self._shadow)
        self._shadow_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._shadow_anim.setDuration(210)
        self._shadow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._offset_anim = QPropertyAnimation(self._shadow, b"yOffset", self)
        self._offset_anim.setDuration(210)
        self._offset_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._home_y = 4.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)
        content.setParent(self)
        content.setStyleSheet(
            content.styleSheet()
            + f"\nQFrame#{content.objectName()} {{ background: transparent; border: none; border-radius: 14px; }}"
        )
        layout.addWidget(content)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._shadow_anim.stop()
        self._shadow_anim.setStartValue(self._shadow.blurRadius())
        self._shadow_anim.setEndValue(27.0)
        self._shadow_anim.start()
        self._offset_anim.stop()
        self._offset_anim.setStartValue(self._shadow.yOffset())
        self._offset_anim.setEndValue(1.0)
        self._offset_anim.start()
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        # Moving the light toward the pointer gives the card a subtle magnetic pull
        # without moving QWidget geometry (which would fight the layout manager).
        cx = max(1.0, self.width() / 2.0)
        cy = max(1.0, self.height() / 2.0)
        px = max(-1.0, min(1.0, (event.position().x() - cx) / cx))
        py = max(-1.0, min(1.0, (event.position().y() - cy) / cy))
        self._shadow.setOffset(px * 3.0, 2.0 + py * 2.0)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._shadow_anim.stop()
        self._shadow_anim.setStartValue(self._shadow.blurRadius())
        self._shadow_anim.setEndValue(15.0)
        self._shadow_anim.start()
        self._offset_anim.stop()
        self._offset_anim.setStartValue(self._shadow.yOffset())
        self._offset_anim.setEndValue(self._home_y)
        self._offset_anim.start()
        super().leaveEvent(event)


class SkeletonLoader(QFrame):
    """Animated loading skeleton used until first live HUD state arrives."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DashboardSkeleton")
        self.setMinimumHeight(54)
        self.setStyleSheet("""
            QFrame#DashboardSkeleton { background: transparent; border: none; }
            QFrame#DashboardSkeleton QLabel {
                background: #1d303a; border: none; border-radius: 5px; color: transparent;
            }
        """)
        self._phase = 0
        self._bars: list[QFrame] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for width in (180, 118, 150):
            bar = QFrame(self)
            bar.setFixedHeight(8)
            bar.setMaximumWidth(width)
            bar.setStyleSheet("background: #1d303a; border-radius: 4px; border: none;")
            self._bars.append(bar)
            layout.addWidget(bar)
        layout.addStretch(1)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pulse)
        self._timer.start(160)

    def _pulse(self):
        self._phase = (self._phase + 1) % 4
        alpha = (110, 145, 185, 145)[self._phase]
        color = f"rgba(104, 217, 255, {alpha})"
        for index, bar in enumerate(self._bars):
            local = (self._phase + index) % 4
            a = max(65, alpha - local * 16)
            bar.setStyleSheet(f"background: rgba(104, 217, 255, {a}); border-radius: 4px; border: none;")
        self.update()

    def stop(self):
        self._timer.stop()


class ModernDashboard(QWidget):
    """Responsive bento home dashboard: compact orb, telemetry cards, and actions."""

    avatar_requested = pyqtSignal()
    refresh_requested = pyqtSignal()

    def __init__(
        self,
        panels: tuple[QWidget, QWidget, QWidget, QWidget, QWidget],
        parent: QWidget | None = None,
        extra_panel: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("ModernDashboard")
        self._panels = panels
        # Optional sixth surface (the autonomous task view). Kept separate from
        # ``_cards`` so the existing five telemetry cards keep their positions.
        self._extra_panel = extra_panel
        self._extra_card: MagneticCard | None = None
        self._loaded = False
        self._state = "IDLE"
        self.setStyleSheet("""
            QWidget#ModernDashboard { background: transparent; color: #d9e7ec; }
            QLabel#Eyebrow { color: #68d9ff; font: 700 9pt 'Consolas'; letter-spacing: 2px; }
            QLabel#HeroTitle { color: #f0f7ff; font: 700 24pt 'Aptos Display'; }
            QLabel#HeroSub { color: #8caab9; font: 10pt 'Aptos'; }
            QLabel#SectionTitle { color: #a7c0cc; font: 700 9pt 'Consolas'; letter-spacing: 1px; }
            QLabel#StatusChip {
                color: #8fffd6; background: rgba(49, 208, 158, 22);
                border: 1px solid rgba(49, 208, 158, 75); border-radius: 9px;
                padding: 6px 10px; font: 700 8pt 'Consolas';
            }
            QFrame#HeroSurface {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba(16, 34, 47, 245), stop:0.52 rgba(11, 22, 35, 242),
                    stop:1 rgba(28, 22, 49, 235));
                border: 1px solid rgba(104, 217, 255, 0.24); border-radius: 22px;
            }
            QFrame#QuickSurface {
                background: rgba(15, 25, 36, 225); border: 1px solid rgba(94, 173, 199, 0.30);
                border-radius: 18px;
            }
            QPushButton#AccentButton {
                color: #07141d; background: #80e7ff; border: 0; border-radius: 10px;
                padding: 10px 15px; font: 700 9pt 'Consolas';
            }
            QPushButton#AccentButton:hover { background: #c4f4ff; }
            QPushButton#GhostButton {
                color: #c7e0e9; background: rgba(104,217,255,0.06);
                border: 1px solid rgba(104,217,255,0.30); border-radius: 10px;
                padding: 9px 12px; font: 700 8pt 'Consolas';
            }
            QPushButton#GhostButton:hover { background: rgba(104,217,255,0.16); border-color: #80e7ff; }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        scroll = QScrollArea(self)
        self._scroll = scroll
        scroll.setObjectName("DashboardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea#DashboardScroll { background: transparent; border: none; }
            QScrollBar:vertical { background: rgba(11,18,27,120); width: 7px; margin: 2px; border-radius: 3px; }
            QScrollBar::handle:vertical { background: rgba(104,217,255,100); border-radius: 3px; min-height: 30px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("DashboardContent")
        content.setStyleSheet("QWidget#DashboardContent { background: transparent; }")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(3, 5, 11, 8)
        content_layout.setSpacing(16)

        hero = QFrame(content)
        hero.setObjectName("HeroSurface")
        hero_layout = QHBoxLayout(hero)
        self._hero_layout = hero_layout
        hero_layout.setContentsMargins(24, 18, 20, 18)
        hero_layout.setSpacing(12)

        copy = QVBoxLayout()
        copy.setSpacing(5)
        eyebrow = QLabel("PERSONAL INTELLIGENCE  /  LIVE")
        eyebrow.setObjectName("Eyebrow")
        copy.addWidget(eyebrow)
        title = QLabel("Your command center.")
        title.setObjectName("HeroTitle")
        title.setWordWrap(True)
        copy.addWidget(title)
        subtitle = QLabel("Focus on what matters. JARVIS keeps your system and next steps in view.")
        subtitle.setObjectName("HeroSub")
        subtitle.setWordWrap(True)
        copy.addWidget(subtitle)

        status_row = QHBoxLayout()
        self.status_chip = QLabel("● SYSTEM STANDBY")
        self.status_chip.setObjectName("StatusChip")
        self.status_chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        status_row.addWidget(self.status_chip)
        status_row.addStretch(1)
        copy.addLayout(status_row)
        hero_layout.addLayout(copy, stretch=1)

        self.orb = FloatingHolographicOrb(hero)
        hero_layout.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignCenter)

        hero_right = QVBoxLayout()
        hero_right.setSpacing(8)
        hero_right.addStretch(1)
        self.btn_avatar = QPushButton("OPEN AVATAR  ↗", hero)
        self.btn_avatar.setObjectName("GhostButton")
        self.btn_avatar.clicked.connect(self.avatar_requested.emit)
        self.btn_avatar.setCursor(Qt.CursorShape.PointingHandCursor)
        hero_right.addWidget(self.btn_avatar, alignment=Qt.AlignmentFlag.AlignRight)
        label = QLabel("VOICE / VISUALS")
        label.setStyleSheet("color: #587f90; font: 700 8pt 'Consolas';")
        label.setAlignment(Qt.AlignmentFlag.AlignRight)
        hero_right.addWidget(label)
        hero_right.addStretch(1)
        hero_layout.addLayout(hero_right)

        content_layout.addWidget(hero)

        section = QHBoxLayout()
        section.setContentsMargins(3, 0, 0, 0)
        section_title = QLabel("SYSTEM OVERVIEW")
        section_title.setObjectName("SectionTitle")
        section.addWidget(section_title)
        section.addStretch(1)
        small_meta = QLabel("LIVE TELEMETRY  ·  SECURE BY DESIGN")
        small_meta.setStyleSheet("color: #547382; font: 8pt 'Consolas';")
        section.addWidget(small_meta)
        content_layout.addLayout(section)

        grid = QGridLayout()
        self._grid = grid
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._cards: list[MagneticCard] = []
        # Keep telemetry components intact; the dashboard simply rearranges them.
        positions = dashboard_grid_positions(1000, len(panels))
        for panel, position in zip(panels, positions):
            card = MagneticCard(panel, content)
            card.setMinimumWidth(0)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self._cards.append(card)
            grid.addWidget(card, position[0], position[1])
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        quick = QFrame(content)
        quick.setObjectName("QuickSurface")
        quick.setMinimumWidth(0)
        quick_layout = QVBoxLayout(quick)
        quick_layout.setContentsMargins(18, 15, 18, 16)
        quick_layout.setSpacing(12)
        q_title = QLabel("QUICK ACTIONS")
        q_title.setObjectName("SectionTitle")
        quick_layout.addWidget(q_title)

        self._skeleton = SkeletonLoader(quick)
        quick_layout.addWidget(self._skeleton)

        self._ready_group = QWidget(quick)
        ready_layout = QVBoxLayout(self._ready_group)
        ready_layout.setContentsMargins(0, 0, 0, 0)
        ready_layout.setSpacing(8)
        ready_note = QLabel("Your workspace is ready.")
        ready_note.setStyleSheet("color: #8caab9; font: 10pt 'Aptos';")
        ready_layout.addWidget(ready_note)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.btn_refresh = QPushButton("REFRESH DATA", quick)
        self.btn_refresh.setObjectName("AccentButton")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        action_row.addWidget(self.btn_refresh)
        action_row.addStretch(1)
        ready_layout.addLayout(action_row)
        quick_layout.addWidget(self._ready_group)
        self._ready_group.hide()
        self._quick_surface = quick
        grid.addWidget(quick, 2, 1)

        if extra_panel is not None:
            extra_card = MagneticCard(extra_panel, content)
            extra_card.setMinimumWidth(0)
            extra_card.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Preferred)
            grid.addWidget(extra_card, 3, 0, 1, 2)
            self._extra_card = extra_card

        content_layout.addLayout(grid)
        content_layout.addStretch(1)
        scroll.setWidget(content)

        # Loading begins when this separate page is actually opened, not while
        # JARVIS is sitting on the hologram-only home screen.
        self._loading_timer = QTimer(self)
        self._loading_timer.setSingleShot(True)
        self._loading_timer.timeout.connect(self.finish_loading)
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.setInterval(70)
        self._layout_timer.timeout.connect(self._apply_responsive_layout)
        self._compact_layout = None
        self._apply_responsive_layout()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Debounce grid rearrangement while the user resizes the HUD."""
        super().resizeEvent(event)
        if hasattr(self, "_layout_timer"):
            self._layout_timer.start()

    def _apply_responsive_layout(self) -> None:
        """Reflow cards and trim hero spacing without changing any live panel."""
        width = max(1, self._scroll.viewport().width())
        compact = width <= 760
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        positions = dashboard_grid_positions(width, len(self._cards))
        for card in self._cards:
            self._grid.removeWidget(card)
        for card, (row, column) in zip(self._cards, positions):
            self._grid.addWidget(card, row, column)
        next_row = len(self._cards) if compact else (len(self._cards) + 1) // 2
        self._grid.removeWidget(self._quick_surface)
        if compact:
            self._grid.addWidget(self._quick_surface, next_row, 0, 1, 1)
            self._grid.setColumnStretch(1, 0)
            self._grid.setHorizontalSpacing(8)
            self._grid.setVerticalSpacing(10)
            self._hero_layout.setContentsMargins(14, 12, 14, 12)
            self._hero_layout.setSpacing(6)
            self.orb.setFixedSize(64, 64)
            if self._extra_card is not None:
                self._grid.removeWidget(self._extra_card)
                self._grid.addWidget(self._extra_card, next_row + 1, 0, 1, 1)
        else:
            self._grid.addWidget(self._quick_surface, next_row, 1)
            self._grid.setColumnStretch(1, 1)
            self._grid.setHorizontalSpacing(14)
            self._grid.setVerticalSpacing(14)
            self._hero_layout.setContentsMargins(24, 18, 20, 18)
            self._hero_layout.setSpacing(12)
            self.orb.setFixedSize(104, 104)
            if self._extra_card is not None:
                self._grid.removeWidget(self._extra_card)
                self._grid.addWidget(self._extra_card, next_row + 1, 0, 1, 2)

    def open_extra(self) -> bool:
        """Scroll the autonomous-task card into view (no-op when absent)."""
        if self._extra_card is None:
            return False
        self.finish_loading()
        self._scroll.ensureWidgetVisible(self._extra_card, 0, 24)
        return True

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if not self._loaded and not self._loading_timer.isActive():
            self._loading_timer.start(780)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._loaded:
            self._loading_timer.stop()
        super().hideEvent(event)

    def finish_loading(self) -> None:
        self._loading_timer.stop()
        if self._loaded:
            return
        self._loaded = True
        self._skeleton.stop()
        self._skeleton.hide()
        self._ready_group.show()
        effect = QGraphicsDropShadowEffect(self._ready_group)
        effect.setColor(QColor(104, 217, 255, 32))
        effect.setBlurRadius(18)
        effect.setOffset(0, 3)
        self._ready_group.setGraphicsEffect(effect)

    def set_state(self, state: str) -> None:
        self._state = str(state or "IDLE").upper()
        self.orb.set_state(self._state)
        friendly = {
            "IDLE": "● SYSTEM STANDBY",
            "LISTENING": "● LISTENING",
            "THINKING": "◈ THINKING",
            "SPEAKING": "● SPEAKING",
            "PRIVACY_LOCK": "⊘ PRIVACY LOCK",
            "LOCKDOWN": "⊘ PRIVACY LOCK",
        }.get(self._state, f"● {self._state}")
        self.status_chip.setText(friendly)
        color = "#ff6280" if self._state in {"PRIVACY_LOCK", "LOCKDOWN"} else (
            "#a78bfa" if self._state == "THINKING" else (
                "#70ffc4" if self._state == "LISTENING" else "#8fffd6"
            )
        )
        self.status_chip.setStyleSheet(
            "QLabel#StatusChip { color: %s; background: rgba(49,208,158,22); "
            "border: 1px solid rgba(49,208,158,75); border-radius: 9px; padding: 6px 10px; "
            "font: 700 8pt 'Consolas'; }" % color
        )
        if self._state in {"LISTENING", "THINKING", "SPEAKING", "PRIVACY_LOCK", "LOCKDOWN"}:
            self.finish_loading()

    def set_audio_energy(self, level: float) -> None:
        self.orb.set_audio_energy(level)

    def set_bihansa_mode(self, enabled: bool) -> None:
        self.orb.set_bihansa_mode(enabled)
