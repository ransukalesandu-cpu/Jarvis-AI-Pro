"""Context-aware glass task panels that stay out of the hologram's way.

The home screen is supposed to be a hologram, not a dashboard. But when JARVIS
is actually *doing* something — playing a track, opening a video, downloading a
file, waiting on a reminder — the user needs to see it. This module owns that
middle ground:

* :class:`TaskPanelManager` is one transparent overlay on the hologram stage.
  Screens call :meth:`open_task` / :meth:`update_task` / :meth:`close_task` and
  never touch geometry themselves.
* :class:`GlassTaskPanel` renders a single task. Its *kind* decides which
  controls exist; a control that has no real callback is not drawn at all, so
  the panel cannot advertise an action it cannot perform.
* The layout is deterministic: candidates are scored for distance from the
  face, overlap with other panels and overflow, and the best free slot wins.
  No physics, no timers, no randomness — the same inputs always produce the
  same screen, which is what makes it testable.

Truthfulness rules encoded here:

* ``progress is None`` means *indeterminate* (an animated sweep), never 0 %.
* a panel is only marked ``COMPLETED`` by the code that actually finished the
  work; this module never infers success from a timeout.
* the music waveform only moves while ``energy`` is being fed from real audio.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QToolButton, QWidget

from core import failsoft
from core.hologram_theme import ThemePalette, palette_for_mode

__all__ = [
    "TaskState",
    "TaskKind",
    "TaskSpec",
    "GlassTaskPanel",
    "TaskPanelManager",
    "layout_candidates",
    "kind_for_action",
]


class TaskState:
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    ALL = (WAITING, RUNNING, COMPLETED, FAILED, CANCELLED)
    TERMINAL = (COMPLETED, FAILED, CANCELLED)

    LABELS = {
        WAITING: "WAITING",
        RUNNING: "RUNNING",
        COMPLETED: "DONE",
        FAILED: "FAILED",
        CANCELLED: "CANCELLED",
    }


class TaskKind:
    MUSIC = "music"
    VIDEO = "video"
    IMAGE = "image"
    DOWNLOAD = "download"
    REMINDER = "reminder"
    SEARCH = "search"
    GENERIC = "generic"


# Tool/action name → panel kind. Matching is prefix/substring based because the
# action namespace mixes snake_case ("youtube_video") with prefixes
# ("game_updater_download"). An unknown action deliberately gets GENERIC: the
# panel then claims nothing it cannot show.
_KIND_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("music", "spotify", "song", "playlist", "audio_player"), TaskKind.MUSIC),
    (("youtube", "video", "movie", "stream"), TaskKind.VIDEO),
    (("image", "picture", "photo", "screen_process", "camera", "screenshot"), TaskKind.IMAGE),
    (("download", "game_updater", "install", "update_steam", "epic"), TaskKind.DOWNLOAD),
    (("reminder", "timer", "alarm", "schedule", "daily_planner", "calendar"), TaskKind.REMINDER),
    (("search", "news", "weather", "research", "web_"), TaskKind.SEARCH),
)


def kind_for_action(action_name: str) -> str:
    """Best-effort panel kind for a real tool call; never invents a kind."""
    name = str(action_name or "").strip().lower()
    if not name:
        return TaskKind.GENERIC
    for needles, kind in _KIND_RULES:
        if any(needle in name for needle in needles):
            return kind
    return TaskKind.GENERIC


@dataclass
class TaskSpec:
    """Everything a panel needs; mutated through :meth:`TaskPanelManager.update_task`."""

    task_id: str
    kind: str = TaskKind.GENERIC
    title: str = ""
    subtitle: str = ""
    state: str = TaskState.RUNNING
    #: 0.0-1.0, or ``None`` when the real progress is unknown (indeterminate).
    progress: float | None = None
    pinned: bool = False
    detail: str = ""
    #: Media only: seconds. Both must be set for a timeline to be drawn.
    position: float | None = None
    duration: float | None = None
    #: Media only: absolute path to a thumbnail that actually exists.
    thumbnail_path: str = ""
    #: Optional callables. A control is only drawn when its callback exists.
    on_play_pause: Callable[[], None] | None = None
    on_next: Callable[[], None] | None = None
    on_previous: Callable[[], None] | None = None
    on_open: Callable[[], None] | None = None
    on_expand: Callable[[], None] | None = None
    on_dismiss: Callable[[], None] | None = None
    playing: bool = False
    #: Real audio energy 0.0-1.0, pushed by the visualizer bridge.
    energy: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0

    def normalised(self) -> "TaskSpec":
        state = self.state if self.state in TaskState.ALL else TaskState.RUNNING
        progress = self.progress
        if progress is not None:
            try:
                progress = max(0.0, min(1.0, float(progress)))
            except (TypeError, ValueError):
                progress = None
        position = self.position if self.position is not None else None
        duration = self.duration if self.duration is not None else None
        if duration is not None and duration <= 0:
            duration = None
        return replace(
            self,
            state=state,
            progress=progress,
            title=str(self.title)[:90],
            subtitle=str(self.subtitle)[:90],
            detail=str(self.detail)[:140],
            position=position,
            duration=duration,
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in TaskState.TERMINAL


def _has_thumbnail(spec: TaskSpec) -> bool:
    """True only when the thumbnail path really points at an existing file."""
    path = str(getattr(spec, "thumbnail_path", "") or "").strip()
    if not path:
        return False
    try:
        return Path(path).is_file()
    except OSError:
        return False


def _overlap_area(a: QRect, b: QRect) -> int:
    intersect = a.intersected(b)
    if intersect.isEmpty():
        return 0
    return max(0, intersect.width()) * max(0, intersect.height())


def layout_candidates(
    bounds: QRect,
    blocked: QRect,
    panel_size: tuple[int, int],
    placed: Iterable[QRect] = (),
    margin: int = 12,
    gap: int = 10,
) -> list[tuple[int, QRect]]:
    """Score every free slot for one panel; lowest cost wins.

    ``blocked`` is the hologram's bounding box — the one thing on screen that
    must never be covered. Candidates are generated in columns on both sides of
    it (and below it, as a fallback for narrow windows), then scored by:

    * overlap with the face (dominant),
    * overlap with panels already placed,
    * distance from the face centre (keep them close, but not on top),
    * clipping outside ``bounds`` (disqualifying).

    Returns ``[(cost, rect), …]`` sorted best-first so callers can debug the
    choice and tests can assert that *something* fits.
    """
    panel_w, panel_h = max(120, int(panel_size[0])), max(48, int(panel_size[1]))
    inner = bounds.adjusted(margin, margin, -margin, -margin)
    results: list[tuple[int, QRect]] = []

    left_x = inner.left()
    right_x = inner.right() - panel_w + 1
    # Columns hug the face: as close as possible without intruding.
    face_left = blocked.left() - gap - panel_w
    face_right = blocked.right() + gap
    xs = [max(left_x, min(face_left, inner.right() - panel_w + 1)), min(right_x, max(face_right, inner.left()))]
    below_y = blocked.bottom() + gap
    ys = [inner.top(), max(inner.top(), blocked.top())]
    step = max(64, panel_h + gap)

    for index in range(6):
        for y in ys:
            ys_candidate = y + index * step
            for x in xs:
                rect = QRect(int(x), int(ys_candidate), panel_w, panel_h)
                if not inner.contains(rect):
                    continue
                face_overlap = _overlap_area(rect, blocked)
                if face_overlap:
                    # Covering the hologram is not a trade-off, it is a defect.
                    continue
                panel_overlap = sum(_overlap_area(rect, other) for other in placed)
                distance = int(math.hypot(rect.center().x() - blocked.center().x(),
                                          rect.center().y() - blocked.center().y()))
                cost = panel_overlap * 4 + distance
                results.append((cost, rect))

    # Bottom strip under the face, for short/wide windows with no side room.
    for index in range(2):
        for x in (inner.left(), blocked.left(), max(inner.left(), inner.right() - panel_w + 1)):
            rect = QRect(int(x), int(min(inner.bottom() - panel_h + 1, below_y + index * step)),
                         panel_w, panel_h)
            if not inner.contains(rect) or _overlap_area(rect, blocked):
                continue
            panel_overlap = sum(_overlap_area(rect, other) for other in placed)
            distance = int(math.hypot(rect.center().x() - blocked.center().x(),
                                      rect.center().y() - blocked.center().y()))
            cost = panel_overlap * 4 + distance
            results.append((cost, rect))

    results.sort(key=lambda item: item[0])
    return results


class GlassTaskPanel(QWidget):
    """One translucent rounded task card drawn with QPainter.

    Child buttons are created only for callbacks that exist. That is the whole
    "no decorative controls" rule, enforced by construction rather than review.
    """

    sig_dismiss = pyqtSignal(str)
    sig_pin = pyqtSignal(str, bool)

    def __init__(self, spec: TaskSpec, palette: ThemePalette, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(f"GlassTaskPanel_{spec.task_id}")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._palette = palette
        self._spec = spec.normalised()
        self._phase = 0.0
        self._collapsed = False
        #: 1.0 → 0.0 decay used by voice-command "this is the target" feedback.
        self._highlight = 0.0
        self._buttons: list[QToolButton] = []
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    # -- public API ---------------------------------------------------------
    @property
    def spec(self) -> TaskSpec:
        return self._spec

    @property
    def task_id(self) -> str:
        return self._spec.task_id

    def apply_spec(self, spec: TaskSpec, palette: ThemePalette | None = None) -> None:
        changed_kind = spec.kind != self._spec.kind
        self._spec = spec.normalised()
        if palette is not None:
            self._palette = palette
        if changed_kind:
            self._rebuild_buttons()
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        for button in self._buttons:
            button.setVisible(not self._collapsed)
        self.update()

    def set_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def flash(self) -> None:
        """Highlight this panel briefly — feedback that a command targeted it."""
        self._highlight = 1.0
        self.update()

    def set_highlight(self, value: float) -> None:
        try:
            self._highlight = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            self._highlight = 0.0
        self.update()

    # -- construction -------------------------------------------------------
    def _build(self) -> None:
        self._rebuild_buttons()

    def _rebuild_buttons(self) -> None:
        for button in self._buttons:
            button.deleteLater()
        self._buttons = []
        spec = self._spec
        actions: list[tuple[str, str, Callable[[], None] | None]] = []
        if spec.kind == TaskKind.MUSIC:
            actions.append(("⏮", "Previous track", spec.on_previous))
            actions.append(("⏸" if spec.playing else "▶", "Play/pause", spec.on_play_pause))
            actions.append(("⏭", "Next track", spec.on_next))
        if spec.on_open is not None:
            actions.append(("↗", "Open", spec.on_open))
        if spec.on_expand is not None and spec.kind in (TaskKind.VIDEO, TaskKind.IMAGE):
            actions.append(("⤢", "Expand", spec.on_expand))
        # Dismiss exists whenever the caller can handle it; otherwise the panel
        # stays until the owning task clears it.
        if spec.on_dismiss is not None or spec.is_terminal:
            actions.append(("✕", "Dismiss", self._emit_dismiss))

        x = 8
        for glyph, tooltip, callback in actions:
            if callback is None:
                continue
            button = QToolButton(self)
            button.setText(glyph)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setFixedSize(22, 22)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QToolButton { color: %s; background: rgba(255,255,255,16);"
                " border: 1px solid rgba(255,255,255,40); border-radius: 11px; }"
                "QToolButton:hover { background: rgba(255,255,255,46); }"
                % QColor(*self._palette.accent).name()
            )
            button.clicked.connect(lambda _checked=False, fn=callback: self._invoke(fn))
            button.move(x, 30)
            button.show()
            self._buttons.append(button)
            x += 26

    def _invoke(self, callback: Callable[[], None]) -> None:
        """Run an action; a broken callback must not kill the HUD."""
        try:
            callback()
        except Exception:
            failsoft.suppress("ui.task_panels:action")

    def _emit_dismiss(self) -> None:
        if self._spec.on_dismiss is not None:
            self._invoke(self._spec.on_dismiss)
        self.sig_dismiss.emit(self.task_id)

    # -- painting -----------------------------------------------------------
    def _tick(self) -> None:
        try:
            self._tick_body()
        except RuntimeError:
            # The panel was deleted between the timer firing and this call.
            failsoft.suppress("ui.task_panels:tick")

    def _tick_body(self) -> None:
        if self._highlight > 0.0:
            self._highlight = max(0.0, self._highlight - 0.05)
            self.update()
        if self._spec.state in (TaskState.RUNNING, TaskState.WAITING):
            self._phase = (self._phase + 4.0) % 360.0
            self.update()
        elif abs(self._spec.energy) > 0.01:
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        accent = QColor(*self._palette.accent)
        state_colour = {
            TaskState.COMPLETED: QColor("#7fe0a8"),
            TaskState.FAILED: QColor("#ff6b6b"),
            TaskState.CANCELLED: QColor("#9aa7b0"),
        }.get(self._spec.state, accent)

        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 120), 1.2))
        painter.setBrush(QColor(6, 10, 16, 214))
        painter.drawPath(path)

        # Voice-command focus pulse. Drawn only while a real command targeted us.
        if self._highlight > 0.0:
            glow = QColor(accent.red(), accent.green(), accent.blue(), int(70 + 150 * self._highlight))
            painter.setPen(QPen(glow, 1.2 + 1.4 * self._highlight))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        # Left status edge: colour alone never carries the message, the label does.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(state_colour.red(), state_colour.green(), state_colour.blue(), 190))
        painter.drawRoundedRect(QRectF(rect.left() + 1, rect.top() + 8, 3, rect.height() - 16), 2, 2)

        text_left = rect.left() + 12
        # Reserve the right-hand corner for the state label: the title is elided
        # to fit, it never runs underneath it.
        state_width = 74.0
        title_width = max(40.0, rect.width() - 24 - state_width)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QPen(QColor("#f2ece2")))
        painter.drawText(
            QRectF(text_left, rect.top() + 6, title_width, 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._elide(self._spec.title or self._spec.task_id, title_width),
        )

        if self._spec.subtitle:
            painter.setFont(QFont("Segoe UI", 7))
            painter.setPen(QPen(QColor(200, 200, 205, 190)))
            painter.drawText(
                QRectF(text_left, rect.top() + 20, title_width, 13),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self._elide(self._spec.subtitle, rect.width() - 24),
            )

        bottom = rect.bottom() - 6
        if self._collapsed:
            return

        # Music: only draw the waveform while real energy is arriving.
        if self._spec.kind == TaskKind.MUSIC and self._spec.energy > 0.01:
            self._paint_waveform(painter, QRectF(text_left, bottom - 12, rect.width() - 24, 12))

        # Timeline: only when both position and duration are actually known.
        if self._spec.duration and self._spec.position is not None:
            ratio = max(0.0, min(1.0, self._spec.position / self._spec.duration))
            bar = QRectF(text_left, bottom - 4, rect.width() - 24, 3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 28))
            painter.drawRoundedRect(bar, 1.5, 1.5)
            painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 220))
            painter.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * ratio, bar.height()), 1.5, 1.5)

        if self._spec.state == TaskState.RUNNING:
            if self._spec.progress is None:
                # Indeterminate sweep — honest "working, amount unknown".
                bar = QRectF(text_left, bottom - 4, rect.width() - 24, 3)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 28))
                painter.drawRoundedRect(bar, 1.5, 1.5)
                span = bar.width() * 0.3
                offset = (math.sin(math.radians(self._phase)) * 0.5 + 0.5) * (bar.width() - span)
                painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 210))
                painter.drawRoundedRect(QRectF(bar.left() + offset, bar.top(), span, bar.height()), 1.5, 1.5)
            else:
                bar = QRectF(text_left, bottom - 4, rect.width() - 24, 3)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 28))
                painter.drawRoundedRect(bar, 1.5, 1.5)
                painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 220))
                painter.drawRoundedRect(
                    QRectF(bar.left(), bar.top(), bar.width() * self._spec.progress, bar.height()), 1.5, 1.5
                )
                painter.setFont(QFont("Segoe UI", 7))
                painter.setPen(QPen(QColor(230, 230, 235, 200)))
                painter.drawText(
                    QRectF(rect.right() - 60, bottom - 18, 50, 12),
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    f"{int(self._spec.progress * 100)}%",
                )

        # State label always present: colour is not the only signal.
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.setPen(QPen(state_colour))
        painter.drawText(
            QRectF(rect.right() - 78, rect.top() + 6, 68, 14),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            TaskState.LABELS.get(self._spec.state, self._spec.state.upper()),
        )

    def _paint_waveform(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor(*self._palette.glow), 1.2))
        columns = max(4, int(rect.width() / 4))
        for index in range(columns):
            phase = self._phase / 28.0 + index * 0.55
            amplitude = rect.height() * (0.22 + 0.78 * min(1.0, self._spec.energy)) * abs(math.sin(phase))
            x = rect.left() + index * 4
            painter.drawLine(
                QPoint(int(x), int(rect.center().y() - amplitude / 2)),
                QPoint(int(x), int(rect.center().y() + amplitude / 2)),
            )

    @staticmethod
    def _elide(text: str, width: float) -> str:
        limit = max(4, int(width / 6.4))
        return text if len(text) <= limit else text[: limit - 1] + "…"

    # -- accessibility / interaction ---------------------------------------
    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        self.set_collapsed(not self._collapsed)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.set_collapsed(not self._collapsed)
            return
        if event.key() == Qt.Key.Key_Escape:
            if self._spec.is_terminal:
                self._emit_dismiss()
            return
        super().keyPressEvent(event)


class TaskPanelManager(QWidget):
    """Transparent overlay that owns every :class:`GlassTaskPanel` on the stage.

    Placement is deterministic and re-runs whenever the stage resizes or the
    panel set changes, so panels reflow across resolutions instead of drifting
    off-screen. The hologram gets an explicit exclusion rectangle from the
    caller (its own widget geometry) and is never covered.
    """

    sig_task_action = pyqtSignal(str, str)   # task_id, action ("dismiss", ...)

    PANEL_SIZES = {
        TaskKind.MUSIC: (300, 74),
        # Video/image panels are compact unless there is a real thumbnail to
        # show; an empty 178 px card is just reserved black space.
        TaskKind.VIDEO: (268, 96),
        TaskKind.IMAGE: (220, 96),
        TaskKind.DOWNLOAD: (280, 70),
        TaskKind.REMINDER: (280, 64),
        TaskKind.SEARCH: (280, 64),
        TaskKind.GENERIC: (280, 66),
    }

    def __init__(self, stage: QWidget, palette: ThemePalette | None = None):
        super().__init__(stage)
        self.setObjectName("TaskPanelOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._stage = stage
        self._palette = palette or palette_for_mode("jarvis")
        self._panels: dict[str, GlassTaskPanel] = {}
        self._specs: dict[str, TaskSpec] = {}
        self._blocked = QRect()
        self._archived: list[TaskSpec] = []
        self.setGeometry(stage.rect())
        # Follow the stage itself: the overlay is not in a layout, so without
        # this it would keep its construction-time size and place nothing.
        stage.installEventFilter(self)
        self.raise_()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self._stage and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._stage.rect())
            self.reflow()
            self.raise_()
        return super().eventFilter(watched, event)

    # -- configuration ------------------------------------------------------
    def set_blocked_rect(self, rect: QRect) -> None:
        """Tell the manager which area is the hologram (never covered)."""
        if rect != self._blocked:
            self._blocked = QRect(rect)
            self.reflow()

    def set_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        for panel in self._panels.values():
            panel.set_palette(palette)
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.reflow()

    def stage_resized(self) -> None:
        self.setGeometry(self._stage.rect())
        self.reflow()

    # -- task lifecycle -----------------------------------------------------
    def open_task(self, spec: TaskSpec) -> GlassTaskPanel:
        spec = spec.normalised()
        panel = self._panels.get(spec.task_id)
        if panel is None:
            panel = GlassTaskPanel(spec, self._palette, self)
            panel.sig_dismiss.connect(self._on_dismiss)
            self._panels[spec.task_id] = panel
            self._specs[spec.task_id] = spec
            panel.show()
            panel.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        else:
            panel.apply_spec(spec, self._palette)
            self._specs[spec.task_id] = spec
        self._archived = [item for item in self._archived if item.task_id != spec.task_id]
        self.reflow()
        return panel

    def update_task(self, task_id: str, **changes) -> bool:
        """Patch a live task. Unknown ids return False rather than creating one."""
        spec = self._specs.get(task_id)
        panel = self._panels.get(task_id)
        if spec is None or panel is None:
            return False
        for key, value in changes.items():
            if not hasattr(spec, key):
                raise AttributeError(f"TaskSpec has no field {key!r}")
            setattr(spec, key, value)
        spec = spec.normalised()
        self._specs[task_id] = spec
        panel.apply_spec(spec, self._palette)
        self._resize_panel(task_id)
        if spec.is_terminal:
            # Completed/failed tasks shrink and stay reachable, never vanish.
            panel.set_collapsed(True)
        self.reflow()
        return True

    def close_task(self, task_id: str, *, archive: bool = True) -> None:
        spec = self._specs.get(task_id)
        panel = self._panels.pop(task_id, None)
        self._specs.pop(task_id, None)
        if panel is not None:
            try:
                panel.hide()
                panel.deleteLater()
            except RuntimeError:
                # Already destroyed by Qt; dropping our reference is enough.
                failsoft.suppress("ui.task_panels:close_task")
        if spec is not None and archive:
            self._archived.append(spec)
            del self._archived[:-20]
        self.reflow()

    def archive(self) -> list[TaskSpec]:
        """Recently finished tasks, newest last — the "reopen" list."""
        return list(self._archived)

    def reopen(self, task_id: str) -> bool:
        for spec in list(self._archived):
            if spec.task_id == task_id:
                self._archived.remove(spec)
                self.open_task(spec)
                return True
        return False

    def has_task(self, task_id: str) -> bool:
        return task_id in self._panels

    def specs(self) -> list[TaskSpec]:
        """Live task specs, used by the Dynamic Island for its one-line summary."""
        return list(self._specs.values())

    def task_ids(self) -> list[str]:
        return list(self._panels)

    def panel(self, task_id: str) -> GlassTaskPanel | None:
        return self._panels.get(task_id)

    def flash(self, task_id: str) -> bool:
        """Briefly highlight one panel (voice-command target feedback)."""
        panel = self._panels.get(task_id)
        if panel is None:
            return False
        panel.flash()
        return True

    def set_energy(self, energy: float) -> None:
        """Feed real output energy so music panels animate only when audible."""
        try:
            value = max(0.0, min(1.0, float(energy)))
        except (TypeError, ValueError):
            value = 0.0
        for spec in self._specs.values():
            spec.energy = value
        for panel in list(self._panels.values()):
            spec = self._specs.get(panel.task_id)
            if spec is not None:
                panel.apply_spec(spec, self._palette)

    def clear(self) -> None:
        for task_id in list(self._panels):
            self.close_task(task_id, archive=False)
        self._archived.clear()

    # -- internals ----------------------------------------------------------
    def _on_dismiss(self, task_id: str) -> None:
        self.sig_task_action.emit(task_id, "dismiss")
        self.close_task(task_id)

    #: Sizes used once a real thumbnail exists for a video/image task.
    MEDIA_SIZES = {
        TaskKind.VIDEO: (268, 178),
        TaskKind.IMAGE: (220, 168),
    }

    def _panel_size(self, spec: TaskSpec) -> tuple[int, int]:
        if spec.kind in self.MEDIA_SIZES and _has_thumbnail(spec):
            return self.MEDIA_SIZES[spec.kind]
        return self.PANEL_SIZES.get(spec.kind, self.PANEL_SIZES[TaskKind.GENERIC])

    def _resize_panel(self, task_id: str) -> None:
        panel = self._panels.get(task_id)
        spec = self._specs.get(task_id)
        if panel is None or spec is None:
            return
        width, height = self._panel_size(spec)
        if spec.is_terminal:
            height = 40
        panel.resize(width, height)

    def reflow(self) -> None:
        """Place every panel deterministically; live tasks win over finished ones."""
        try:
            self._reflow()
        except RuntimeError:
            failsoft.suppress("ui.task_panels:reflow")

    def _reflow(self) -> None:
        if not self._panels:
            return
        bounds = self.rect()
        blocked = self._blocked if not self._blocked.isNull() else QRect(
            bounds.center().x() - 120, bounds.center().y() - 120, 240, 240
        )
        ordered = sorted(
            self._panels.values(),
            key=lambda panel: (
                1 if panel.spec.is_terminal else 0,
                0 if panel.spec.pinned else 1,
                panel.spec.task_id,
            ),
        )
        placed: list[QRect] = []
        for panel in ordered:
            if panel.task_id not in self._specs:
                continue
            spec = self._specs[panel.task_id]
            width, height = self._panel_size(spec)
            if spec.is_terminal:
                height = 40
            panel.resize(width, height)
            candidates = layout_candidates(bounds, blocked, (width, height), placed)
            if not candidates:
                panel.hide()   # no honest space: hide, keep it reopenable
                continue
            _, rect = candidates[0]
            panel.setGeometry(rect)
            panel.show()
            panel.set_collapsed(spec.is_terminal)
            placed.append(rect)
