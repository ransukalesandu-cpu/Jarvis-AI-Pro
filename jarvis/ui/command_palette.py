"""The Ctrl+K command palette and the Dynamic Island pill.

The palette is a centred glass card: type to filter every HUD command
(core/ui_menus.py), arrows to choose, Enter to run, Esc to close. Anything it
does not know is sent to JARVIS as a question.

The island is a small pill at the top of the stage. It follows the state bus:
a dot in the assistant's state colour, the state, the open windows, and a
running timer's countdown. Clicking it opens the palette.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from jarvis.core import ui_menus, ui_state
from jarvis.core.ui_tokens import BASE_COLORS as T
from jarvis.core.ui_tokens import GLASS, state_color


def _alpha(hex_: str, a: float) -> QColor:
    c = QColor(hex_)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


class CommandPalette(QFrame):
    """Search-and-run for every HUD command."""

    command_chosen = pyqtSignal(str)     # a command id from core/ui_menus
    text_submitted = pyqtSignal(str)     # free text for JARVIS

    W, H = 560, 380

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.extra: list[ui_menus.Command] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Search commands, or ask JARVIS…   (Esc to close)")
        self.input.setFont(QFont("Consolas", 11))
        self.input.setStyleSheet(
            f"QLineEdit {{ color:{T['white']}; background:{T['dark']}; border:1px solid {T['border_accent']};"
            f" border-radius:8px; padding:8px 10px; }} QLineEdit:focus {{ border-color:{T['primary']}; }}")
        self.list = QListWidget(self)
        self.list.setFont(QFont("Consolas", 10))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setStyleSheet(
            f"QListWidget {{ background:transparent; border:none; color:{T['text']}; }}"
            f"QListWidget::item {{ padding:6px 8px; border-radius:6px; }}"
            f"QListWidget::item:selected {{ background:{T['primary_ghost']}; color:{T['primary']}; }}")
        lay.addWidget(self.input)
        lay.addWidget(self.list, 1)
        self.input.textChanged.connect(self.refresh)
        self.input.returnPressed.connect(self._run)
        self.list.itemActivated.connect(lambda _i: self._run())
        self.input.installEventFilter(self)
        self.hide()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        p.fillPath(path, _alpha(T["panel"], 0.94))
        p.setPen(QPen(_alpha(T["primary"], GLASS["border_alpha"]), 1.2))
        p.drawPath(path)

    def open(self) -> None:
        par = self.parentWidget()
        if par is not None:
            w = min(self.W, par.width() - 40)
            h = min(self.H, par.height() - 80)
            self.setGeometry((par.width() - w) // 2, max(20, par.height() // 6), w, h)
        self.input.clear()
        self.refresh()
        self.show()
        self.raise_()
        self.input.setFocus()

    def refresh(self) -> None:
        self.list.clear()
        for c in ui_menus.search(self.input.text(), self.extra):
            item = QListWidgetItem(f"{c.title}    ·  {c.section}" + (f"   {c.shortcut}" if c.shortcut else ""))
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.input and event.type() == event.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow() + (1 if key == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
        return super().eventFilter(obj, event)

    def _run(self) -> None:
        item = self.list.currentItem()
        text = self.input.text().strip()
        self.hide()
        if item is not None:
            self.command_chosen.emit(str(item.data(Qt.ItemDataRole.UserRole)))
        elif text:
            self.text_submitted.emit(text)


class IslandPill(QWidget):
    """The Dynamic Island: state, open windows and a running timer."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Command palette (Ctrl+K)")
        self.state = "idle"
        self.windows: tuple = ()
        self.timer_text = ""
        bus = ui_state.bus()
        self.state = str(bus.get(ui_state.ASSISTANT, "idle"))
        self.windows = tuple(bus.get(ui_state.WINDOWS, ()) or ())
        self._unsub = [bus.subscribe(ui_state.ASSISTANT, self._on_bus),
                       bus.subscribe(ui_state.WINDOWS, self._on_bus)]
        self.destroyed.connect(lambda *_: [u() for u in self._unsub])

    def _on_bus(self, key: str, value) -> None:
        if key == ui_state.ASSISTANT:
            self.state = str(value)
        elif key == ui_state.WINDOWS:
            self.windows = tuple(value or ())
        self.update()

    def set_timer(self, text: str) -> None:
        if text != self.timer_text:
            self.timer_text = text
            self.update()

    def text(self) -> str:
        parts = [self.state.replace("_", " ").upper()]
        if self.timer_text:
            parts.append(f"◷ {self.timer_text}")
        if self.windows:
            parts.append(f"▣ {len(self.windows)}")
        return "   ·   ".join(parts)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, _alpha(T["dark"], 0.88))
        col = state_color(self.state)
        p.setPen(QPen(_alpha(col, 0.55), 1.0))
        p.drawPath(path)
        d = r.height() * 0.28
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col))
        p.drawEllipse(QRectF(r.left() + r.height() * 0.45, r.center().y() - d / 2, d, d))
        p.setPen(QColor(T["text"]))
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        p.drawText(r.adjusted(r.height() * 0.9, 0, -10, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())

    def mouseReleaseEvent(self, event) -> None:
        self.clicked.emit()
        super().mouseReleaseEvent(event)
