"""The component set. Each mirrors a web primitive (frontend/src/components/ui) and its props.

Accessibility on the Qt side: every control gets an accessibleName (label) and, for hints/errors, an
accessibleDescription; tone/variant/size/state are dynamic properties the token QSS keys on.
"""
from __future__ import annotations

from typing import Callable, Iterable, Sequence

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ._fluent import fluent
from .theme import ms, px, reduced_motion, token

VARIANTS = ("solid", "outline", "ghost")
SIZES = ("sm", "md", "lg")
TONES = ("neutral", "primary", "ok", "warn", "danger")
_HEIGHT = {"sm": "control-sm", "md": "control-md", "lg": "control-lg"}


def _props(w: QWidget, variant: str = "outline", size: str = "md", tone: str = "neutral") -> None:
    if variant not in VARIANTS or size not in SIZES or tone not in TONES:
        raise ValueError(f"bad style props: {variant}/{size}/{tone}")
    w.setProperty("variant", variant)
    w.setProperty("uiSize", size)      # "size" is QWidget's own QSize property
    w.setProperty("tone", tone)


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


# ── Button ──────────────────────────────────────────────────────────────────
_FS = {"sm": "fs-sm", "md": "fs-md", "lg": "fs-base"}


def _tone_style(button: QWidget, variant: str, tone: str) -> None:
    """Fluent buttons style themselves; layer the tone colours on top (theme-aware) with setCustomStyleSheet."""
    cls = type(button).__name__
    if tone in ("primary", "neutral") and variant != "solid" or tone == "primary":
        return
    c = token("text-dim" if tone == "neutral" else tone)
    if variant == "solid":
        qss = (f"{cls} {{ background-color: {c}; border-color: {c}; color: {token('bg')}; }}"
               f"{cls}:hover {{ background-color: {c}; border-color: {token('text')}; }}"
               f"{cls}:pressed {{ background-color: {c}; color: {token('glass-strong')}; }}")
    elif variant == "outline":
        qss = f"{cls} {{ border: 1px solid {c}; color: {c}; }}"
    else:
        qss = f"{cls} {{ color: {c}; }}"
    fluent.setCustomStyleSheet(button, qss, qss)


class Button(QWidget):
    """PrimaryPushButton for variant=solid, PushButton for outline, TransparentPushButton for ghost.

    ``loading`` disables it and shows a spinner; the text stays (and is announced).
    """

    clicked = pyqtSignal()

    def __init__(self, text: str = "", *, variant: str = "solid", size: str = "md", tone: str = "primary",
                 icon=None, loading: bool = False, disabled: bool = False, accessible_name: str = "", parent=None):
        super().__init__(parent)
        _props(self, variant, size, tone)
        cls = {"solid": fluent.PrimaryPushButton, "outline": fluent.PushButton, "ghost": fluent.TransparentPushButton}[variant]
        self.button = cls(text, self) if icon is None else cls(icon, text, self)
        _props(self.button, variant, size, tone)
        self.button.setMinimumHeight(px(_HEIGHT[size]))
        _tone_style(self.button, variant, tone)
        self.button.setAccessibleName(accessible_name or text)
        self.button.clicked.connect(self.clicked.emit)
        self.spinner = fluent.IndeterminateProgressRing(self, start=False)
        self.spinner.setFixedSize(px("space-4"), px("space-4"))
        self.spinner.setStrokeWidth(2)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(px("space-1-5"))
        lay.addWidget(self.spinner)
        lay.addWidget(self.button)
        self._disabled = disabled
        self.set_loading(loading)

    @property
    def text(self) -> str:
        return self.button.text()

    def set_loading(self, on: bool) -> None:
        self.loading = bool(on)
        self.spinner.setVisible(self.loading)
        if self.loading and not reduced_motion():
            self.spinner.start()
        else:
            self.spinner.stop()
        self.button.setEnabled(not (self.loading or self._disabled))
        self.button.setProperty("busy", self.loading)
        self.button.setAccessibleDescription("busy" if self.loading else "")

    def setDisabled(self, on: bool) -> None:  # noqa: N802 - Qt naming
        self._disabled = bool(on)
        self.set_loading(self.loading)


# ── Field family ────────────────────────────────────────────────────────────
class _Field(QWidget):
    """Label + control + hint/error, the Qt twin of the web Field."""

    def __init__(self, label: str, control: QWidget, *, hint: str = "", error: str = "", parent=None):
        super().__init__(parent)
        self.control = control
        self.label = fluent.CaptionLabel(label, self)
        self.label.setBuddy(control)
        self.message = fluent.CaptionLabel("", self)
        self.message.setWordWrap(True)
        control.setAccessibleName(label)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(px("space-1"))
        lay.addWidget(self.label)
        lay.addWidget(control)
        lay.addWidget(self.message)
        lay.addStretch(1)
        self.hint = hint
        self.set_error(error)

    def set_error(self, error: str) -> None:
        self.error = error or ""
        invalid = bool(self.error)
        self.control.setProperty("invalid", invalid)
        if hasattr(self.control, "setError"):
            self.control.setError(invalid)
        cls = type(self.control).__name__
        border = f"{cls} {{ border: 1px solid {token('danger')}; }}" if invalid else ""
        fluent.setCustomStyleSheet(self.control, border, border)
        text = self.error or self.hint
        self.message.setText(text)
        self.message.setVisible(bool(text))
        self.message.setProperty("role", "error" if invalid else "faint")
        colour = QColor(token("danger") if invalid else token("text-faint"))
        self.message.setTextColor(colour, colour)      # Fluent labels ignore QSS colour
        self.control.setAccessibleDescription(text)
        _repolish(self.control)


class Input(_Field):
    def __init__(self, label: str, *, placeholder: str = "", value: str = "", hint: str = "", error: str = "",
                 size: str = "md", disabled: bool = False, loading: bool = False, parent=None):
        edit = fluent.LineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setText(value)
        edit.setMinimumHeight(px(_HEIGHT[size]))
        edit.setEnabled(not disabled)
        edit.setProperty("busy", loading)
        _props(edit, size=size)
        super().__init__(label, edit, hint=hint, error=error, parent=parent)


class Textarea(_Field):
    def __init__(self, label: str, *, placeholder: str = "", value: str = "", hint: str = "", error: str = "",
                 disabled: bool = False, parent=None):
        edit = fluent.PlainTextEdit()
        edit.setPlaceholderText(placeholder)
        edit.setPlainText(value)
        edit.setMinimumHeight(px("control-lg") * 2)
        edit.setEnabled(not disabled)
        super().__init__(label, edit, hint=hint, error=error, parent=parent)


class Select(_Field):
    """ComboBox. With no options it is disabled and shows ``empty_text``."""

    def __init__(self, label: str, options: Sequence[tuple[str, str]], *, value: str | None = None,
                 placeholder: str = "Choose…", empty_text: str = "Nothing to choose from", hint: str = "",
                 error: str = "", disabled: bool = False, size: str = "md", parent=None):
        box = fluent.ComboBox()
        box.setMinimumHeight(px(_HEIGHT[size]))
        for val, text in options:
            box.addItem(text, userData=val)
        self.empty_text = empty_text
        if not options:
            box.setPlaceholderText(empty_text)
            box.setEnabled(False)
            box.setAccessibleDescription(empty_text)
        else:
            box.setPlaceholderText(placeholder)
            idx = next((i for i, (v, _) in enumerate(options) if v == value), -1)
            box.setCurrentIndex(idx)
            box.setEnabled(not disabled)
        super().__init__(label, box, hint=hint, error=error, parent=parent)

    def value(self):
        return self.control.currentData()


class Checkbox(_Field):
    def __init__(self, label: str, *, checked: bool = False, hint: str = "", error: str = "",
                 disabled: bool = False, parent=None):
        box = fluent.CheckBox(label)
        box.setChecked(checked)
        box.setEnabled(not disabled)
        super().__init__(label, box, hint=hint, error=error, parent=parent)
        self.label.hide()          # the checkbox carries its own visible text


class Switch(QWidget):
    """On/off setting. ``toggled(bool)``."""

    toggled = pyqtSignal(bool)

    def __init__(self, label: str, *, checked: bool = False, disabled: bool = False, parent=None):
        super().__init__(parent)
        self.switch = fluent.SwitchButton(self)
        self.switch.setOnText("On")
        self.switch.setOffText("Off")
        self.switch.setChecked(checked)
        self.switch.setEnabled(not disabled)
        self.switch.setAccessibleName(label)
        self.switch.checkedChanged.connect(self.toggled.emit)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.switch)

    def isChecked(self) -> bool:  # noqa: N802
        return self.switch.isChecked()


class Segmented(QWidget):
    """One-of-many choice (SegmentedWidget). ``changed(value)``."""

    changed = pyqtSignal(str)

    def __init__(self, label: str, options: Sequence[tuple[str, str]], *, value: str = "", disabled: bool = False, parent=None):
        super().__init__(parent)
        self.seg = fluent.SegmentedWidget(self)
        self.seg.setAccessibleName(label)
        for val, text in options:
            self.seg.addItem(routeKey=val, text=text, onClick=lambda _=False, v=val: self.changed.emit(v))
        if value:
            self.seg.setCurrentItem(value)
        self.seg.setEnabled(not disabled)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.seg)

    def value(self) -> str:
        item = self.seg.currentItem()
        return item.property("routeKey") if item is not None and item.property("routeKey") else self.seg.currentRouteKey()


# ── Tabs ────────────────────────────────────────────────────────────────────
class Tabs(QWidget):
    """Pivot (tab strip) + stacked panels; arrow keys move along the strip."""

    changed = pyqtSignal(str)

    def __init__(self, label: str, items: Sequence[tuple[str, str, QWidget]], *, value: str = "", parent=None):
        super().__init__(parent)
        self.pivot = fluent.Pivot(self)
        self.pivot.setAccessibleName(label)
        self.stack = QStackedWidget(self)
        self._pages: dict[str, QWidget] = {}
        for key, text, page in items:
            page.setAccessibleName(text)
            self.stack.addWidget(page)
            self._pages[key] = page
            self.pivot.addItem(routeKey=key, text=text, onClick=lambda _=False, k=key: self.select(k))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(px("space-3"))
        lay.addWidget(self.pivot)
        lay.addWidget(self.stack)
        if items:
            self.select(value or items[0][0])

    def select(self, key: str) -> None:
        if key not in self._pages:
            return
        self.pivot.setCurrentItem(key)
        self.stack.setCurrentWidget(self._pages[key])
        self.current = key
        self.changed.emit(key)


# ── Table ───────────────────────────────────────────────────────────────────
class Table(QWidget):
    """TableWidget with loading / empty / error (+ retry) states, like the web Table."""

    def __init__(self, caption: str, columns: Sequence[tuple[str, str]], rows: Iterable[dict] = (), *,
                 loading: bool = False, error: str = "", on_retry: Callable[[], None] | None = None,
                 empty_text: str = "Nothing here yet.", parent=None):
        super().__init__(parent)
        self.columns = list(columns)
        self.table = fluent.TableWidget(self)
        self.table.setAccessibleName(caption)
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels([h for _, h in self.columns])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.state = QFrame(self)
        sl = QHBoxLayout(self.state)
        self.state_text = fluent.BodyLabel("", self.state)
        self.state_text.setWordWrap(True)
        self.retry = Button("Try again", variant="outline", tone="neutral", size="sm", parent=self.state)
        if on_retry:
            self.retry.clicked.connect(on_retry)
        self.ring = fluent.IndeterminateProgressRing(self.state, start=False)
        self.ring.setFixedSize(px("space-5"), px("space-5"))
        sl.addStretch(1)
        sl.addWidget(self.ring)
        sl.addWidget(self.state_text)
        sl.addWidget(self.retry)
        sl.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)
        lay.addWidget(self.state)
        self.empty_text = empty_text
        self.on_retry = on_retry
        self.set_rows(rows, loading=loading, error=error)

    def set_rows(self, rows: Iterable[dict], *, loading: bool = False, error: str = "") -> None:
        rows = list(rows)
        self.table.setRowCount(0 if (loading or error) else len(rows))
        if not (loading or error):
            for r, row in enumerate(rows):
                for c, (key, _) in enumerate(self.columns):
                    item = QTableWidgetItem(str(row.get(key, "")))
                    if isinstance(row.get(key), (int, float)):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(r, c, item)
        self.mode = "error" if error else "loading" if loading else "empty" if not rows else "rows"
        self.state.setVisible(self.mode != "rows")
        self.ring.setVisible(self.mode == "loading")
        if self.mode == "loading" and not reduced_motion():
            self.ring.start()
        else:
            self.ring.stop()
        self.retry.setVisible(self.mode == "error" and self.on_retry is not None)
        self.state_text.setText({"error": error, "loading": "Loading…", "empty": self.empty_text}.get(self.mode, ""))
        colour = QColor(token("danger") if self.mode == "error" else token("text-dim"))
        self.state_text.setTextColor(colour, colour)
        self.setAccessibleDescription(self.state_text.text())


# ── Overlays ────────────────────────────────────────────────────────────────
class Dialog(fluent.MessageBoxBase):
    """Modal dialog over ``parent`` (dims it): title, optional description, body, buttons (primary last)."""

    def __init__(self, title: str, *, parent: QWidget, description: str = "", body: QWidget | None = None,
                 primary: str = "OK", secondary: str = "Cancel"):
        super().__init__(parent)
        self.title = fluent.SubtitleLabel(title, self)
        self.viewLayout.addWidget(self.title)
        if description:
            d = fluent.BodyLabel(description, self)
            d.setWordWrap(True)
            d.setTextColor(QColor(token("text-dim")), QColor(token("text-dim")))
            self.viewLayout.addWidget(d)
        if body is not None:
            self.viewLayout.addWidget(body)
        self.yesButton.setText(primary)
        self.cancelButton.setText(secondary)
        self.setAccessibleName(title)
        self.widget.setMinimumWidth(min(px("dialog-w"), 560))


class Sheet(QFrame):
    """Panel that slides in from an edge of ``parent``; Escape closes it. Non-modal, like the settings drawer."""

    closed = pyqtSignal()

    def __init__(self, title: str, body: QWidget, *, side: str = "right", parent: QWidget):
        super().__init__(parent)
        self.side = side
        self.setObjectName("Glass")
        self.setAccessibleName(title)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        lay = QVBoxLayout(self)
        m = px("space-4")
        lay.setContentsMargins(m, m, m, m)
        head = QHBoxLayout()
        head.addWidget(fluent.SubtitleLabel(title, self), 1)
        close = fluent.TransparentToolButton(fluent.FluentIcon.CLOSE, self)
        close.setAccessibleName("Close")
        close.clicked.connect(self.close_sheet)
        head.addWidget(close)
        lay.addLayout(head)
        lay.addWidget(body, 1)
        self.hide()

    def _geom(self, shown: bool):
        p = self.parentWidget().rect()
        if self.side == "bottom":
            h = int(p.height() * 0.6)
            return (QPoint(0, p.height() - h if shown else p.height()), p.width(), h)
        w = min(px("sheet-w"), p.width())
        x = (p.width() - w if shown else p.width()) if self.side == "right" else (0 if shown else -w)
        return (QPoint(x, 0), w, p.height())

    def open_sheet(self) -> None:
        start, w, h = self._geom(False)
        end, _, _ = self._geom(True)
        self.resize(w, h)
        self.move(start)
        self.show()
        self.raise_()
        self.setFocus()
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(ms("dur"))
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def close_sheet(self) -> None:
        self.hide()
        self.closed.emit()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.close_sheet()
        else:
            super().keyPressEvent(e)


def popover(target: QWidget, title: str, content: str, *, parent=None):
    """Non-modal Flyout anchored to ``target``."""
    ani = fluent.FlyoutAnimationType.NONE if reduced_motion() else fluent.FlyoutAnimationType.PULL_UP
    return fluent.Flyout.create(title=title, content=content, target=target, parent=parent or target.window(),
                                isClosable=True, aniType=ani)


def tooltip(widget: QWidget, text: str) -> None:
    """Hover/focus hint. Never the only place information lives."""
    widget.setToolTip(text)
    widget.installEventFilter(fluent.ToolTipFilter(widget, showDelay=200, position=fluent.ToolTipPosition.TOP))


_TOAST = {"ok": "success", "warn": "warning", "danger": "error", "neutral": "info", "primary": "info"}


def toast(parent: QWidget, title: str, content: str = "", *, tone: str = "neutral"):
    """InfoBar in the top-right corner. Errors stay until closed; others hide after ``dur-toast``."""
    make = getattr(fluent.InfoBar, _TOAST.get(tone, "info"))
    return make(title=title, content=content, parent=parent, position=fluent.InfoBarPosition.TOP_RIGHT,
                duration=-1 if tone == "danger" else int(token("dur-toast").removesuffix("ms")), isClosable=True)


# ── Charts and Qt-only extras ───────────────────────────────────────────────
class SparkChart(QWidget):
    """Realtime sparkline (pyqtgraph). The numbers go to accessibleDescription, like the web text equivalent."""

    def __init__(self, label: str, data: Sequence[float] = (), *, unit: str = "", max_value: float | None = None,
                 tone: str = "secondary", parent=None):
        super().__init__(parent)
        import pyqtgraph as pg

        self.label, self.unit = label, unit
        self.plot = pg.PlotWidget(self)
        self.plot.setBackground(None)
        self.plot.setStyleSheet("background: transparent; border: none;")
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.plot.setMouseEnabled(False, False)
        self.plot.setMenuEnabled(False)
        self.plot.setFixedHeight(px("control-lg") + px("space-1"))
        if max_value is not None:
            self.plot.setYRange(0, max_value, padding=0)
        colour = token(tone if tone in ("secondary", "primary", "warm", "amber") else "secondary")
        self.curve = self.plot.plot([], pen=pg.mkPen(colour, width=1.5), fillLevel=0, brush=pg.mkBrush(colour + "2e"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.caption = fluent.CaptionLabel(label, self)
        lay.addWidget(self.caption)
        lay.addWidget(self.plot)
        self.set_data(data)

    def set_data(self, data: Sequence[float]) -> None:
        data = list(data)
        self.curve.setData(data)
        if not data:
            text = f"{self.label}: no samples yet"
        else:
            text = (f"{self.label}: now {round(data[-1])}{self.unit}, min {round(min(data))}, "
                    f"max {round(max(data))} over {len(data)} s")
        self.caption.setText(text if not data else f"{self.label}  {round(data[-1])}{self.unit}")
        self.setAccessibleDescription(text)


class Collapsible(QWidget):
    """Collapsible section (SuperQt). Qt-only helper for long settings pages; animation off for reduced motion."""

    def __init__(self, title: str, body: QWidget, *, expanded: bool = False, parent=None):
        super().__init__(parent)
        from superqt import QCollapsible

        self.box = QCollapsible(title, self)
        self.box.setDuration(ms("dur"))
        self.box.addWidget(body)
        if expanded:
            self.box.expand(animate=False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.box)


def label(text: str, role: str = "") -> QLabel:
    """Plain label with an optional token role (dim / faint) for the QSS."""
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    return lb
