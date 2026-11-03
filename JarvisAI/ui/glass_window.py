"""Glass windows for the HUD and the widgets that live in them.

A :class:`GlassWindow` is a frameless, translucent panel with a title bar
(drag to move it to the other dock, minimise, close) painted from the theme
tokens. Where it goes is decided by core/window_manager.py; this module only
draws and reports what the user did.

Contents, one per window kind: a timer, an image viewer, a headline list, the
downloads folder, and web players (YouTube Music, music, video) with media
controls. Chromium (QtWebEngine) is imported only when a web window is first
opened, so starting JARVIS stays light; a web window whose page the manager
freezes stops using CPU until it is shown again.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QVBoxLayout, QWidget)

from core.ui_tokens import BASE_COLORS as T
from core.ui_tokens import GLASS

_BTN = (f"QPushButton {{ color:{T['text']}; background:transparent; border:1px solid {T['border']};"
        f" border-radius:6px; padding:3px 10px; font: 9pt 'Consolas'; }}"
        f"QPushButton:hover {{ border-color:{T['primary']}; color:{T['primary']}; }}")


def _alpha(hex_: str, a: float) -> QColor:
    c = QColor(hex_)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


class GlassWindow(QFrame):
    """A translucent window frame around one content widget."""

    close_clicked = pyqtSignal(str)
    minimize_clicked = pyqtSignal(str)
    dropped = pyqtSignal(str, float, float)       # id, x, y in the parent
    activated = pyqtSignal(str)

    def __init__(self, wid: str, title: str, content: QWidget, parent: QWidget | None = None,
                 lite: bool = False):
        super().__init__(parent)
        self.wid = wid
        self.content = content
        self.lite = lite
        self._drag_from: QPoint | None = None
        self.setObjectName("GlassWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        bar = QWidget(self)
        bar.setFixedHeight(28)
        bar.setCursor(Qt.CursorShape.OpenHandCursor)
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(12, 0, 6, 0)
        self._title = QLabel(title, bar)
        self._title.setStyleSheet(f"color:{T['primary']}; font: bold 9pt 'Consolas'; letter-spacing:2px;")
        hb.addWidget(self._title)
        hb.addStretch(1)
        for text, tip, sig in (("—", "Minimise", self.minimize_clicked), ("✕", "Close", self.close_clicked)):
            b = QPushButton(text, bar)
            b.setToolTip(tip)
            b.setFixedSize(24, 20)
            b.setStyleSheet(f"QPushButton {{ color:{T['text_dim']}; background:transparent; border:none; }}"
                            f"QPushButton:hover {{ color:{T['white']}; }}")
            b.clicked.connect(lambda _=False, s=sig: s.emit(self.wid))
            hb.addWidget(b)
        self._bar = bar

        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        lay.addWidget(bar)
        content.setParent(self)
        lay.addWidget(content, 1)

    # ── painting ────────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = GLASS["radius"]
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        fill = GLASS["fill_alpha_low"] if self.lite else GLASS["fill_alpha"]
        p.fillPath(path, _alpha(T["panel"], fill))
        sheen = QLinearGradient(0, 0, 0, 40)
        sheen.setColorAt(0.0, _alpha(T["white"], GLASS["highlight_alpha"]))
        sheen.setColorAt(1.0, _alpha(T["white"], 0.0))
        p.fillPath(path, QBrush(sheen))
        p.setPen(QPen(_alpha(T["primary"], GLASS["border_alpha"]), 1.0))
        p.drawPath(path)
        p.setPen(QPen(_alpha(T["primary"], 0.25), 1.0))
        p.drawLine(int(r.left() + 12), 28, int(r.right() - 12), 28)

    # ── dragging between docks ──────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        self.activated.emit(self.wid)
        if event.position().y() <= self._bar.height():
            self._drag_from = event.globalPosition().toPoint() - self.pos()
            self._bar.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            self.raise_()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_from is not None:
            self._drag_from = None
            self._bar.setCursor(Qt.CursorShape.OpenHandCursor)
            c = self.geometry().center()
            self.dropped.emit(self.wid, float(c.x()), float(c.y()))
        super().mouseReleaseEvent(event)

    # ── page lifecycle (web windows) ────────────────────────────────────────
    def set_frozen(self, frozen: bool) -> None:
        fn = getattr(self.content, "set_frozen", None)
        if fn is not None:
            fn(frozen)


# ── contents ────────────────────────────────────────────────────────────────

def _label(text: str, size: int = 9, color: str | None = None, bold: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"color:{color or T['text']}; font: {'bold ' if bold else ''}{size}pt 'Consolas';"
                      " background:transparent;")
    return lab


class TimerContent(QWidget):
    """Countdown timer: +1 / +5 / +15 minutes, start-pause, reset."""

    finished = pyqtSignal()

    def __init__(self, seconds: int = 0, parent=None):
        super().__init__(parent)
        self.remaining = float(max(0, seconds))
        self.running = False
        self._last = 0.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 12)
        self._display = _label("00:00", 26, T["primary"], bold=True)
        self._display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._display, 1)
        row = QHBoxLayout()
        for text, fn in (("+1m", lambda: self.add(60)), ("+5m", lambda: self.add(300)),
                         ("+15m", lambda: self.add(900)), ("▶/❚❚", self.toggle), ("Reset", self.reset)):
            b = QPushButton(text)
            b.setStyleSheet(_BTN)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._step)
        self._tick.start(250)
        self._render()
        if seconds:
            self.toggle()

    def add(self, seconds: float) -> None:
        self.remaining += seconds
        self._render()

    def toggle(self) -> None:
        self.running = not self.running and self.remaining > 0
        self._last = time.monotonic()

    def reset(self) -> None:
        self.running = False
        self.remaining = 0.0
        self._render()

    def _step(self) -> None:
        if not self.running:
            return
        now = time.monotonic()
        self.remaining = max(0.0, self.remaining - (now - self._last))
        self._last = now
        if self.remaining <= 0:
            self.running = False
            self.finished.emit()
        self._render()

    def _render(self) -> None:
        s = int(self.remaining + 0.999)
        self._display.setText(f"{s // 3600:d}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600
                              else f"{s // 60:02d}:{s % 60:02d}")


class ImageContent(QWidget):
    def __init__(self, path: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 10)
        self._view = _label("No image", 9, T["text_dim"])
        self._view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view.setMinimumHeight(60)
        lay.addWidget(self._view, 1)
        b = QPushButton("Open image…")
        b.setStyleSheet(_BTN)
        b.clicked.connect(self._pick)
        lay.addWidget(b)
        self._pixmap: QPixmap | None = None
        if path:
            self.show_image(path)

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open image", str(Path.home()),
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if path:
            self.show_image(path)

    def show_image(self, path: str) -> bool:
        pm = QPixmap(path)
        if pm.isNull():
            self._view.setText("Could not open the image")
            return False
        self._pixmap = pm
        self._fit()
        return True

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        if self._pixmap is not None and self._view.width() > 4:
            self._view.setPixmap(self._pixmap.scaled(self._view.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))


_LIST = (f"QListWidget {{ background:transparent; border:none; color:{T['text']}; font: 9pt 'Consolas'; }}"
         f"QListWidget::item {{ padding:5px 4px; border-bottom:1px solid {T['border']}; }}"
         f"QListWidget::item:selected {{ background:{T['primary_ghost']}; color:{T['white']}; }}")


class NewsContent(QWidget):
    """Headlines (title, source, url); double-click opens the article."""

    def __init__(self, items=None, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 8)
        self.list = QListWidget()
        self.list.setStyleSheet(_LIST)
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemDoubleClicked.connect(self._open)
        lay.addWidget(self.list)
        self.set_items(items or [])

    def set_items(self, items) -> None:
        self.list.clear()
        if not items:
            self.list.addItem("No headlines yet — ask JARVIS for the news.")
            return
        for it in items:
            title = str(it.get("title") or "").strip()
            src = str(it.get("source") or "").strip()
            item = QListWidgetItem(f"{title}\n{src}" if src else title)
            item.setData(Qt.ItemDataRole.UserRole, str(it.get("url") or ""))
            self.list.addItem(item)

    def _open(self, item: QListWidgetItem) -> None:
        url = item.data(Qt.ItemDataRole.UserRole)
        if url and str(url).startswith("https://"):
            QDesktopServices.openUrl(QUrl(url))


def downloads_dir() -> Path:
    return Path(os.environ.get("JARVIS_DOWNLOADS") or (Path.home() / "Downloads"))


def recent_files(folder: Path, limit: int = 40) -> list[Path]:
    try:
        files = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
    except OSError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


class DownloadsContent(QWidget):
    """Newest files in the Downloads folder; double-click opens one."""

    def __init__(self, folder: str = "", parent=None):
        super().__init__(parent)
        self.folder = Path(folder) if folder else downloads_dir()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 8)
        self.list = QListWidget()
        self.list.setStyleSheet(_LIST)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemDoubleClicked.connect(self._open)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn in (("Refresh", self.refresh), ("Open folder", self._open_folder)):
            b = QPushButton(text)
            b.setStyleSheet(_BTN)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        files = recent_files(self.folder)
        if not files:
            self.list.addItem(f"Nothing in {self.folder}")
        for f in files:
            item = QListWidgetItem(f"{f.name}   ·  {_size(f.stat().st_size)}")
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            self.list.addItem(item)

    def _open(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))


# Media control scripts, run in the page. YouTube Music has its own buttons;
# anything else gets the first <video>/<audio> element.
_JS_TOGGLE = ("(function(){var b=document.querySelector('#play-pause-button');if(b){b.click();return;}"
              "var m=document.querySelector('video,audio');if(m){m.paused?m.play():m.pause();}})()")
_JS_NEXT = ("(function(){var b=document.querySelector('.next-button, .ytp-next-button');"
            "if(b){b.click();}})()")
_JS_PREV = ("(function(){var b=document.querySelector('.previous-button, .ytp-prev-button');"
            "if(b){b.click();}else{var m=document.querySelector('video,audio');if(m){m.currentTime=0;}}})()")
_JS_MUTE = "(function(){var m=document.querySelector('video,audio');if(m){m.muted=!m.muted;}})()"
_JS_PAUSE = "(function(){document.querySelectorAll('video,audio').forEach(function(m){m.pause();});})()"

DEFAULT_URLS = {"youtube_music": "https://music.youtube.com/", "music": "https://music.youtube.com/",
                "video": "https://www.youtube.com/"}


class WebMediaContent(QWidget):
    """A web player with media controls. QtWebEngine loads on first use."""

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.view = None
        self._frozen = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 6)
        lay.setSpacing(6)
        self._host = QVBoxLayout()
        lay.addLayout(self._host, 1)
        row = QHBoxLayout()
        for text, js in (("⏮", _JS_PREV), ("⏯", _JS_TOGGLE), ("⏭", _JS_NEXT), ("🔇", _JS_MUTE)):
            b = QPushButton(text)
            b.setStyleSheet(_BTN)
            b.clicked.connect(lambda _=False, s=js: self.run_js(s))
            row.addWidget(b)
        lay.addLayout(row)
        self._status = _label("", 8, T["text_dim"])
        self._host.addWidget(self._status)
        QTimer.singleShot(0, self._create_view)

    def _create_view(self) -> None:
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView   # Chromium: only now
        except Exception as exc:                                    # not installed
            self._status.setText(f"Web player unavailable: {exc.__class__.__name__}")
            return
        self.view = QWebEngineView(self)
        self._status.hide()
        self._host.addWidget(self.view, 1)
        self.view.load(QUrl(self.url))

    def run_js(self, script: str) -> None:
        if self.view is not None and not self._frozen:
            self.view.page().runJavaScript(script)

    def set_frozen(self, frozen: bool) -> None:
        """Sleep the page while hidden; a visible one is only paused."""
        if self.view is None or frozen == self._frozen:
            return
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage
            page = self.view.page()
            if frozen:
                page.runJavaScript(_JS_PAUSE)
                if not self.isVisible():
                    page.setLifecycleState(QWebEnginePage.LifecycleState.Frozen)
            else:
                page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
            self._frozen = frozen
        except Exception as exc:          # an old QtWebEngine without lifecycle states
            print(f"[GlassWindow] page lifecycle change failed: {exc}")


def make_content(kind: str, payload: dict | None = None) -> QWidget:
    payload = payload or {}
    if kind == "timer":
        return TimerContent(int(payload.get("seconds") or 0))
    if kind == "image":
        return ImageContent(str(payload.get("path") or ""))
    if kind == "news":
        return NewsContent(payload.get("items") or [])
    if kind == "downloads":
        return DownloadsContent(str(payload.get("folder") or ""))
    if kind in DEFAULT_URLS:
        return WebMediaContent(str(payload.get("url") or DEFAULT_URLS[kind]))
    raise KeyError(kind)
