"""Polished side-panel cards for the main HUD.

These wrappers deliberately leave each live telemetry widget's contents and
behavior intact. They add a skeleton placeholder, subtle magnetic shadow, and
a short fade-in only around the non-hologram telemetry surfaces.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QEasingCurve, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QColor, QCursor
from PyQt6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QStackedWidget,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ui.panels.modern_dashboard import SkeletonLoader


class BentoPanelSurface(QFrame):
    """A geometry-neutral wrapper for one existing telemetry panel."""

    def __init__(self, panel: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("BentoPanelSurface")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setMinimumWidth(max(0, panel.minimumWidth()))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(
            "QFrame#BentoPanelSurface { background: transparent; border: none; padding: 0; }"
        )

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setColor(QColor(61, 190, 232, 48))
        self._shadow.setBlurRadius(14.0)
        self._shadow.setOffset(0.0, 3.0)
        self.setGraphicsEffect(self._shadow)
        self._shadow_animation = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._shadow_animation.setDuration(190)
        self._shadow_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hovered = False
        self._reveal_animation: QPropertyAnimation | None = None

        self._stack = QStackedWidget(self)
        self._stack.setObjectName("BentoPanelStack")
        self._stack.setFrameShape(QFrame.Shape.NoFrame)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setStyleSheet("QStackedWidget#BentoPanelStack { background: transparent; border: none; }")
        stack_layout = QVBoxLayout(self)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.setSpacing(0)
        stack_layout.addWidget(self._stack)

        self.panel = panel
        self.panel.setParent(self._stack)
        self._stack.addWidget(self.panel)
        self._skeleton = SkeletonLoader(self._stack)
        self._stack.addWidget(self._skeleton)
        self._stack.setCurrentWidget(self._skeleton)

        # Qt sends pointer events to child labels as they cover the panel.
        # Observe the existing children too, without altering their behavior.
        self.panel.setMouseTracking(True)
        self.panel.installEventFilter(self)
        for child in self.panel.findChildren(QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)

        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.timeout.connect(self.show_panel)
        self._reveal_timer.start(620)

    def show_panel(self) -> None:
        """Replace skeleton bars with the live panel using a brief opacity fade."""
        if self._stack.currentWidget() is self.panel:
            return
        self._skeleton.stop()
        self.panel.setGraphicsEffect(None)
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        effect = QGraphicsOpacityEffect(self.panel)
        effect.setOpacity(0.0)
        self.panel.setGraphicsEffect(effect)
        self._stack.setCurrentWidget(self.panel)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(220)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def finish():
            if self._reveal_animation is animation:
                self.panel.setGraphicsEffect(None)
                self._reveal_animation = None

        animation.finished.connect(finish)
        self._reveal_animation = animation
        animation.start()

    def _animate_shadow(self, hovering: bool) -> None:
        self._hovered = hovering
        self._shadow_animation.stop()
        self._shadow_animation.setStartValue(self._shadow.blurRadius())
        self._shadow_animation.setEndValue(25.0 if hovering else 14.0)
        self._shadow_animation.start()
        if not hovering:
            self._shadow.setOffset(0.0, 3.0)

    def _reset_if_pointer_left(self) -> None:
        local = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(local):
            self._animate_shadow(False)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        event_type = event.type()
        if event_type == QEvent.Type.Enter:
            self._animate_shadow(True)
        elif event_type == QEvent.Type.MouseMove and self._hovered:
            local = self.mapFromGlobal(QCursor.pos())
            cx = max(1.0, self.width() / 2.0)
            cy = max(1.0, self.height() / 2.0)
            px = max(-1.0, min(1.0, (local.x() - cx) / cx))
            py = max(-1.0, min(1.0, (local.y() - cy) / cy))
            self._shadow.setOffset(px * 2.4, 2.0 + py * 1.5)
        elif event_type == QEvent.Type.Leave:
            QTimer.singleShot(24, self._reset_if_pointer_left)
        return super().eventFilter(watched, event)
