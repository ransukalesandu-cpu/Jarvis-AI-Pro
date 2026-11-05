"""HUD widgets and overlay panels used by the main JARVIS window.

Split out of ``ui/__init__.py`` to keep that module manageable. Everything here
is re-exported from ``ui`` so ``from ui import SetupOverlay`` keeps working.

The shared theme helpers (``C``, ``qcol``, ...) still live in ``ui/__init__.py``.
``ui`` imports this module only after defining them, so the import below
resolves against the partly initialised package. ``_read_full_config`` is the
same function object as ``ui._read_full_config``, so patching ``ui.API_FILE`` in
tests still affects these panels.
"""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPointF,
    QPropertyAnimation, QRectF, Qt, QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QDesktopServices, QDragEnterEvent, QDropEvent, QFont,
    QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSlider, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from . import _OS, DEFAULT_UI_COLOR, C, _read_full_config, qcol


class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        v = max(0.0, min(100.0, pct))
        if v == self._value and text == self._text:
            return          # unchanged — skip the repaint
        self._value = v
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 4, 4)

        bar_h   = 4
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

        p.end()

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        # Cap scrollback so an hours-long session can't grow the document
        # without bound — keeps memory flat and every insert cheap. Oldest
        # lines drop off the top automatically.
        self.document().setMaximumBlockCount(600)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._ai_name_lc = "jarvis"   # updated when assistant name changes
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        _ai_pfx = f"{self._ai_name_lc}:"
        if   tl.startswith("you:"):                              self._tag = "you"
        elif tl.startswith(_ai_pfx) or tl.startswith("jarvis:"): self._tag = "ai"
        elif tl.startswith("file:"):                             self._tag = "file"
        elif "err" in tl:                                        self._tag = "err"
        else:                                                    self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                # SYS lines are the bulk of the log. Amber fought the cyan HUD
                # and, being a fixed status colour rather than a hue-linked one,
                # stayed amber even after the accent picker retinted everything
                # else. TEXT_MED follows the theme and drops the contrast to a
                # level you can read past.
                "sys":  qcol(C.TEXT_MED),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        # The marching-ants dashed border is only meaningful while the user is
        # hovering or dragging a file over the zone. When idle, skip the repaint
        # entirely instead of redrawing the whole zone 25×/s forever — that idle
        # repaint held the GIL and stole time from the audio/response threads.
        if not (self._hovering or self._drag_over):
            return
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

        p.end()

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 244, 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(0, 6, 10, 242);
                border: 1px solid {C.PRI};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Courier New", 8))
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; border: none;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 12
            scaled = px.scaled(
                max_w, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)   # auto-dismiss after 6 s


class ProviderTile(QPushButton):
    """Offline-drawn provider mark and label for the first-run selector."""

    def __init__(self, provider: str, title: str, subtitle: str,
                 accent: str, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.title = title
        self.subtitle = subtitle
        self.accent = QColor(accent)
        self.setCheckable(True)
        self.setFixedHeight(54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(f"Select {title} as the one-shot AI provider")
        self.setStyleSheet("ProviderTile { border: none; }")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        selected = self.isChecked()
        fill = QColor(self.accent)
        fill.setAlpha(28 if selected else 10)
        painter.setBrush(fill)
        border = QColor(self.accent)
        border.setAlpha(230 if selected else 70)
        painter.setPen(QPen(border, 1.4 if selected else 1.0))
        painter.drawRoundedRect(bounds, 4, 4)

        cx, cy = 25.0, self.height() / 2.0
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self.accent, 2.0, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if self.provider == "gemini":
            # Gemini's four-point sparkle in a restrained cyan-to-violet glow.
            star = QPainterPath()
            star.moveTo(cx, cy - 15); star.lineTo(cx + 3.5, cy - 3.5)
            star.lineTo(cx + 15, cy); star.lineTo(cx + 3.5, cy + 3.5)
            star.lineTo(cx, cy + 15); star.lineTo(cx - 3.5, cy + 3.5)
            star.lineTo(cx - 15, cy); star.lineTo(cx - 3.5, cy - 3.5)
            star.closeSubpath()
            gradient = QLinearGradient(cx - 13, cy - 12, cx + 13, cy + 12)
            gradient.setColorAt(0.0, QColor("#58D7FF"))
            gradient.setColorAt(0.55, QColor("#9B7BFF"))
            gradient.setColorAt(1.0, QColor("#F27DFF"))
            painter.fillPath(star, gradient)
        elif self.provider == "openai":
            # Six interlocking loops suggest the OpenAI rosette at small sizes.
            painter.setPen(QPen(self.accent, 1.8))
            for angle in range(0, 360, 60):
                painter.save()
                painter.translate(cx, cy)
                painter.rotate(angle)
                painter.drawEllipse(QRectF(-4.4, -11.3, 8.8, 13.0))
                painter.restore()
            painter.drawEllipse(QRectF(cx - 2.1, cy - 2.1, 4.2, 4.2))
        else:
            # Claude's warm sunburst mark, drawn as precise tapered rays.
            painter.setPen(QPen(self.accent, 2.2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            for angle in range(-90, 270, 30):
                painter.save()
                painter.translate(cx, cy)
                painter.rotate(angle)
                painter.drawLine(QPointF(0, -6), QPointF(0, -15))
                painter.restore()
            painter.setBrush(self.accent)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(cx - 3.0, cy - 3.0, 6.0, 6.0))

        primary = QColor(C.TEXT if selected else C.TEXT_MED)
        painter.setPen(primary)
        painter.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(49, cy - 13, self.width() - 55, 18),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.title)
        painter.setPen(QColor(C.TEXT_DIM))
        painter.setFont(QFont("Courier New", 6, QFont.Weight.Normal))
        painter.drawText(QRectF(49, cy + 3, self.width() - 55, 14),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.subtitle)
        if self.hasFocus():
            painter.setPen(QPen(QColor(C.PRI), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(bounds.adjusted(3, 3, -3, -3), 3, 3)


class SetupOverlay(QWidget):
    """Focused first-run setup panel: collect only the required Gemini Live API key."""

    done = pyqtSignal(object)

    def __init__(self, parent=None, *, allow_keep_existing: bool = True):
        super().__init__(parent)
        self._allow_keep_existing = bool(allow_keep_existing)
        self.setObjectName("GeminiSetupOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            QWidget#GeminiSetupOverlay {{
                background: rgba(6, 13, 19, 250);
                border: 1px solid rgba(113, 212, 194, 150);
                border-radius: 14px;
            }}
            QLabel {{ background: transparent; }}
        """)

        config = _read_full_config()
        self._existing_gemini_key = str(config.get("gemini_api_key", "") or "").strip()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 23, 26, 22)
        layout.setSpacing(10)

        eyebrow = QLabel("J.A.R.V.I.S  /  FIRST-RUN SETUP")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eyebrow.setStyleSheet(
            "color: #71d4c2; background: transparent; font: 700 9pt 'Consolas'; "
            "letter-spacing: 1px; border: none;"
        )
        layout.addWidget(eyebrow)

        title = QLabel("Connect Gemini Live")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        title.setStyleSheet(
            "color: #edf3e8; background: transparent; font: 700 19pt 'Aptos Display'; "
            "border: none;"
        )
        layout.addWidget(title)

        subtitle = QLabel("Add one API key to get JARVIS online.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            "color: #9aafaa; background: transparent; font: 10pt 'Aptos'; border: none;"
        )
        layout.addWidget(subtitle)
        layout.addSpacing(7)

        caption = QLabel("GEMINI API KEY  ·  REQUIRED")
        caption.setStyleSheet(
            "color: #9aafaa; background: transparent; font: 700 8pt 'Consolas'; border: none;"
        )
        layout.addWidget(caption)

        key_row = QHBoxLayout()
        key_row.setSpacing(7)
        self._key_fields = {}
        field = QLineEdit()
        field.setObjectName("GeminiApiKeyField")
        field.setEchoMode(QLineEdit.EchoMode.Password)
        if self._allow_keep_existing and self._existing_gemini_key:
            field.setPlaceholderText("Saved locally · leave blank to keep")
        elif self._existing_gemini_key:
            field.setPlaceholderText("Paste a replacement Gemini API key")
        else:
            field.setPlaceholderText("Paste your Gemini API key")
        field.setMinimumHeight(40)
        field.setFont(QFont("Consolas", 10))
        field.setStyleSheet("""
            QLineEdit#GeminiApiKeyField {
                background: #071017; color: #edf3e8;
                border: 1px solid #34464a; border-radius: 7px; padding: 8px 10px;
                selection-background-color: #397f78;
            }
            QLineEdit#GeminiApiKeyField:focus { border: 1px solid #71d4c2; }
        """)
        field.returnPressed.connect(self._submit)
        key_row.addWidget(field, 1)
        self._key_fields["gemini_api_key"] = field
        self._key_field = field

        self._show_key_button = QToolButton()
        self._show_key_button.setText("SHOW")
        self._show_key_button.setCheckable(True)
        self._show_key_button.setMinimumHeight(40)
        self._show_key_button.setToolTip("Show or hide the API key")
        self._show_key_button.setStyleSheet("""
            QToolButton {
                color: #71d4c2; background: #10191d;
                border: 1px solid #34464a; border-radius: 7px;
                padding: 0 11px; font: 700 8pt 'Consolas';
            }
            QToolButton:hover { border-color: #71d4c2; background: #172d2c; }
            QToolButton:checked { color: #edf3e8; border-color: #71d4c2; }
        """)
        self._show_key_button.toggled.connect(self._toggle_key_visibility)
        key_row.addWidget(self._show_key_button)
        layout.addLayout(key_row)

        self._error_label = QLabel("Enter a Gemini API key to continue.")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            "color: #e97869; background: transparent; font: 9pt 'Aptos'; border: none;"
        )
        self._error_label.hide()
        layout.addWidget(self._error_label)

        note = QLabel("Your API key is saved locally on this computer. No other AI provider keys are required here.")
        note.setWordWrap(True)
        note.setStyleSheet(
            "color: #78908d; background: transparent; font: 9pt 'Aptos'; border: none;"
        )
        layout.addSpacing(3)
        layout.addWidget(note)

        connect_btn = QPushButton("SAVE KEY  &  CONTINUE")
        connect_btn.setObjectName("ConnectGeminiButton")
        connect_btn.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        connect_btn.setMinimumHeight(42)
        connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        connect_btn.setStyleSheet("""
            QPushButton#ConnectGeminiButton {
                background: #71d4c2; color: #061018;
                border: 1px solid #71d4c2; border-radius: 7px;
                padding: 9px 14px;
            }
            QPushButton#ConnectGeminiButton:hover { background: #9be8d9; border-color: #9be8d9; }
            QPushButton#ConnectGeminiButton:pressed { background: #397f78; color: #ffffff; }
        """)
        connect_btn.clicked.connect(self._submit)
        layout.addSpacing(6)
        layout.addWidget(connect_btn)

    def _toggle_key_visibility(self, visible: bool) -> None:
        self._key_field.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self._show_key_button.setText("HIDE" if visible else "SHOW")

    def _submit(self) -> None:
        # Existing credentials may only be retained in a normal setup/review.
        # Recovery from a rejected/missing key must force the user to enter a new one.
        entered_key = self._key_field.text().strip()
        key = entered_key or (
            self._existing_gemini_key if self._allow_keep_existing else ""
        )
        if not key:
            self._key_field.setStyleSheet(self._key_field.styleSheet() + """
                QLineEdit#GeminiApiKeyField { border: 1px solid #e97869; }
            """)
            self._error_label.show()
            self._key_field.setFocus()
            return
        self._error_label.hide()
        self.done.emit({"gemini_api_key": key})


class HueWheel(QWidget):
    """
    Circular colour picker. The user drags the handle (small white circle)
    around the wheel to choose from ALL hues. The filled circle in the centre
    is a live preview of the selected colour.
    """

    hue_picked    = pyqtSignal(str)   # while dragging (live)
    hue_committed = pyqtSignal(str)   # when the handle is released

    _RING = 16   # ring thickness (px)

    def __init__(self, initial_hex: str = DEFAULT_UI_COLOR, parent=None):
        super().__init__(parent)
        self.setFixedSize(148, 148)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hue  = 0.53
        self._drag = False
        self.set_color(initial_hex)

    # ── API ──────────────────────────────────────────────────────────────────
    def color(self) -> str:
        return QColor.fromHsvF(self._hue, 1.0, 1.0).name()

    def set_color(self, hex_str: str):
        c = QColor((hex_str or "").strip())
        if c.isValid() and c.hsvHueF() >= 0:
            self._hue = c.hsvHueF()
            self.update()

    # ── geometry helpers ─────────────────────────────────────────────────────
    def _ring_rect(self) -> QRectF:
        m = self._RING / 2 + 3
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def _hue_from_pos(self, pos: QPointF) -> float:
        c  = QRectF(self.rect()).center()
        dx = pos.x() - c.x()
        dy = c.y() - pos.y()          # screen y goes down — flip to math axis
        ang = math.atan2(dy, dx)      # [-π, π], counter-clockwise
        return (ang / (2 * math.pi)) % 1.0

    # ── drawing ──────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect   = self._ring_rect()
        center = rect.center()

        grad = QConicalGradient(center, 0)
        for i in range(0, 361, 20):
            grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
        p.setPen(QPen(QBrush(grad), self._RING))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        # centre preview circle
        preview = QColor.fromHsvF(self._hue, 1.0, 1.0)
        inner   = rect.adjusted(30, 30, -30, -30)
        p.setPen(QPen(qcol(C.BORDER_B), 1))
        p.setBrush(QBrush(preview))
        p.drawEllipse(inner)

        # draggable handle
        r   = rect.width() / 2
        ang = self._hue * 2 * math.pi
        hx  = center.x() + r * math.cos(ang)
        hy  = center.y() - r * math.sin(ang)
        p.setPen(QPen(QColor("#00060a"), 2))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPointF(hx, hy), 7.5, 7.5)
        p.end()

    # ── fare ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        self._drag = True
        self._hue  = self._hue_from_pos(e.position())
        self.update()
        self.hue_picked.emit(self.color())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._hue = self._hue_from_pos(e.position())
            self.update()
            self.hue_picked.emit(self.color())

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.hue_committed.emit(self.color())


class CustomizeOverlay(QWidget):
    """Floating overlay — change assistant name, user name, UI colour and voice."""

    saved = pyqtSignal(str, str, str, str)   # assistant_name, user_name, ui_color, voice
    _OW, _OH = 400, 588

    def __init__(self, assistant_name="JARVIS", user_name="",
                 ui_color=DEFAULT_UI_COLOR, voice="", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            CustomizeOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(8)

        def _lbl(txt, fs=9, bold=False, color=C.PRI, align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt); w.setAlignment(align)
            w.setFont(QFont("Courier New", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        _fs = (f"QLineEdit {{ background: #000d12; color: {C.TEXT}; "
               f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
               f"QLineEdit:focus {{ border: 1px solid {C.PRI}; }}")

        lay.addWidget(_lbl("⚙  CUSTOMISE ASSISTANT", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_lbl("ASSISTANT NAME", 8, color=C.TEXT_DIM,
                            align=Qt.AlignmentFlag.AlignLeft))
        self._name_input = QLineEdit(assistant_name)
        self._name_input.setFont(QFont("Courier New", 10))
        self._name_input.setFixedHeight(32)
        self._name_input.setStyleSheet(_fs)
        lay.addWidget(self._name_input)

        lay.addSpacing(4)
        lay.addWidget(_lbl("YOUR NAME  (leave blank for default sir / efendim)", 8,
                            color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        self._user_input = QLineEdit(user_name)
        self._user_input.setPlaceholderText("e.g.  Tony   (leave blank for auto)")
        self._user_input.setFont(QFont("Courier New", 10))
        self._user_input.setFixedHeight(32)
        self._user_input.setStyleSheet(_fs)
        lay.addWidget(self._user_input)

        # ── Assistant voice — Gemini prebuilt voices ─────────────────────────
        # Names are language-neutral proper nouns, so the row reads the same in
        # every locale. Selecting one and applying rebuilds the Live session.
        from jarvis.memory.config_manager import AVAILABLE_VOICES, DEFAULT_VOICE
        lay.addSpacing(4)
        lay.addWidget(_lbl("ASSISTANT VOICE", 8, color=C.TEXT_DIM,
                            align=Qt.AlignmentFlag.AlignLeft))
        self._sel_voice   = (voice or DEFAULT_VOICE)
        if self._sel_voice not in AVAILABLE_VOICES:
            self._sel_voice = DEFAULT_VOICE
        self._voice_btns: dict[str, QPushButton] = {}
        voice_row = QHBoxLayout(); voice_row.setSpacing(4)
        for _v in AVAILABLE_VOICES:
            b = QPushButton(_v)
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, name=_v: self._on_voice_pick(name))
            self._voice_btns[_v] = b
            voice_row.addWidget(b)
        lay.addLayout(voice_row)
        self._refresh_voice_btns()

        # ── UI colour — colour wheel ─────────────────────────────────────────
        lay.addSpacing(4)
        clr_hdr = QHBoxLayout()
        clr_hdr.addWidget(_lbl("UI COLOUR  —  drag the handle", 8,
                               color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        clr_hdr.addStretch()
        df_btn = QPushButton("DEFAULT")
        df_btn.setFixedSize(64, 20)
        df_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        df_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        df_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        df_btn.clicked.connect(lambda: self._set_color(DEFAULT_UI_COLOR))
        clr_hdr.addWidget(df_btn)
        lay.addLayout(clr_hdr)

        self._initial_color = (ui_color or DEFAULT_UI_COLOR).strip().lower()
        self._sel_color     = self._initial_color
        self.on_preview     = None   # callable(hex) — live preview; MainWindow wires it

        self._wheel = HueWheel(self._sel_color)
        wheel_row = QHBoxLayout()
        wheel_row.addStretch(); wheel_row.addWidget(self._wheel); wheel_row.addStretch()
        lay.addLayout(wheel_row)
        self._wheel.hue_picked.connect(self._on_wheel_pick)
        self._wheel.hue_committed.connect(self._on_wheel_commit)

        self._hex_input = QLineEdit(self._sel_color)
        self._hex_input.setPlaceholderText("#00d4ff   (custom hex colour)")
        self._hex_input.setFont(QFont("Courier New", 10))
        self._hex_input.setFixedHeight(28)
        self._hex_input.setStyleSheet(_fs)
        self._hex_input.textEdited.connect(self._on_hex_edited)
        lay.addWidget(self._hex_input)

        lay.addSpacing(6)
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)

        save_btn = QPushButton("▸  APPLY CHANGES")
        save_btn.setFixedHeight(34)
        save_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setFont(QFont("Courier New", 9))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    # ── voice selection ──────────────────────────────────────────────────────
    def _on_voice_pick(self, name: str):
        self._sel_voice = name
        self._refresh_voice_btns()

    def _refresh_voice_btns(self):
        """Highlight the selected voice pill; dim the rest."""
        for name, b in self._voice_btns.items():
            on = (name == self._sel_voice)
            b.setChecked(on)
            if on:
                b.setStyleSheet(f"""
                    QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI};
                        border: 1px solid {C.PRI}; border-radius: 3px; }}
                """)
            else:
                b.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {C.TEXT_MED};
                        border: 1px solid {C.BORDER}; border-radius: 3px; }}
                    QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
                """)

    # ── colour flow ──────────────────────────────────────────────────────────
    def _set_color(self, hx: str, update_wheel: bool = True, preview: bool = True):
        """Updates the selected colour; hex box + wheel stay in sync, theme is live-previewed."""
        self._sel_color = hx.strip().lower()
        self._hex_input.blockSignals(True)
        self._hex_input.setText(self._sel_color)
        self._hex_input.blockSignals(False)
        if update_wheel:
            self._wheel.set_color(self._sel_color)
        if preview and self.on_preview:
            self.on_preview(self._sel_color)

    def _on_wheel_pick(self, hx: str):
        # While dragging: update the hex box, don't apply the theme yet
        self._sel_color = hx
        self._hex_input.blockSignals(True)
        self._hex_input.setText(hx)
        self._hex_input.blockSignals(False)

    def _on_wheel_commit(self, hx: str):
        # Handle released → live-preview the whole interface
        self._set_color(hx, update_wheel=False)

    def _on_hex_edited(self, text: str):
        t = text.strip().lower()
        if t.startswith("#") and len(t) == 7:
            try:
                int(t[1:], 16)
            except ValueError:
                return
            self._set_color(t, update_wheel=True, preview=True)

    def _cancel(self):
        # If a preview was applied, revert to the colour from launch
        if self.on_preview and self._sel_color != self._initial_color:
            self.on_preview(self._initial_color)
        self.hide()

    def _save(self):
        name = self._name_input.text().strip() or "JARVIS"
        user = self._user_input.text().strip()
        self.saved.emit(name, user, self._sel_color or DEFAULT_UI_COLOR, self._sel_voice)
        self.hide()


class VoicePersonalityOverlay(QWidget):
    """Editor for response style profiles stored in local long-term memory."""

    saved = pyqtSignal(object)
    preview_requested = pyqtSignal(object)
    _OW = 460

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        from jarvis.memory.voice_personality import MODE_DEFINITIONS

        self._modes = MODE_DEFINITIONS
        self._settings = dict(settings or {})
        self._settings["tuning"] = dict(self._settings.get("tuning") or {})
        self._settings["vocal"] = dict(self._settings.get("vocal") or {})
        self._editing_mode = str(self._settings.get("mode", "conversational"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(self._OW)
        parent_height = parent.height() if parent is not None else 760
        self.setMaximumHeight(max(480, min(820, parent_height - 24)))
        self.setStyleSheet(f"VoicePersonalityOverlay {{ background: rgba(7, 13, 16, 248); border: 1px solid {C.BORDER_B}; border-radius: 6px; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;} QWidget#VoicePersonalityContent{background:transparent;}")
        content = QWidget()
        content.setObjectName("VoicePersonalityContent")
        scroll.setWidget(content)
        outer.addWidget(scroll)
        lay = QVBoxLayout(content)
        lay.setContentsMargins(22, 17, 22, 17)
        lay.setSpacing(8)

        def label(text, color=C.TEXT_DIM, size=8, bold=False):
            w = QLabel(text)
            w.setFont(QFont("Courier New", size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        header = label("◈  RESPONSE PERSONALITY", C.PRI, 11, True)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(header)
        lay.addWidget(label("Choose a response mode and tune its speaking style."))

        lay.addWidget(label("ACTIVE MODE"))
        self._mode = QComboBox()
        self._mode.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._mode.setFixedHeight(32)
        self._mode.setStyleSheet(f"QComboBox {{ background: #081216; color: {C.TEXT}; border: 1px solid {C.BORDER}; padding: 4px 8px; }} QComboBox QAbstractItemView {{ background: #0b1519; color: {C.TEXT}; selection-background-color: {C.PRI_GHO}; }}")
        for mode_id, item in self._modes.items():
            self._mode.addItem(item["label"], mode_id)
        idx = self._mode.findData(self._editing_mode)
        self._mode.setCurrentIndex(max(0, idx))
        lay.addWidget(self._mode)

        self._description = label("", C.TEXT_MED)
        self._description.setWordWrap(True)
        lay.addWidget(self._description)

        self._name_label = label("CUSTOM PROFILE NAME")
        lay.addWidget(self._name_label)
        self._name = QLineEdit(str(self._settings.get("custom_name", "My profile")))
        self._name.setMaxLength(40)
        self._name.setPlaceholderText("e.g. Mission Control")
        self._name.setFixedHeight(30)
        self._name.setFont(QFont("Courier New", 9))
        self._name.setStyleSheet(f"QLineEdit {{ background: #081216; color: {C.TEXT}; border: 1px solid {C.BORDER}; padding: 4px 7px; }}")
        lay.addWidget(self._name)

        self._text_label = label("PERSONAL TUNING FOR THIS MODE")
        lay.addWidget(self._text_label)
        self._text = QTextEdit()
        self._text.setAcceptRichText(False)
        self._text.setMaximumHeight(150)
        self._text.setFont(QFont("Courier New", 9))
        self._text.setPlaceholderText("How should JARVIS phrase replies? Keep instructions focused on tone, length, or format.")
        self._text.setStyleSheet(f"QTextEdit {{ background: #081216; color: {C.TEXT}; border: 1px solid {C.BORDER}; padding: 6px; }}")
        lay.addWidget(self._text)
        lay.addWidget(label("Response and vocal controls stay in local memory · custom instructions max 1,200 characters", C.TEXT_DIM, 7))

        rule = QFrame(); rule.setFrameShape(QFrame.Shape.HLine)
        rule.setStyleSheet(f"color:{C.BORDER}; margin:3px 0;")
        lay.addWidget(rule)
        lay.addWidget(label("VOCAL BEHAVIOR ENGINE", C.PRI, 9, True))
        lay.addWidget(label("Gemini streams the speech; optional breath texture is generated locally.", C.TEXT_DIM, 7))

        from jarvis.core.vocal_behavior import normalize_settings
        vocal = normalize_settings(self._settings.get("vocal"))
        self._vocal_checks = {}
        check_row = QHBoxLayout()
        for key, text in (("enabled", "ENGINE"), ("breathing", "BREATH"),
                          ("sighs", "SIGHS"), ("laughter", "REACTIONS")):
            check = QCheckBox(text)
            check.setChecked(vocal[key])
            check.setStyleSheet(f"QCheckBox{{color:{C.TEXT_MED};font:7pt 'Courier New';spacing:4px;}} QCheckBox::indicator{{width:12px;height:12px;}}")
            self._vocal_checks[key] = check
            check_row.addWidget(check)
        lay.addLayout(check_row)

        profile_row = QHBoxLayout()
        profile_row.addWidget(label("VOCAL PROFILE", C.TEXT_DIM, 7))
        self._vocal_profile = QComboBox()
        self._vocal_profile.setStyleSheet(f"QComboBox{{background:#081216;color:{C.TEXT};border:1px solid {C.BORDER};padding:3px;}} QComboBox QAbstractItemView{{background:#0b1519;color:{C.TEXT};}}")
        for profile_id, title in (("professional", "Professional Jarvis"), ("natural", "Natural Companion"),
                                  ("expressive", "Expressive"), ("minimal", "Minimal")):
            self._vocal_profile.addItem(title, profile_id)
        self._vocal_profile.setCurrentIndex(max(0, self._vocal_profile.findData(vocal["profile"])))
        profile_row.addWidget(self._vocal_profile, 1)
        lay.addLayout(profile_row)

        self._vocal_sliders = {}
        for key, title in (("expressiveness", "Expressiveness"), ("pause_naturalness", "Pause naturalness"),
                           ("breath_volume", "Breath volume"), ("event_frequency", "Event frequency")):
            row = QHBoxLayout()
            row.addWidget(label(title.upper(), C.TEXT_DIM, 7))
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(vocal[key])
            slider.setStyleSheet(f"QSlider::groove:horizontal{{height:4px;background:{C.BORDER};}} QSlider::handle:horizontal{{width:12px;margin:-5px 0;background:{C.PRI};border-radius:6px;}} QSlider::sub-page:horizontal{{background:{C.PRI_DIM};}}")
            value_label = label(str(vocal[key]), C.TEXT_MED, 7)
            slider.valueChanged.connect(lambda value, target=value_label: target.setText(str(value)))
            self._vocal_sliders[key] = slider
            row.addWidget(slider, 1)
            row.addWidget(value_label)
            lay.addLayout(row)

        buttons = QHBoxLayout()
        preview = QPushButton("PREVIEW BREATH")
        preview.setFixedHeight(32)
        preview.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        preview.setStyleSheet(f"QPushButton{{color:{C.ACC2};background:transparent;border:1px solid {C.BORDER};border-radius:3px;}} QPushButton:hover{{border-color:{C.ACC2};}}")
        preview.clicked.connect(lambda: self.preview_requested.emit(self._collect_vocal_settings()))
        buttons.addWidget(preview)
        reset = QPushButton("RESET")
        reset.setFixedHeight(32)
        reset.setFont(QFont("Courier New", 7))
        reset.setStyleSheet(f"QPushButton{{color:{C.TEXT_MED};background:transparent;border:1px solid {C.BORDER};border-radius:3px;}}")
        reset.clicked.connect(self._reset_vocal_settings)
        buttons.addWidget(reset)
        save = QPushButton("▸  SAVE PROFILE")
        save.setFixedHeight(32)
        save.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        save.setStyleSheet(f"QPushButton {{ color: {C.PRI}; background: {C.PRI_GHO}; border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}")
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        cancel = QPushButton("CANCEL")
        cancel.setFixedHeight(32)
        cancel.setFont(QFont("Courier New", 8))
        cancel.setStyleSheet(f"QPushButton {{ color: {C.TEXT_MED}; background: transparent; border: 1px solid {C.BORDER}; border-radius: 3px; }}")
        cancel.clicked.connect(self.hide)
        buttons.addWidget(cancel)
        lay.addLayout(buttons)

        self._mode.currentIndexChanged.connect(self._change_mode)
        self._load_mode(self._editing_mode)
        self.adjustSize()

    def _store_current(self):
        text = self._text.toPlainText().strip()[:1200]
        if self._editing_mode == "custom":
            self._settings["custom_instructions"] = text
        else:
            self._settings.setdefault("tuning", {})[self._editing_mode] = text

    def _load_mode(self, mode_id):
        self._editing_mode = mode_id
        self._description.setText(self._modes[mode_id]["description"])
        custom = mode_id == "custom"
        self._name_label.setVisible(custom)
        self._name.setVisible(custom)
        self._text_label.setText("CUSTOM STYLE INSTRUCTIONS" if custom else "PERSONAL TUNING FOR THIS MODE")
        content = (self._settings.get("custom_instructions", "") if custom else
                   self._settings.get("tuning", {}).get(mode_id, ""))
        self._text.setPlainText(content)

    def _change_mode(self, _index):
        self._store_current()
        self._load_mode(str(self._mode.currentData() or "conversational"))

    def _save(self):
        self._store_current()
        self._settings["mode"] = str(self._mode.currentData() or "conversational")
        self._settings["custom_name"] = self._name.text().strip() or "My profile"
        self._settings["vocal"] = self._collect_vocal_settings()
        self.saved.emit(self._settings)
        self.hide()

    def _collect_vocal_settings(self) -> dict:
        from jarvis.core.vocal_behavior import normalize_settings
        result = {key: check.isChecked() for key, check in self._vocal_checks.items()}
        result["profile"] = str(self._vocal_profile.currentData() or "professional")
        result.update({key: slider.value() for key, slider in self._vocal_sliders.items()})
        return normalize_settings(result)

    def _reset_vocal_settings(self) -> None:
        from jarvis.core.vocal_behavior import DEFAULT_SETTINGS
        for key, check in self._vocal_checks.items():
            check.setChecked(bool(DEFAULT_SETTINGS[key]))
        self._vocal_profile.setCurrentIndex(max(0, self._vocal_profile.findData(DEFAULT_SETTINGS["profile"])))
        for key, slider in self._vocal_sliders.items():
            slider.setValue(int(DEFAULT_SETTINGS[key]))


class PluginManagerOverlay(QWidget):
    """Floating overlay — lists discovered plugins with per-plugin ON/OFF toggles."""

    _OW = 420

    def __init__(self, plugins: list[dict], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PluginManagerOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🧩  PLUGIN MANAGER")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        if not plugins:
            empty = QLabel("No plugins found in /plugins.")
            empty.setFont(QFont("Courier New", 8))
            empty.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(empty)

        for p in plugins:
            lay.addLayout(self._build_row(p))

        lay.addSpacing(4)
        close_btn = QPushButton("CLOSE")
        close_btn.setFixedHeight(30)
        close_btn.setFont(QFont("Courier New", 9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self.hide)
        lay.addWidget(close_btn)
        self.adjustSize()

    def _build_row(self, p: dict) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(6)

        label_text = p["name"] if p["valid"] else f"{p['name']}  (⚠ {p['file']})"
        lbl = QLabel(label_text)
        lbl.setFont(QFont("Courier New", 8))
        lbl.setStyleSheet(f"color: {C.TEXT if p['valid'] else C.TEXT_DIM}; background: transparent;")
        lbl.setToolTip(p["description"] if p["valid"] else p["error"])
        lbl.setWordWrap(False)
        row.addWidget(lbl, stretch=1)

        btn = QPushButton()
        btn.setFixedSize(72, 24)
        btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        if not p["valid"]:
            btn.setText("BROKEN")
            btn.setEnabled(False)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
            """)
        else:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._style_toggle(btn, p["enabled"])
            btn.clicked.connect(lambda _, name=p["name"], b=btn: self._toggle(name, b))
        row.addWidget(btn)
        return row

    def _style_toggle(self, btn: QPushButton, enabled: bool):
        if enabled:
            btn.setText("ON")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            btn.setText("OFF")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
            """)

    def _toggle(self, name: str, btn: QPushButton):
        from jarvis.memory.config_manager import get_plugin_enabled, save_plugin_enabled
        new_val = not get_plugin_enabled(name)
        save_plugin_enabled(name, new_val)
        self._style_toggle(btn, new_val)


class _HudOverlay(QWidget):
    """Base for the floating panels placed by hand over the HUD.

    They are children of the central widget but sit in no layout, so Qt never
    invalidates the region they occupy when they hide or shrink: the HUD keeps
    painting around them and their last frame stays on screen as a ghost. Any
    overlay positioned with _centre_overlay needs this."""

    def hideEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            # Repaint exactly what we were covering, before we stop covering it.
            p.update(self.geometry())
        super().hideEvent(e)

    def closeEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            p.update(self.geometry())
        super().closeEvent(e)


class ConfirmBanner(_HudOverlay):
    """The gate in front of an action that cannot be taken back.

    The old confirmation was a tool parameter the model filled in itself, which
    means it confirmed its own shutdown requests. This is the interface asking,
    and the answer travels from a human finger to core/confirm.py without the
    model in the loop. Nothing blocks while it is up: the assistant keeps
    talking, so this costs no latency — unlike the old gate, which spent two
    tool round trips on every power command."""

    answered = pyqtSignal(bool)
    _OW = 430

    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ConfirmBanner {{
                background: rgba(14, 3, 0, 250);
                border: 1px solid {C.ACC};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        hdr = QLabel("⚠  CONFIRM")
        hdr.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.ACC}; background: transparent;")
        lay.addWidget(hdr)

        ttl = QLabel(title)
        ttl.setWordWrap(True)
        ttl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        ttl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(ttl)

        if detail:
            if title == "Instagram account access":
                # DMs and captions must be visible in full before approval.
                # Keep the overlay compact and let long content scroll.
                dtl = QTextEdit()
                dtl.setReadOnly(True)
                dtl.setPlainText(detail)
                dtl.setFixedHeight(170)
                dtl.setFont(QFont("Courier New", 8))
                dtl.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: {C.PANEL}; "
                    f"border: 1px solid {C.BORDER};"
                )
                lay.addWidget(dtl)
            else:
                dtl = QLabel(detail)
                dtl.setWordWrap(True)
                dtl.setFont(QFont("Courier New", 8))
                dtl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
                lay.addWidget(dtl)

        voice_hint = QLabel("VOICE: say CONFIRM ACTION or CANCEL ACTION")
        voice_hint.setWordWrap(True)
        voice_hint.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        voice_hint.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        lay.addWidget(voice_hint)

        row = QHBoxLayout(); row.setSpacing(8)

        yes = QPushButton("▸  CONFIRM")
        yes.setFixedHeight(32)
        yes.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        yes.setCursor(Qt.CursorShape.PointingHandCursor)
        yes.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.ACC};
                border: 1px solid {C.ACC}; border-radius: 3px; }}
            QPushButton:hover {{ background: rgba(255,107,0,40); }}
        """)
        yes.clicked.connect(lambda: self.answered.emit(True))
        row.addWidget(yes)

        no = QPushButton("CANCEL")
        no.setFixedHeight(32)
        no.setFont(QFont("Courier New", 9))
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        no.clicked.connect(lambda: self.answered.emit(False))
        row.addWidget(no)
        lay.addLayout(row)

        # Default focus on CANCEL: if someone hits Enter without reading, the
        # safe answer wins.
        no.setDefault(True)
        no.setFocus()


class AudioDeviceOverlay(_HudOverlay):
    """Choose which microphone JARVIS listens to and which speakers it uses.

    Both audio streams used to open with no `device=` at all, so they always
    took the OS default — which on Windows moves by itself the moment a headset
    is plugged in. 'JARVIS can't hear me' is usually 'JARVIS is listening to the
    webcam'."""

    picked = pyqtSignal()      # emitted after Apply, when something changed
    _OW = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        from jarvis.core.audio_devices import list_devices, DEFAULT_LABEL
        from jarvis.memory.config_manager import get_input_device, get_output_device

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AudioDeviceOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🎧  AUDIO DEVICES")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        _combo_css = (
            f"QComboBox {{ background: #000d12; color: {C.TEXT}; "
            f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
            f"QComboBox:hover {{ border-color: {C.BORDER_B}; }}"
            f"QComboBox QAbstractItemView {{ background: #000d12; color: {C.TEXT}; "
            f"selection-background-color: {C.PRI_GHO}; border: 1px solid {C.BORDER}; }}"
        )

        def _row(label: str, kind: str, current: str) -> QComboBox:
            cap = QLabel(label)
            cap.setFont(QFont("Courier New", 8))
            cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(cap)

            box = QComboBox()
            box.setFont(QFont("Courier New", 9))
            box.setFixedHeight(30)
            box.setStyleSheet(_combo_css)
            # The list is served from a cache warmed on a background thread at
            # startup, so opening this panel never blocks the Qt thread on the
            # host audio API.
            box.addItem(DEFAULT_LABEL, "")
            for name in list_devices(kind):
                box.addItem(name, name)
            idx = box.findData(current) if current else 0
            box.setCurrentIndex(idx if idx >= 0 else 0)
            if current and idx < 0:
                # Saved device is not plugged in right now. Show it rather than
                # silently resetting the user's choice to default.
                box.addItem(f"{current}  (not connected)", current)
                box.setCurrentIndex(box.count() - 1)
            lay.addWidget(box)
            return box

        self._in_box  = _row("MICROPHONE — what JARVIS hears you with",
                             "input", get_input_device())
        lay.addSpacing(4)
        self._out_box = _row("SPEAKERS — what JARVIS talks through",
                             "output", get_output_device())

        note = QLabel("Applying reconnects the session. Your conversation is kept.")
        note.setWordWrap(True)
        note.setFont(QFont("Courier New", 7))
        note.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addSpacing(6)
        lay.addWidget(note)

        row = QHBoxLayout(); row.setSpacing(8)
        ok = QPushButton("▸  APPLY")
        ok.setFixedHeight(32)
        ok.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """)
        ok.clicked.connect(self._apply)
        row.addWidget(ok)

        cancel = QPushButton("CLOSE")
        cancel.setFixedHeight(32)
        cancel.setFont(QFont("Courier New", 9))
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel.clicked.connect(self.hide)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _apply(self):
        from jarvis.memory.config_manager import (
            get_input_device, get_output_device,
            save_input_device, save_output_device,
        )
        new_in  = self._in_box.currentData()  or ""
        new_out = self._out_box.currentData() or ""
        changed = (new_in != get_input_device()) or (new_out != get_output_device())
        save_input_device(new_in)
        save_output_device(new_out)
        self.hide()
        # Only rebuild the session if something actually moved — a no-op Apply
        # should not cost a reconnect.
        if changed:
            self.picked.emit()


class MemoryOverlay(_HudOverlay):
    """Everything JARVIS has stored about you, and when it learned it.

    Memory used to be a 2200-character store that deleted its oldest entries
    when full and mentioned it only on stdout. The cap is gone; this panel is
    the other half of that change — a memory you cannot inspect is a memory you
    cannot trust, and 'delete' has to be something the person can do."""

    _OW = 520

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            MemoryOverlay {{
                background: rgba(0, 6, 10, 246);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 16)
        self._lay.setSpacing(5)
        self._rebuild()

    def _clear_layout(self):
        """Take every item out of the layout and detach it from the widget tree
        in this call.

        deleteLater() on its own is not enough: it queues destruction for the
        next event-loop pass, and until then the old rows are still children of
        this widget and still paint — which is what drew half of the previous
        panel over the new one. setParent(None) removes them from the tree now;
        deleteLater() then frees them safely."""
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # hide() stops it painting in this frame; deleteLater() frees it
                # safely afterwards. setParent(None) would also stop the paint,
                # but it turns the widget into a top-level window for the moment
                # between the two calls, which is not something to leave lying
                # around inside a click handler.
                w.hide()
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    si = sub.takeAt(0)
                    sw = si.widget()
                    if sw is not None:
                        sw.hide()
                        sw.deleteLater()
                sub.deleteLater()

    def _settle(self, before):
        """Size the panel to its content, re-centre it, and repaint what the old
        size covered.

        The re-size has to happen here rather than at the end of _rebuild
        because Qt has not polished the freshly-created children at that point,
        so the size hint it would read is the empty-layout one. Measured: a
        first adjustSize() returned 32 px for a panel whose content needed 155,
        and a second call — after the same widgets had been through the event
        loop — returned 155. So this runs twice: once now, once on the next
        turn, from _rebuild.

        The re-centre and the repaint are needed because the overlay is placed
        by hand and is in no layout: shrinking it leaves it off-centre and
        leaves its former pixels on screen, since nothing tells the parent that
        region changed. The repaint has to cover the union of the old and new
        rectangles."""
        self._lay.invalidate()
        self._lay.activate()
        self.updateGeometry()
        self.adjustSize()

        p = self.parentWidget()
        if p is None:
            self.update()
            return
        self.move(max(0, (p.width()  - self.width())  // 2),
                  max(0, (p.height() - self.height()) // 2))
        p.update(before.united(self.geometry()))
        self.update()

    def _rebuild(self):
        before = self.geometry()
        self._clear_layout()

        from jarvis.memory.memory_manager import all_entries_for_ui
        from html import escape

        hdr = QLabel("🧠  WHAT JARVIS REMEMBERS")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        self._lay.addWidget(sep)

        rows = all_entries_for_ui()

        from jarvis.memory.config_manager import get_memory_provider_access_enabled
        provider_memory_enabled = get_memory_provider_access_enabled()
        privacy_note = (
            "AI-provider memory access is ON: redacted memory and recent turns may be sent."
            if provider_memory_enabled else
            "AI-provider memory access is OFF: stored memory stays out of automatic requests."
        )
        cap = QLabel(f"{len(rows)} memories — newest first. Stored in "
                     f"memory/long_term.json on this machine. {privacy_note} "
                     f"When enabled, common credentials and contact identifiers are "
                     f"redacted before memory requests are sent.")
        cap.setWordWrap(True)
        cap.setFont(QFont("Courier New", 7))
        cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._lay.addWidget(cap)

        from jarvis.memory.config_manager import (
            get_memory_provider_access_enabled, save_memory_provider_access_enabled,
        )
        self._memory_provider_checkbox = QCheckBox(
            "Allow AI-provider access to redacted memory"
        )
        self._memory_provider_checkbox.setChecked(get_memory_provider_access_enabled())
        self._memory_provider_checkbox.setToolTip(
            "Off (default): memory is omitted from automatic AI prompts, contextual "
            "recall results are withheld, and episode summaries are created locally. "
            "On: JARVIS redacts common credentials and contact identifiers before "
            "including relevant memory or up to 40 recent conversation lines in AI requests. "
            "Redaction uses patterns and may miss unusual sensitive data; review before enabling."
        )
        self._memory_provider_checkbox.setStyleSheet(
            f"QCheckBox {{ color: {C.TEXT_MED}; background: transparent; spacing: 6px; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
            f"QCheckBox::indicator:unchecked {{ border: 1px solid {C.BORDER_B}; background: {C.PANEL2}; }}"
            f"QCheckBox::indicator:checked {{ border: 1px solid {C.PRI}; background: {C.PRI_DIM}; }}"
        )
        self._memory_provider_checkbox.toggled.connect(save_memory_provider_access_enabled)
        self._lay.addWidget(self._memory_provider_checkbox)

        if not rows:
            empty = QLabel("Nothing stored yet.")
            empty.setFont(QFont("Courier New", 9))
            empty.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            self._lay.addWidget(empty)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFixedHeight(min(420, 34 * len(rows) + 10))
            scroll.setStyleSheet(
                f"QScrollArea {{ border: 1px solid {C.BORDER}; border-radius: 3px; "
                f"background: transparent; }}"
            )
            inner = QWidget()
            ilay  = QVBoxLayout(inner)
            ilay.setContentsMargins(6, 6, 6, 6)
            ilay.setSpacing(3)

            for r in rows:
                line = QHBoxLayout(); line.setSpacing(6)
                meta_parts = [r.get("category", "memory")]
                if r.get("memory_record"):
                    meta_parts.extend((r.get("type", "semantic"), r.get("source", "unknown"),
                                       f"claim {round(float(r.get('confidence', 0)) * 100)}%",
                                       r.get("verification_status", "unverified"),
                                       f"privacy {r.get('privacy_class', 'personal')}"))
                    if r.get("summary_confidence") is not None:
                        meta_parts.append(f"summary {round(float(r['summary_confidence']) * 100)}%")
                    if r.get("last_verified_at"):
                        meta_parts.append(f"verified {str(r['last_verified_at'])[:10]}")
                    if r.get("source_history"):
                        origin = r["source_history"][0]
                        meta_parts.append(f"origin {origin.get('source', 'unknown')} · {origin.get('why', '')[:55]}")
                    if r.get("change_history"):
                        change = r["change_history"][-1]
                        meta_parts.append(f"last change {change.get('action', '')} · {change.get('why', '')[:55]}")
                    if r.get("supporting_episode_ids"):
                        meta_parts.append("supports " + ",".join(r["supporting_episode_ids"][:2]))
                    if r.get("related_memory_ids"):
                        meta_parts.append("links " + ",".join(r["related_memory_ids"][:2]))
                    if r.get("conflicts", 0):
                        meta_parts.append(f"possible conflicts {r['conflicts']}")
                elif r.get("category") == "response_usage":
                    meta_parts.append(f"context {r.get('source', 'response')}")
                meta = QLabel(" · ".join(escape(str(part)) for part in meta_parts)
                              + f" · {escape(str(r.get('updated') or '—'))}")
                meta.setWordWrap(True)
                meta.setFont(QFont("Courier New", 7))
                meta.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
                txt = QLabel(f"<b>{escape(str(r['key']).replace('_', ' '))}</b> "
                             f"<span style='color:{C.TEXT_MED}'>— {escape(str(r['value']))}</span>")
                txt.setWordWrap(True)
                txt.setFont(QFont("Courier New", 8))
                txt.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
                line.addWidget(txt, 1)

                line.addWidget(meta)

                if r.get("memory_record"):
                    pin = QPushButton("PIN" if r.get("pinned") else "○")
                    pin.setFixedSize(30, 22)
                    pin.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
                    pin.setCursor(Qt.CursorShape.PointingHandCursor)
                    pin.setToolTip("Unpin retention" if r.get("pinned") else "Pin this memory")
                    pin.setStyleSheet(f"QPushButton {{ background: transparent; color: {C.PRI}; border: 1px solid {C.BORDER}; }}")
                    pin.clicked.connect(lambda _=False, mid=r.get("id", ""), value=not r.get("pinned", False): self._pin(mid, value))
                    line.addWidget(pin)

                rm = QPushButton("✕") if r.get("category") != "response_usage" else None
                if rm is not None:
                    rm.setFixedSize(20, 20)
                    rm.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
                    rm.setCursor(Qt.CursorShape.PointingHandCursor)
                    rm.setToolTip("Permanently delete this memory and linked copies")
                    rm.setStyleSheet(f"""
                        QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                            border: 1px solid {C.BORDER}; border-radius: 3px; }}
                        QPushButton:hover {{ color: {C.RED}; border-color: {C.RED}; }}
                    """)
                    rm.clicked.connect(
                        lambda _=False, c=r["category"], k=r.get("id", r["key"]): self._forget(c, k))
                    line.addWidget(rm)

                holder = QWidget()
                holder.setLayout(line)
                ilay.addWidget(holder)

            ilay.addStretch()
            scroll.setWidget(inner)
            self._lay.addWidget(scroll)

        close = QPushButton("CLOSE")
        close.setFixedHeight(30)
        close.setFont(QFont("Courier New", 9))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close.clicked.connect(self.hide)
        self._lay.addWidget(close)

        self._settle(before)
        # …and again once Qt has polished the new children, because the size
        # hint is not final until then. Harmless when the first pass already
        # got it right: _settle is idempotent.
        QTimer.singleShot(0, lambda g=before: self._settle(g))

    def _forget(self, category: str, key: str):
        from jarvis.memory.memory_manager import forget
        forget(key, category)
        # Rebuild on the NEXT event-loop turn, not inside this click handler.
        # The rebuild destroys the very ✕ button that emitted this signal, and
        # Qt is entitled to touch the sender after a slot returns; tearing it
        # down mid-emission is how a widget ends up half-alive on screen.
        QTimer.singleShot(0, self._rebuild)

    def _pin(self, memory_id: str, pinned: bool):
        from jarvis.memory.memory_lifecycle import pin_memory
        pin_memory(memory_id, pinned)
        QTimer.singleShot(0, self._rebuild)


class ClipboardPanel(QWidget):
    """Floating panel shown when text is copied — offers quick Jarvis actions."""

    action_requested = pyqtSignal(str)
    _W, _H = 326, 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ClipboardPanel {{
                background: rgba(0, 8, 14, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)
        self._clip_text = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 7)
        lay.setSpacing(4)

        hdr = QHBoxLayout(); hdr.setSpacing(4)
        icon_lbl = QLabel("◈  CLIPBOARD DETECTED")
        icon_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent;")
        hdr.addWidget(icon_lbl); hdr.addStretch()
        x_btn = QPushButton("✕")
        x_btn.setFixedSize(16, 16)
        x_btn.setFont(QFont("Courier New", 8))
        x_btn.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.clicked.connect(self.hide)
        hdr.addWidget(x_btn)
        lay.addLayout(hdr)

        self._preview = QLabel()
        self._preview.setFont(QFont("Courier New", 8))
        self._preview.setStyleSheet(f"""
            color: {C.TEXT}; background: {C.PANEL2};
            border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 6px;
        """)
        self._preview.setWordWrap(False)
        self._preview.setFixedHeight(28)
        lay.addWidget(self._preview)

        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        _bs = (f"QPushButton {{ background: {C.PANEL2}; color: {C.TEXT_MED}; "
               f"border: 1px solid {C.BORDER}; border-radius: 2px; }}"
               f"QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}")
        for label, cmd_fmt in [
            ("TRANSLATE", "Translate this text to English: {text}"),
            ("SUMMARISE", "Summarise this: {text}"),
            ("EXPLAIN",   "Explain this: {text}"),
            ("FIX",       "Fix grammar and spelling: {text}"),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(_bs)
            b.clicked.connect(lambda _, c=cmd_fmt: self._trigger(c))
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.hide)
        self.hide()

    def _trigger(self, cmd_fmt: str):
        if self._clip_text:
            self.action_requested.emit(cmd_fmt.format(text=self._clip_text[:800]))
        self.hide()

    def show_clipboard(self, text: str):
        self._clip_text = text
        preview = text[:58].replace('\n', ' ')
        if len(text) > 58:
            preview += "…"
        self._preview.setText(f'"{preview}"')
        self.show(); self.raise_()
        self._dismiss_timer.start(8000)


class PluginSettingsOverlay(QWidget):
    """Floating overlay — renders per-plugin settings forms.

    Fully generic: it iterates the settings schemas a plugin declared via its
    PLUGIN_SETTINGS constant (delivered by PluginRegistry.settings_schemas) and
    builds a form for each. It knows NOTHING about any specific plugin, so the
    core stays clean and plugins remain pure drop-in — install a plugin that
    declares fields (e.g. the 3D-printer suite) and its section appears here;
    install none and this panel simply says there's nothing to configure.
    """

    _test_done = pyqtSignal(str, bool, str)   # namespace, ok, message
    _OW = 460

    def __init__(self, sections: list[dict], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PluginSettingsOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self._sections = sections or []
        self._widgets: dict[tuple, object] = {}    # (namespace, key) -> input widget
        self._types:   dict[tuple, str]    = {}     # (namespace, key) -> field type
        self._status_labels: dict[str, QLabel] = {} # namespace -> status QLabel
        self._test_done.connect(self._on_test_done)

        self._fs = (f"QLineEdit {{ background: #000d12; color: {C.TEXT}; "
                    f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
                    f"QLineEdit:focus {{ border: 1px solid {C.PRI}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 16)
        root.setSpacing(8)

        root.addWidget(self._lbl("⚙  PLUGIN SETTINGS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        root.addWidget(sep)

        if not self._sections:
            root.addWidget(self._lbl(
                "No configurable plugins are installed.\nDrop a plugin that needs "
                "settings (like the 3D-printer suite) into the plugins folder and "
                "it will show up here.", 9, color=C.TEXT_DIM))
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; }")
            inner = QWidget()
            inner.setStyleSheet("background: transparent;")
            form = QVBoxLayout(inner)
            form.setContentsMargins(0, 0, 6, 0)
            form.setSpacing(6)
            for sec in self._sections:
                self._build_section(form, sec)
            form.addStretch(1)
            scroll.setWidget(inner)
            root.addWidget(scroll, 1)

        # ── bottom buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        if self._sections:
            save_btn = QPushButton("▸  SAVE")
            save_btn.setFixedHeight(34)
            save_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            save_btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C.PRI};
                    border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
                QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
            """)
            save_btn.clicked.connect(self._save_all)
            btn_row.addWidget(save_btn)

        close_btn = QPushButton("CLOSE")
        close_btn.setFixedHeight(34)
        close_btn.setFont(QFont("Courier New", 9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self.hide)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ── helpers ───────────────────────────────────────────────────────────────
    def _lbl(self, txt, fs=9, bold=False, color=C.PRI,
             align=Qt.AlignmentFlag.AlignLeft):
        w = QLabel(txt); w.setAlignment(align); w.setWordWrap(True)
        w.setFont(QFont("Courier New", fs,
                        QFont.Weight.Bold if bold else QFont.Weight.Normal))
        w.setStyleSheet(f"color: {color}; background: transparent;")
        return w

    def _build_section(self, form: QVBoxLayout, sec: dict):
        ns     = sec.get("namespace") or sec.get("plugin") or "plugin"
        title  = sec.get("title") or ns
        fields = sec.get("fields") or []
        values = sec.get("values") or {}

        form.addSpacing(4)
        form.addWidget(self._lbl(title, 10, True, C.PRI))

        for field in fields:
            if not isinstance(field, dict) or not field.get("key"):
                continue
            key   = field["key"]
            ftype = (field.get("type") or "text").lower()
            label = field.get("label") or key
            default = field.get("default")
            stored  = values.get(key, default)

            form.addWidget(self._lbl(label.upper(), 8, color=C.TEXT_DIM))

            if ftype == "choice":
                w = QComboBox()
                w.addItems([str(o) for o in field.get("options", [])])
                w.setFont(QFont("Courier New", 9))
                w.setFixedHeight(30)
                w.setStyleSheet(
                    f"QComboBox {{ background: #000d12; color: {C.TEXT}; "
                    f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 2px 8px; }}"
                    f"QComboBox QAbstractItemView {{ background: #000d12; color: {C.TEXT}; "
                    f"selection-background-color: {C.PRI_GHO}; }}")
                if stored is not None:
                    w.setCurrentText(str(stored))
            elif ftype == "toggle":
                w = QPushButton()
                w.setCheckable(True)
                w.setChecked(bool(stored))
                w.setFixedHeight(28)
                w.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
                w.setCursor(Qt.CursorShape.PointingHandCursor)
                self._style_toggle(w)
                w.toggled.connect(lambda _=False, b=w: self._style_toggle(b))
            else:  # text / password
                w = QLineEdit("" if stored is None else str(stored))
                w.setFont(QFont("Courier New", 10))
                w.setFixedHeight(30)
                w.setStyleSheet(self._fs)
                if field.get("placeholder"):
                    w.setPlaceholderText(str(field["placeholder"]))
                if ftype == "password":
                    w.setEchoMode(QLineEdit.EchoMode.Password)

            self._widgets[(ns, key)] = w
            self._types[(ns, key)]   = ftype
            form.addWidget(w)

        # optional test/connect action button + status line
        action = sec.get("action")
        if isinstance(action, dict) and callable(action.get("run")):
            form.addSpacing(2)
            ab = QPushButton(str(action.get("label") or "TEST"))
            ab.setFixedHeight(30)
            ab.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            ab.setCursor(Qt.CursorShape.PointingHandCursor)
            ab.setStyleSheet(f"""
                QPushButton {{ background: #00091a; color: {C.PRI};
                    border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
                QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
            """)
            ab.clicked.connect(lambda _=False, n=ns: self._run_action(n))
            form.addWidget(ab)

        status = self._lbl("", 8, color=C.TEXT_DIM)
        self._status_labels[ns] = status
        form.addWidget(status)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {C.BORDER}; margin: 4px 0;")
        form.addWidget(line)

    def _style_toggle(self, btn: QPushButton):
        on = btn.isChecked()
        btn.setText("ON" if on else "OFF")
        if on:
            btn.setStyleSheet(f"QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI}; "
                              f"border: 1px solid {C.PRI}; border-radius: 3px; }}")
        else:
            btn.setStyleSheet(f"QPushButton {{ background: transparent; color: {C.TEXT_MED}; "
                              f"border: 1px solid {C.BORDER}; border-radius: 3px; }}")

    # ── data ──────────────────────────────────────────────────────────────────
    def _gather(self, ns: str) -> dict:
        out = {}
        for (n, key), w in self._widgets.items():
            if n != ns:
                continue
            t = self._types.get((n, key), "text")
            if t == "choice":
                out[key] = w.currentText()
            elif t == "toggle":
                out[key] = w.isChecked()
            else:
                out[key] = w.text().strip()
        return out

    def _save_ns(self, ns: str):
        from jarvis.memory.config_manager import save_plugin_config
        save_plugin_config(ns, self._gather(ns))

    def _save_all(self):
        for sec in self._sections:
            ns = sec.get("namespace") or sec.get("plugin")
            if ns:
                self._save_ns(ns)
                lbl = self._status_labels.get(ns)
                if lbl:
                    lbl.setText("Saved ✓")
                    lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")

    def _run_action(self, ns: str):
        sec = next((s for s in self._sections
                    if (s.get("namespace") or s.get("plugin")) == ns), None)
        if not sec:
            return
        run_fn = (sec.get("action") or {}).get("run")
        if not callable(run_fn):
            return
        self._save_ns(ns)                 # persist what the user typed before testing
        values = self._gather(ns)
        lbl = self._status_labels.get(ns)
        if lbl:
            lbl.setText("Testing…")
            lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")

        def worker():
            try:
                res = run_fn(values)
                if isinstance(res, tuple) and len(res) == 2:
                    ok, msg = bool(res[0]), str(res[1])
                else:
                    ok, msg = bool(res), str(res)
            except Exception as e:
                ok, msg = False, str(e)
            self._test_done.emit(ns, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_done(self, ns: str, ok: bool, msg: str):
        lbl = self._status_labels.get(ns)
        if not lbl:
            return
        lbl.setText(msg)
        color = C.PRI if ok else "#ff6b6b"
        lbl.setStyleSheet(f"color: {color}; background: transparent;")


class RemoteKeyOverlay(QWidget):
    """Floating overlay — QR code for instant phone pairing + manual key fallback."""

    closed = pyqtSignal()

    _OW, _OH = 400, 465

    def __init__(self, url: str, key: str, auto_login_url: str = "",
                 manual_url: str = "", expiry_secs: int = 600, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            RemoteKeyOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._expiry          = time.time() + expiry_secs
        self._on_new_key      = None
        self._auto_login_url  = auto_login_url
        self._manual_url      = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("◈  REMOTE ACCESS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        # ── QR code ───────────────────────────────────────────────────────────
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(176, 176)
        self._qr_label.setStyleSheet(
            "background: white; border-radius: 10px; padding: 4px;"
        )
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self._qr_label)
        qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url)

        lay.addWidget(_lbl("Scan with phone camera to connect instantly", 8, color=C.TEXT_DIM))

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_lbl("Or enter manually:", 7, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))

        self._url_lbl = QLabel(self._manual_url)
        self._url_lbl.setFont(QFont("Courier New", 8))
        self._url_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._url_lbl)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(QFont("Courier New", 28, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.ACC};
            background: {C.PANEL2};
            border: 1px solid {C.BORDER_B};
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 10px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(QFont("Courier New", 8))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        new_btn = QPushButton("NEW KEY")
        new_btn.setFixedHeight(32)
        new_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        new_btn.clicked.connect(self._refresh_key)
        btn_row.addWidget(new_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._tick)
        self._ctimer.start(1000)
        self._tick()

    def set_new_key_callback(self, fn) -> None:
        self._on_new_key = fn

    def _update_qr(self, url: str) -> None:
        if not url:
            self._qr_label.setText("—")
            return
        try:
            import qrcode as _qrmod
            from io import BytesIO
            qr = _qrmod.QRCode(
                box_size=5, border=2,
                error_correction=_qrmod.constants.ERROR_CORRECT_M,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(170, 170,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        except ImportError:
            self._qr_label.setText("pip install\nqrcode[pil]")
            self._qr_label.setFont(QFont("Courier New", 8))
            self._qr_label.setStyleSheet(
                "color: #888; background: white; border-radius: 10px; padding: 4px;"
            )
        except Exception:
            self._qr_label.setText(url[:28])
            self._qr_label.setFont(QFont("Courier New", 7))
            self._qr_label.setStyleSheet(
                f"color: {C.PRI}; background: white; border-radius: 10px; padding: 4px;"
            )

    def _tick(self):
        remaining = max(0, int(self._expiry - time.time()))
        m, s = divmod(remaining, 60)
        self._timer_lbl.setText(f"Key expires in  {m:02d}:{s:02d}")
        if remaining == 0:
            self._do_close()

    def mark_connected(self) -> None:
        """Call from any thread when a phone successfully connects."""
        self._ctimer.stop()
        self._key_lbl.setText("CONNECTED")
        self._key_lbl.setStyleSheet(f"""
            color: {C.GREEN};
            background: rgba(34,197,94,0.08);
            border: 2px solid rgba(34,197,94,0.4);
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 4px;
        """)
        self._qr_label.setText("✓")
        self._qr_label.setFont(QFont("Courier New", 54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet(
            "color: #00ff88; background: #001a0d; border-radius: 10px;"
        )
        self._timer_lbl.setText("Phone connected — JARVIS ready")
        self._timer_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _refresh_key(self):
        if self._on_new_key:
            result = self._on_new_key()
            if result:
                url    = result[0]
                key    = result[1]
                auto   = result[2] if len(result) >= 3 else ""
                manual = result[3] if len(result) >= 4 else url
                self._manual_url     = manual or url
                self._url_lbl.setText(self._manual_url)
                self._key_lbl.setText(key)
                self._auto_login_url = auto
                self._update_qr(auto or url)
                self._expiry = time.time() + 600
                self._key_lbl.setStyleSheet(f"""
                    color: {C.ACC};
                    background: {C.PANEL2};
                    border: 1px solid {C.BORDER_B};
                    border-radius: 8px;
                    padding: 6px 4px;
                    letter-spacing: 10px;
                """)
                self._timer_lbl.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: transparent;"
                )
                self._ctimer.start(1000)
                self._tick()

    def _do_close(self):
        self._ctimer.stop()
        self.hide()
        self.closed.emit()


class AIProviderOverlay(_HudOverlay):
    """Choose the provider for one-shot reasoning and keep optional keys local."""

    saved = pyqtSignal(object)
    _OW, _OH = 520, 510

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings or {}
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AIProviderOverlay {{
                background: rgba(5, 12, 17, 250);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
            QLineEdit, QComboBox {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 5px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(7)

        def label(text, size=8, color=C.TEXT_DIM, bold=False):
            item = QLabel(text)
            item.setFont(QFont("Courier New", size,
                               QFont.Weight.Bold if bold else QFont.Weight.Normal))
            item.setStyleSheet(f"color: {color}; background: transparent;")
            item.setWordWrap(True)
            return item

        lay.addWidget(label("◈  MODEL PROVIDER", 12, C.PRI, True))
        lay.addWidget(label(
            "Selects the provider for one-shot reasoning, coding, and file analysis. "
            "Live voice, tool routing, and Google-grounded search continue using Gemini. "
            "Provider usage may be billed by the provider.",
            8, C.TEXT_MED,
        ))

        self._provider = QComboBox()
        for text, value in (
            ("Gemini  ·  current default", "gemini"),
            ("OpenAI  ·  GPT API", "openai"),
            ("Anthropic  ·  Claude API", "anthropic"),
        ):
            self._provider.addItem(text, value)
        current = str(self._settings.get("provider", "gemini"))
        idx = self._provider.findData(current)
        self._provider.setCurrentIndex(max(0, idx))
        lay.addWidget(label("ACTIVE ONE-SHOT PROVIDER", 8, C.TEXT_DIM, True))
        lay.addWidget(self._provider)

        self._openai_key = QLineEdit()
        self._openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._openai_key.setPlaceholderText(
            "Saved locally; leave blank to keep it" if self._settings.get("has_openai_key")
            else "Paste OpenAI API key"
        )
        lay.addWidget(label("OPENAI API KEY", 8, C.TEXT_DIM, True))
        lay.addWidget(self._openai_key)

        self._openai_fast = QLineEdit(str(self._settings.get("openai_model_fast", "gpt-5.6-luna")))
        self._openai_strong = QLineEdit(str(self._settings.get("openai_model_reasoning", "gpt-5.6-terra")))
        lay.addWidget(label("GPT MODEL IDS  ·  FAST / REASONING", 8, C.TEXT_DIM, True))
        row = QHBoxLayout()
        row.addWidget(self._openai_fast)
        row.addWidget(self._openai_strong)
        lay.addLayout(row)

        self._anthropic_key = QLineEdit()
        self._anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._anthropic_key.setPlaceholderText(
            "Saved locally; leave blank to keep it" if self._settings.get("has_anthropic_key")
            else "Paste Anthropic API key"
        )
        lay.addWidget(label("ANTHROPIC API KEY", 8, C.TEXT_DIM, True))
        lay.addWidget(self._anthropic_key)

        from jarvis.core.provider_settings import CLAUDE_FAST_MODEL, CLAUDE_STRONG_MODEL
        self._anthropic_fast = QLineEdit(str(self._settings.get("anthropic_model_fast", CLAUDE_FAST_MODEL)))
        self._anthropic_strong = QLineEdit(str(self._settings.get("anthropic_model_reasoning", CLAUDE_STRONG_MODEL)))
        lay.addWidget(label("CLAUDE MODEL IDS  ·  FAST / REASONING", 8, C.TEXT_DIM, True))
        row = QHBoxLayout()
        row.addWidget(self._anthropic_fast)
        row.addWidget(self._anthropic_strong)
        lay.addLayout(row)

        self._status = label(
            "Keys are stored in the locally ignored config/api_keys.json file.",
            8, C.GREEN,
        )
        lay.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("CANCEL")
        save = QPushButton("▸  SAVE PROVIDER")
        cancel.clicked.connect(self.hide)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        lay.addLayout(buttons)

    def _save(self):
        provider = str(self._provider.currentData() or "gemini")
        if provider == "openai" and not (
            self._openai_key.text().strip() or self._settings.get("has_openai_key")
        ):
            self._status.setText("Add an OpenAI key before selecting GPT.")
            self._status.setStyleSheet(f"color: {C.RED}; background: transparent;")
            return
        if provider == "anthropic" and not (
            self._anthropic_key.text().strip() or self._settings.get("has_anthropic_key")
        ):
            self._status.setText("Add an Anthropic key before selecting Claude.")
            self._status.setStyleSheet(f"color: {C.RED}; background: transparent;")
            return
        self.saved.emit({
            "provider": provider,
            "openai_api_key": self._openai_key.text(),
            "anthropic_api_key": self._anthropic_key.text(),
            "openai_model_fast": self._openai_fast.text(),
            "openai_model_reasoning": self._openai_strong.text(),
            "anthropic_model_fast": self._anthropic_fast.text(),
            "anthropic_model_reasoning": self._anthropic_strong.text(),
        })
        self.hide()


class NewsBriefingOverlay(QFrame):
    """Compact, animated headline card shown only while the news is being read."""

    _W = 430
    _H = 198

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NewsBriefingOverlay")
        self.setStyleSheet(
            f"QFrame#NewsBriefingOverlay{{background:rgba(8,14,18,246);"
            f"border:1px solid {C.PRI};border-radius:5px;}}"
            f"QLabel{{background:transparent;border:0;color:{C.TEXT};}}"
        )
        self._items: list[dict] = []
        self._images: dict[int, QPixmap] = {}
        self._image_failures: set[int] = set()
        self._index = 0
        self._animation: QParallelAnimationGroup | None = None
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 9)
        root.setSpacing(6)
        header = QHBoxLayout()
        self._kicker = QLabel("◈  SRI LANKA / LIVE BRIEFING")
        self._kicker.setStyleSheet(f"color:{C.PRI};font:bold 8pt 'Courier New';letter-spacing:1px;")
        header.addWidget(self._kicker, 1)
        self._counter = QLabel("01 / 01")
        self._counter.setStyleSheet(f"color:{C.TEXT_DIM};font:8pt 'Courier New';")
        header.addWidget(self._counter)
        close = QPushButton("×")
        close.setFixedSize(24, 22)
        close.setToolTip("Dismiss the briefing headlines")
        close.setStyleSheet(f"QPushButton{{color:{C.TEXT_DIM};background:transparent;border:0;font:14pt 'Segoe UI';}}QPushButton:hover{{color:{C.WHITE};}}")
        close.clicked.connect(self.dismiss)
        header.addWidget(close)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(10)
        self._image = QLabel("IMAGE\nLOADING…")
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setFixedSize(142, 112)
        self._image.setStyleSheet(f"background:#050b0e;border:1px solid {C.BORDER};color:{C.TEXT_DIM};font:8pt 'Courier New';")
        body.addWidget(self._image)
        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self._source = QLabel("NEWS SOURCE")
        self._source.setStyleSheet(f"color:{C.ACC2};font:bold 7pt 'Courier New';")
        text_col.addWidget(self._source)
        self._headline = QLabel("Waiting for headlines…")
        self._headline.setWordWrap(True)
        self._headline.setMaximumHeight(42)
        self._headline.setStyleSheet(f"color:{C.WHITE};font:bold 9pt 'Segoe UI';")
        text_col.addWidget(self._headline)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setMaximumHeight(47)
        self._summary.setStyleSheet(f"color:{C.TEXT_MED};font:8pt 'Segoe UI';")
        text_col.addWidget(self._summary, 1)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self._open = QPushButton("OPEN ARTICLE  ↗")
        self._open.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open.setStyleSheet(
            f"QPushButton{{color:{C.PRI};background:#0b171a;border:1px solid {C.PRI_DIM};"
            "padding:5px 9px;font:bold 7pt 'Courier New';}"
            f"QPushButton:hover{{background:{C.PRI_GHO};border-color:{C.PRI};}}"
        )
        self._open.clicked.connect(self._open_current_article)
        actions.addWidget(self._open)
        text_col.addLayout(actions)
        body.addLayout(text_col, 1)
        root.addLayout(body, 1)

        self._advance_timer = QTimer(self)
        self._advance_timer.setInterval(9000)
        self._advance_timer.timeout.connect(self._advance)
        self.hide()

    def set_items(self, items) -> None:
        normalized = [item for item in (items or []) if isinstance(item, dict)]
        if not normalized:
            self.dismiss()
            return
        self._items = normalized[:12]
        self._images.clear()
        self._image_failures.clear()
        self._index = 0
        self._image.setPixmap(QPixmap())
        self._image.setText("IMAGE\nLOADING…")
        self._render_current()
        self._advance_timer.start() if len(self._items) > 1 else self._advance_timer.stop()
        self._animate_in()

    def set_image(self, index: int, article_url: str, data: bytes, _content_type: str) -> None:
        if not 0 <= index < len(self._items) or self._items[index].get("url") != article_url:
            return
        image = QPixmap()
        if not image.loadFromData(data):
            return
        self._images[index] = image
        self._image_failures.discard(index)
        if index == self._index:
            self._render_image(image)

    def set_image_failed(self, index: int, article_url: str) -> None:
        if not 0 <= index < len(self._items) or self._items[index].get("url") != article_url:
            return
        self._image_failures.add(index)
        if index == self._index:
            self._render_image()

    def _render_image(self, image: QPixmap | None = None) -> None:
        image = image or self._images.get(self._index)
        if image is None or image.isNull():
            self._image.setPixmap(QPixmap())
            self._image.setText(
                "IMAGE\nUNAVAILABLE" if self._index in self._image_failures
                else "IMAGE\nLOADING…"
            )
            return
        self._image.setText("")
        self._image.setPixmap(image.scaled(
            self._image.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _render_current(self) -> None:
        item = self._items[self._index]
        self._counter.setText(f"{self._index + 1:02d} / {len(self._items):02d}")
        self._source.setText(str(item.get("source") or "NEWSFIRST / ADA DERANA").upper()[:52])
        self._headline.setText(str(item.get("title") or "Headline")[:180])
        summary = " ".join(str(item.get("detail") or item.get("snippet") or item.get("description") or "").split())
        self._summary.setText(summary[:230] if summary else "JARVIS is reading this headline now.")
        url = str(item.get("url") or item.get("link") or "")
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        trusted = parsed.scheme == "https" and (
            host == "newsfirst.lk" or host.endswith(".newsfirst.lk")
            or host == "adaderana.lk" or host.endswith(".adaderana.lk")
        )
        self._open.setEnabled(trusted)
        self._open.setToolTip("Open this publisher's article in your default browser" if trusted else "No verified publisher article URL is available")
        self._render_image()

    def _advance(self) -> None:
        if len(self._items) < 2:
            return
        self._index = (self._index + 1) % len(self._items)
        self._render_current()

    def _open_current_article(self) -> None:
        if not self._items:
            return
        url = str(self._items[self._index].get("url") or self._items[self._index].get("link") or "")
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed = host == "newsfirst.lk" or host.endswith(".newsfirst.lk") or host == "adaderana.lk" or host.endswith(".adaderana.lk")
        if parsed.scheme == "https" and allowed:
            QDesktopServices.openUrl(QUrl(url))

    def _animate_in(self) -> None:
        self._stop_animation()
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(self._W, max(280, parent.width() - 16))
        height = min(self._H, max(150, parent.height() - 16))
        self.setFixedSize(width, height)
        self._image.setFixedSize(min(142, max(92, (width - 42) // 3)), min(112, height - 76))
        x = max(8, parent.width() - width - 18)
        y = max(8, parent.height() - height - 18)
        target = QPoint(x, y)
        self.setGeometry(x, y + 18, width, height)
        self._opacity.setOpacity(0.0)
        self.show()
        self.raise_()
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self._opacity, b"opacity", group)
        fade.setDuration(380)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        slide = QPropertyAnimation(self, b"pos", group)
        slide.setDuration(380)
        slide.setStartValue(QPoint(x, y + 18))
        slide.setEndValue(target)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(fade)
        group.addAnimation(slide)
        self._animation = group
        group.start()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None or not self.isVisible():
            return
        x = max(8, parent.width() - self.width() - 18)
        y = max(8, parent.height() - self.height() - 18)
        self.move(x, y)

    def dismiss(self) -> None:
        self._advance_timer.stop()
        if not self.isVisible():
            return
        self._stop_animation()
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self._opacity, b"opacity", group)
        fade.setDuration(280)
        fade.setStartValue(self._opacity.opacity())
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InCubic)
        slide = QPropertyAnimation(self, b"pos", group)
        slide.setDuration(280)
        slide.setStartValue(self.pos())
        slide.setEndValue(self.pos() + QPoint(0, 14))
        slide.setEasingCurve(QEasingCurve.Type.InCubic)
        group.addAnimation(fade)
        group.addAnimation(slide)
        group.finished.connect(self._finish_dismiss)
        self._animation = group
        group.start()

    def _finish_dismiss(self) -> None:
        self.hide()
        self._opacity.setOpacity(0.0)
        self._items = []
        self._images.clear()

    def _stop_animation(self) -> None:
        if self._animation is not None:
            self._animation.stop()
            self._animation.deleteLater()
            self._animation = None
