from __future__ import annotations

import atexit
import json
import math
import os
import platform
import random
import sys

if sys.platform != "win32" and not os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
import subprocess
import sys
import threading
import time
from pathlib import Path
import psutil

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

from PyQt6.QtCore import (
    QEvent, QEasingCurve, QLineF, QPropertyAnimation, QRectF, Qt, QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QImage, QKeySequence, QPainter,
    QPen, QPixmap, QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractButton, QApplication, QCheckBox, QComboBox, QFrame, QGraphicsOpacityEffect,
    QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QStackedWidget, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
    QToolButton, QMenu,
)
from .smart_panel import SmartPanelHeader
from core.voice_ui_control import (
    VoiceUICommand, is_high_impact_ui_label, normalize_label,
)
try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    _OPENGL_CANVAS_AVAILABLE = True
except Exception:
    QOpenGLWidget = QWidget
    _OPENGL_CANVAS_AVAILABLE = False
from core import qt_webengine

QWebEnginePage = QWebEngineProfile = QWebEngineView = None
_NEURAL_HAND_WEBVIEW_AVAILABLE = False
_WEBENGINE_LOAD_ATTEMPTED = False


def _load_webengine() -> bool:
    """Import Qt WebEngine on first use instead of with this package.

    Chromium costs tens of megabytes of mapped libraries and can spawn helper
    processes, and its only consumers here are the immersive neural-hand view,
    the Earth globe and the document workspace. See ``core.qt_webengine``.
    """
    global QWebEnginePage, QWebEngineProfile, QWebEngineView
    global _NEURAL_HAND_WEBVIEW_AVAILABLE, _WEBENGINE_LOAD_ATTEMPTED
    if _WEBENGINE_LOAD_ATTEMPTED:
        return _NEURAL_HAND_WEBVIEW_AVAILABLE
    _WEBENGINE_LOAD_ATTEMPTED = True
    loaded = qt_webengine.load()
    if not loaded:
        return False
    globals().update(loaded)
    _NEURAL_HAND_WEBVIEW_AVAILABLE = True
    return True


def _earth_panel_class():
    """Import the 3D globe panel (MapLibre + WebEngine) on demand."""
    from core.earth_globe import EarthGlobePanel

    return EarthGlobePanel


def _workspace_class():
    """Import the document/media workspace (WebEngine + QtPdf) on demand."""
    from core.hud_workspace import HudWorkspace

    return HudWorkspace


from core.neural_viz import NeuralVizMixin
from core.jarvis_logo_overlay import JarvisLogoOverlay

from core import failsoft

try:
    # 3D human head avatar (measured geometry)
    from core.avatar import HoloAvatar
except Exception:
    try:
        # Synthetic robotic hologram fallback
        from core.artificial_avatar import HoloAvatar
    except Exception:      # pragma: no cover — HUD must never die over cosmetics
        HoloAvatar = None


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR = _base_dir()
# UI assets live beside this package, but credentials are shared with the live
# assistant in JarvisAI/config/api_keys.json (or beside the frozen executable).
if getattr(sys, "frozen", False):
    CONFIG_DIR = Path(sys.executable).parent / "config"
else:
    CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
API_FILE = CONFIG_DIR / "api_keys.json"
_QUICK_GRAPHICS_API_REQUESTED = False


def _read_full_config() -> dict:
    """Read api_keys.json config dict. Returns {} on any error."""
    try:
        return json.loads(API_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# Single source of truth for the release name — the window title, the header
# badge and the readme must never disagree again.
APP_VERSION  = "JARVIS AI"
APP_PROTOCOL = APP_VERSION.split()[-1]

_DEFAULT_W, _DEFAULT_H = 1180, 780
_MIN_W,     _MIN_H     = 940, 640
_LEFT_W  = 176
_RIGHT_W = 350

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


def configure_qt_graphics_backend() -> bool:
    """Align Qt Quick with the OpenGL HUD before any Qt Quick window exists.

    Windows defaults Qt Quick to Direct3D 11, which cannot be composed with
    the HUD's QOpenGLWidget. Call this from main() before QApplication and the
    startup video are created. On other platforms Qt's native default remains.
    """
    global _QUICK_GRAPHICS_API_REQUESTED
    if _OS != "Windows":
        return True
    try:
        from PyQt6.QtQuick import QQuickWindow, QSGRendererInterface

        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
        _QUICK_GRAPHICS_API_REQUESTED = True
        print("[HUD] Qt Quick graphics API set to OpenGL for QOpenGLWidget composition.")
        return True
    except Exception as exc:
        print(f"[HUD] Could not select the OpenGL graphics API: {exc}")
        return False


class _HoverMenuButton(QToolButton):
    """Small edge-navigation trigger that opens its menu when hovered."""

    def enterEvent(self, event):
        super().enterEvent(event)
        menu = self.menu()
        if menu is not None and not menu.isVisible():
            self.showMenu()


class C:
    # Instrument-console palette: graphite, oxidized teal, and machined copper.
    # Warm status accents and dense technical typography keep the HUD distinct
    # from a generic neon chatbot panel.
    BG        = "#080e12"
    PANEL     = "#10191d"
    PANEL2    = "#151f22"
    BORDER    = "#34464a"
    BORDER_B  = "#647b7d"
    BORDER_A  = "#4c686b"
    PRI       = "#71d4c2"
    PRI_DIM   = "#397f78"
    PRI_GHO   = "#172d2c"
    ACC       = "#d98a59"
    ACC2      = "#d7bd7b"
    GREEN     = "#9bd5a2"
    GREEN_D   = "#5b986e"
    RED       = "#e97869"
    MUTED_C   = "#d96f68"
    TEXT      = "#c8d9d5"
    TEXT_DIM  = "#78908d"
    TEXT_MED  = "#9aafaa"
    WHITE     = "#edf3e8"
    DARK      = "#0b1215"
    BAR_BG    = "#192326"


# Keys tied to the accent colour — status colours (ACC, GREEN, RED…) stay fixed
_HUE_LINKED = (
    "BG", "PANEL", "PANEL2", "BORDER", "BORDER_B", "BORDER_A",
    "PRI", "PRI_DIM", "PRI_GHO", "TEXT", "TEXT_DIM", "TEXT_MED",
    "WHITE", "DARK", "BAR_BG",
)
_PALETTE_DEFAULTS: dict[str, str] = {k: getattr(C, k) for k in _HUE_LINKED}

DEFAULT_UI_COLOR = _PALETTE_DEFAULTS["PRI"]


def apply_ui_accent(accent_hex: str) -> bool:
    """
    Re-derives the whole teal-family palette from the chosen accent colour
    (hue shift — brightness/saturation ratios are preserved, design stays intact).
    Painted elements (HUD, waveform, metrics) pick up the new colour on the next
    frame; stylesheet-based panels pick it up when they are rebuilt.
    """
    import colorsys

    accent_hex = (accent_hex or "").strip().lower()
    if not (accent_hex.startswith("#") and len(accent_hex) == 7):
        return False
    try:
        int(accent_hex[1:], 16)
    except ValueError:
        return False

    def _hsv(h: str) -> tuple[float, float, float]:
        r = int(h[1:3], 16) / 255
        g = int(h[3:5], 16) / 255
        b = int(h[5:7], 16) / 255
        return colorsys.rgb_to_hsv(r, g, b)

    base_h            = _hsv(_PALETTE_DEFAULTS["PRI"])[0]
    acc_h, acc_s, _av = _hsv(accent_hex)
    dh   = acc_h - base_h
    grey = acc_s < 0.08   # near-grey accent → the whole theme is desaturated

    for key, hex0 in _PALETTE_DEFAULTS.items():
        h, s, v = _hsv(hex0)
        if grey:
            s *= 0.15
        r, g, b = colorsys.hsv_to_rgb((h + dh) % 1.0, s, v)
        setattr(C, key, "#{:02x}{:02x}{:02x}".format(
            int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5)))
    return True


def current_palette() -> dict[str, str]:
    """A snapshot of the accent-linked colours currently on class C."""
    return {k: getattr(C, k) for k in _HUE_LINKED}


def retheme_all_widgets(old: dict[str, str], new: dict[str, str]) -> None:
    """
    LIVE full theme change. Replaces the old palette colours with the new ones
    in EVERY widget's stylesheet across the app and repaints them. This way the
    colour change applies INSTANTLY across the whole interface — panels, buttons,
    borders included — not just the painted elements. No restart needed.
    """
    mapping = {old[k].lower(): new[k].lower()
               for k in old if old[k].lower() != new.get(k, old[k]).lower()}
    if not mapping:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        try:
            ss = w.styleSheet()
            if ss:
                s2 = ss
                for o, n in mapping.items():
                    if o in s2:
                        s2 = s2.replace(o, n)
                if s2 != ss:
                    w.setStyleSheet(s2)
            w.update()
        except Exception:
            failsoft.suppress('ui:retheme_all_widgets')


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c


# ── Windows GPU via NVML DLL (no subprocess, no console window) ──────────────
_nvml_lib: object = None   # cached ctypes DLL
_nvml_ok:  object = None   # None=untested, True=works, False=unavailable


def _nvml_gpu_windows() -> float:
    """Return NVIDIA GPU utilisation % using nvml.dll directly — zero subprocess."""
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        import ctypes

        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            for dll_name in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll_name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    failsoft.suppress('ui:_nvml_gpu_windows')
                    continue

        if _nvml_lib is None:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_ok = True
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        self._stop_event = threading.Event()
        self._thread = None
        # Probe caches — GPU (NVML) and temperature (WMI) are the expensive
        # queries; initialise their handles once and reuse them instead of
        # rebuilding a connection on every poll.
        self._slow_tick = 0            # gpu/temp refreshed every 3rd cycle
        self._pynvml    = None         # cached pynvml module + device handle
        self._pynvml_h  = None
        self._pynvml_ok = None         # None=untested, False=unavailable here
        self._nv_unix   = None         # cached (lib, dev) for Linux/macOS NVML
        self._wmi_conn  = None         # cached WMI connection (creating one is slow)
        self._wmi_ok    = None         # None=untested, False=unavailable here
        self._thread = threading.Thread(
            target=self._loop, name="JarvisSystemMetrics", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.5) -> None:
        """Stop the polling thread before Python tears down native extensions."""
        self._running = False
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))

    def _loop(self):
        while self._running and not self._stop_event.is_set():
            try:
                self._update()
            except Exception:
                failsoft.suppress('ui:_SysMetrics._loop')
            # Event.wait is interruptible; plain time.sleep kept a daemon thread
            # alive during interpreter shutdown and could abort PyQt test runs.
            self._stop_event.wait(2.0)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        # GPU and temperature change slowly and are the most expensive probes
        # (NVML / WMI) — refresh them every 3rd cycle (~6 s) instead of every
        # cycle, reusing the previous reading in between.
        self._slow_tick = (self._slow_tick + 1) % 3
        if self._slow_tick == 1:
            gpu = self._get_gpu()
            tmp = self._get_temp()
        else:
            gpu = self.gpu
            tmp = self.tmp

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # pynvml — subprocess-free; initialise once and reuse the handle.
        # Re-initialising NVML on every poll is slow, so cache it and stop
        # retrying pynvml entirely once it proves unavailable here.
        if self._pynvml_ok is not False:
            try:
                if self._pynvml_h is None:
                    import pynvml  # type: ignore
                    pynvml.nvmlInit()
                    self._pynvml    = pynvml
                    self._pynvml_h  = pynvml.nvmlDeviceGetHandleByIndex(0)
                    self._pynvml_ok = True
                return float(self._pynvml.nvmlDeviceGetUtilizationRates(self._pynvml_h).gpu)
            except Exception:
                self._pynvml_ok = False

        # Windows: nvml.dll via ctypes (already cached in _nvml_gpu_windows)
        if _OS == "Windows":
            return _nvml_gpu_windows()

        # Linux / macOS: libnvidia-ml shared lib via ctypes — init once, reuse
        try:
            import ctypes

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            if self._nv_unix is None:
                _lib = "libnvidia-ml.so.1" if _OS == "Linux" else "libnvidia-ml.dylib"
                nv = ctypes.CDLL(_lib)
                nv.nvmlInit_v2()
                dev = ctypes.c_void_p()
                nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
                self._nv_unix = (nv, dev)

            nv, dev = self._nv_unix
            u = _Util()
            nv.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
            return float(u.gpu)
        except Exception:
            failsoft.suppress('ui:_SysMetrics._get_gpu')

        return -1.0   # N/A — zero subprocess on all platforms

    def _get_temp(self) -> float:
        # psutil — works on Linux; occasionally Windows with driver support
        try:
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "cpu-thermal", "zenpower", "it8688"]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            failsoft.suppress('ui:_SysMetrics._get_temp')

        # Windows: wmi module (pure Python COM, zero subprocess). Reuse a single
        # connection — building a fresh wmi.WMI() on every poll spins up a COM
        # connection each time and is very slow. Give up after one failure.
        if _OS == "Windows" and self._wmi_ok is not False:
            try:
                if self._wmi_conn is None:
                    import wmi  # type: ignore
                    self._wmi_conn = wmi.WMI(namespace="root/wmi")
                tz = self._wmi_conn.MSAcpi_ThermalZoneTemperature()
                if tz:
                    return (tz[0].CurrentTemperature / 10.0) - 273.15
            except Exception:
                self._wmi_ok   = False
                self._wmi_conn = None

        return -1.0   # N/A — zero subprocess on all platforms

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()
# Daemon threads are not joined automatically during interpreter shutdown.
# Stop this lightweight poller while Python and its native extensions are alive.
atexit.register(_metrics.stop)

class HudCanvas(NeuralVizMixin, QOpenGLWidget):
    def __init__(self, face_path: str, assistant_name: str = "J.A.R.V.I.S",
                 parent=None, enable_avatar: bool = True):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self._assistant_name = assistant_name

        # The holographic head that fills the HUD. If it could not be imported
        # we fall back to the old glowing core so the panel is never empty.
        self._avatar = None
        if enable_avatar and HoloAvatar is not None:
            try:
                # The owner's chosen identity: their own face picture as a
                # cyan hologram (core/avatar_image.py), or the smooth volume
                # head when no picture is installed.
                self._avatar = HoloAvatar(style="image")
            except TypeError:          # the synthetic fallback has no styles
                self._avatar = HoloAvatar()
            except Exception:
                self._avatar = None

        # Which centrepiece to draw. Read once here and changed live by the
        # settings toggle; the avatar object is kept either way so switching
        # back is instant and costs no reload.
        try:
            from memory.config_manager import get_hud_style
            self.hud_style = get_hud_style()
        except Exception:
            self.hud_style = "face"
        self._core_phase = 0.0
        self._neural_phase = 0.0
        self._neural_energy = 0.12
        self._neural_flash = 0.0
        self._neural_call_count = 0
        try:
            from memory.config_manager import get_neural_render_scale
            self._neural_render_scale = get_neural_render_scale()
        except Exception:
            self._neural_render_scale = 0.75
        self._neural_render_image = None
        self._neural_gl_hardware = False
        self._hand_rotation = 0.0
        self._hand_yaw = 0.0
        self._hand_tilt = 0.0
        self._hand_3d_active = False
        self._hand_zoom = 1.0
        self._hand_zoom_target = 1.0
        self._hand_prev_point = None
        self._hand_pinching = False
        self._hand_prev_angle = None
        self._hand_scale_span_start = 0.0
        self._hand_zoom_start = 1.0
        self._neural_palette = [
            # Screenshot-matched spectral groups: electric violet, hot pink,
            # amber, icy cyan, signal red, lime, deep purple, and white core.
            QColor("#A84DFF"), QColor("#FF35A8"), QColor("#FFC13D"),
            QColor("#45E8FF"), QColor("#FF3B50"), QColor("#66FF42"),
            QColor("#792DFF"), QColor("#F8FBFF"),
        ]
        self._build_neural_assets()
        self._neural_quick_view = None
        self._neural_quick_container = None
        self._neural_quick_root = None
        # The original NeuralVizMixin is drawn directly into QOpenGLWidget's
        # GPU framebuffer. Do not let the separate QML recreation replace it.
        self._neural_quick_enabled = False
        self._neural_quick_attempted = True
        self._neural_quick_ready = False
        self._neural_quick_last_sync = 0.0
        self._neural_quick_last_mode = None

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._step_t     = time.time()
        self._blink      = True
        self._blink_tick = 0

        # Rescaled-face cache: the smooth rescale is expensive, so we keep the
        # last result and only rebuild it when the (quantised) size changes.

        # Static grid-dot layer, pre-rendered once per size/theme into a pixmap
        # so paintEvent blits it in one call instead of thousands of drawPoint()s.
        self._grid_cache: QPixmap | None = None
        self._grid_key = None
        # Repaint throttle counter (idle frames drop to ~20 Hz — see _step()).
        self._paint_tick = 0

        # Live audio reactivity: _live_amp is written from the audio threads
        # (0.0–1.0), _amp_disp is the smoothed value the paint code reads.
        self._live_amp  = 0.0
        self._amp_disp  = 0.0
        # (frames, start_time, hop) posted by the playback thread — see
        # push_visemes(). None means "no schedule; use the plain level".
        self._visemes = None
        self._vis_i = None        # first schedule frame not yet handed to the mouth
        self._base_scale = 1.0    # slow "breathing" target; amp is added per-frame
        self._base_halo  = 55.0

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        """Ask the avatar to look somewhere for a moment (see HoloAvatar.glance)."""
        try:
            if self._avatar is not None:
                self._avatar.glance(dx, dy, hold)
        except Exception:
            failsoft.suppress('ui:HudCanvas.glance')

    def react_avatar_text(self, text: str) -> None:
        """Drive facial acting from the latest assistant speech transcription."""
        if self._avatar is not None and self.hud_style == "face":
            self._avatar.react_to_text(text)
            self.update()

    def push_visemes(self, frames, hop: float, at: float) -> None:
        """Thread-safe: hand over a schedule of (level, openness, width) frames.

        The playback thread writes up to 200 ms of audio in one go, so a single
        averaged level would only move the mouth five times a second — enough to
        flap, nowhere near enough to articulate. It instead posts the whole
        slice's worth of 20 ms frames here and `_step()` plays them out against
        the wall clock, in step with the audio going to the speakers.

        `at` is the wall-clock time this batch will *begin to sound*, which the
        caller tracks as a playback cursor. It is not the time of the call, and
        the difference is the whole point: `stream.write` returns once the buffer
        accepts the samples, so consecutive batches are handed over far faster
        than they play. Anchoring each one to "now" made every batch start while
        its predecessor was still sounding, so each schedule replaced the last
        after a couple of frames and the mouth only ever played the opening
        instant of every 200 ms — the reason it did not match the words.

        Successive batches are therefore *appended* into one continuous
        timeline, not swapped in. A paragraph is one schedule; the mouth stops
        falling into a gap at every chunk boundary and having to climb back out.
        """
        try:
            if not frames:
                return
            hop = max(1e-3, float(hop))
            at = float(at)
            new = list(frames)
            cur = self._visemes
            if cur is not None:
                old, t0, ohop = cur
                if abs(ohop - hop) < 1e-6:
                    # Where in the existing timeline does this batch land?
                    i = int(round((at - t0) / hop))
                    if 0 <= i <= len(old) + 1:
                        # Continues (or slightly overlaps) what is already
                        # queued: extend rather than restart. Drop whatever has
                        # already been played so the list cannot grow without
                        # bound over a long reply.
                        merged = old[:i] + new
                        played = int((time.time() - t0) / hop) - 2
                        if played > 60:
                            merged = merged[played:]
                            t0 += played * hop
                            if self._vis_i is not None:
                                self._vis_i = max(0, self._vis_i - played)
                        self._visemes = (merged, t0, hop)
                        return
            self._visemes = (new, at, hop)
            self._vis_i = None
        except Exception:
            failsoft.suppress('ui:HudCanvas.push_visemes')

    def set_audio_level(self, level: float) -> None:
        """Thread-safe entry point for the audio threads. Stores the louder of
        the incoming level and the current value so brief gaps between chunks
        don't make the waveform stutter; _step() decays it back down."""
        try:
            lv = float(level)
        except (TypeError, ValueError):
            return
        if lv < 0.0:
            lv = 0.0
        elif lv > 1.0:
            lv = 1.0
        if lv > self._live_amp:
            self._live_amp = lv

    def trigger_activity(self) -> None:
        """Flash a distinct neural pulse for each active JARVIS operation."""
        self._neural_call_count += 1
        self._neural_flash = 1.0

    def apply_neural_hand_pose(self, pose: dict) -> None:
        """Apply local one-hand 3D rotation or two-hand pinch/roll controls."""
        if self.hud_style not in ("neural", "neural_orb"):
            self._hand_prev_point = None
            self._hand_pinching = False
            return
        if not isinstance(pose, dict):
            return
        mode = str(pose.get("mode", "idle"))
        if mode == "scale":
            span = max(0.0, min(1.5, float(pose.get("span", 0.0))))
            angle = float(pose.get("angle", 0.0))
            if not self._hand_pinching:
                self._hand_pinching = True
                self._hand_scale_span_start = max(0.05, span)
                self._hand_zoom_start = self._hand_zoom
                self._hand_prev_angle = angle
            ratio = span / max(0.05, self._hand_scale_span_start)
            self._hand_zoom_target = max(0.62, min(1.75, self._hand_zoom_start * ratio))
            previous_angle = self._hand_prev_angle
            if previous_angle is not None:
                delta_angle = (angle - previous_angle + 180.0) % 360.0 - 180.0
                self._hand_rotation = (self._hand_rotation + delta_angle) % 360.0
            self._hand_prev_angle = angle
            self._hand_prev_point = None
        else:
            self._hand_pinching = False
            point = pose.get("point")
            if mode == "rotate" and isinstance(point, (list, tuple)) and len(point) == 2:
                point = (max(0.0, min(1.0, float(point[0]))),
                         max(0.0, min(1.0, float(point[1]))))
                previous = self._hand_prev_point
                if previous is not None:
                    dx, dy = point[0] - previous[0], point[1] - previous[1]
                    if abs(dx) < 0.20 and abs(dy) < 0.20:
                        self._hand_yaw = max(-68.0, min(68.0, self._hand_yaw + dx * 205.0))
                        self._hand_tilt = max(-55.0, min(55.0, self._hand_tilt - dy * 170.0))
                self._hand_prev_point = point
                if pose.get("dual"):
                    angle = float(pose.get("angle", 0.0))
                    if self._hand_prev_angle is not None:
                        delta_angle = (angle - self._hand_prev_angle + 180.0) % 360.0 - 180.0
                        self._hand_rotation = (self._hand_rotation + delta_angle) % 360.0
                    self._hand_prev_angle = angle
                else:
                    self._hand_prev_angle = None
            else:
                self._hand_prev_point = None
                self._hand_prev_angle = None
        self.update()

    def _make_grid(self, W: int, H: int) -> QPixmap:
        """Pre-render the static grid-dot background into a transparent pixmap so
        paintEvent can blit it once per frame instead of running a nested
        drawPoint() loop across the whole widget every 16 ms."""
        pm = QPixmap(max(1, W), max(1, H))
        pm.fill(Qt.GlobalColor.transparent)
        gp = QPainter(pm)
        gp.setPen(QPen(qcol(C.PRI_GHO), 1))
        for x in range(0, W, 48):
            for y in range(0, H, 48):
                gp.drawPoint(x, y)
        gp.end()
        return pm

    def _paint_neural_network_scaled(self, p: QPainter, W: float, H: float,
                                     cx: float, cy: float, fw: float,
                                     orb_mode: bool = False):
        """Low-resolution fallback used only without a hardware GL context."""
        scale = float(getattr(self, "_neural_render_scale", 0.75))
        if scale >= 0.999:
            self._paint_neural_network(p, W, H, cx, cy, fw, orb_mode)
            return
        iw, ih = max(1, round(W * scale)), max(1, round(H * scale))
        image = self._neural_render_image
        if image is None or image.width() != iw or image.height() != ih:
            image = QImage(iw, ih, QImage.Format.Format_ARGB32_Premultiplied)
            self._neural_render_image = image
        image.fill(Qt.GlobalColor.transparent)
        low = QPainter(image)
        if not low.isActive():
            self._paint_neural_network(p, W, H, cx, cy, fw, orb_mode)
            return
        low.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        low.scale(scale, scale)
        self._paint_neural_network(low, W, H, cx, cy, fw, orb_mode)
        low.end()
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QRectF(0, 0, W, H), image)
        p.restore()

    def initializeGL(self) -> None:
        """Log the OpenGL device backing this exact QPainter HUD canvas."""
        self._neural_gl_hardware = False
        try:
            context = self.context()
            if context is None or not context.isValid():
                print("[HUD] OpenGL context unavailable; using scaled QPainter fallback.")
                return
            # PyQt6 does not wrap QOpenGLContext.functions(). Get the
            # matching OpenGL function table through Qt's supported factory.
            from PyQt6.QtOpenGL import QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile

            profile = QOpenGLVersionProfile()
            profile.setVersion(2, 0)
            functions = QOpenGLVersionFunctionsFactory.get(profile, context)
            if functions is None or not functions.initializeOpenGLFunctions():
                print("[HUD] OpenGL functions unavailable; using scaled QPainter fallback.")
                return
            raw = functions.glGetString(0x1F00)  # GL_VENDOR
            # PyQt6 bindings can expose the returned GL string as either str
            # or bytes depending on the binding/runtime. Do not pass an
            # already-decoded str to bytes(), which requires an encoding.
            if isinstance(raw, str):
                vendor = raw or "unknown"
            elif isinstance(raw, (bytes, bytearray, memoryview)):
                vendor = bytes(raw).decode("utf-8", errors="replace") if raw else "unknown"
            else:
                vendor = str(raw) if raw else "unknown"
            software_markers = ("llvmpipe", "softpipe", "software rasterizer", "basic render driver")
            self._neural_gl_hardware = not any(mark in vendor.lower() for mark in software_markers)
            if self._neural_gl_hardware:
                print(f"[HUD] Neural renderer: original QPainter scene on OpenGL GPU ({vendor}).")
            else:
                print(f"[HUD] OpenGL software device detected ({vendor}); using scaled QPainter fallback.")
        except Exception as exc:
            print(f"[HUD] OpenGL device query failed; using scaled QPainter fallback: {exc}")

    def paintGL(self) -> None:
        """Paint the same HUD scene into QOpenGLWidget's current framebuffer."""
        self._paint_canvas()

    def _start_neural_quick(self) -> None:
        """Start the D3D11-compatible Qt Quick neural renderer, if available."""
        global _QUICK_GRAPHICS_API_REQUESTED
        if self._neural_quick_attempted:
            return
        self._neural_quick_attempted = True
        try:
            from PyQt6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface

            # If explicitly enabled, Qt Quick must share the OpenGL backend
            # with this QOpenGLWidget; mixing D3D11 and OpenGL breaks composition.
            if platform.system() == "Windows" and not _QUICK_GRAPHICS_API_REQUESTED:
                QQuickWindow.setGraphicsApi(
                    QSGRendererInterface.GraphicsApi.OpenGL
                )
                _QUICK_GRAPHICS_API_REQUESTED = True

            view = QQuickView()
            view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
            view.setColor(QColor("#050711"))
            view.statusChanged.connect(lambda status, v=view: self._neural_quick_status(v, status))
            container = QWidget.createWindowContainer(view, self)
            container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            container.setGeometry(self.rect())
            container.hide()
            self._neural_quick_view = view
            self._neural_quick_container = container
            qml_path = BASE_DIR / "assets" / "neural" / "neural_gpu.qml"
            view.setSource(QUrl.fromLocalFile(str(qml_path)))
        except Exception as exc:
            self._neural_quick_ready = False
            print(f"[HUD] Qt Quick neural renderer unavailable; using QPainter fallback: {exc}")

    def _neural_quick_status(self, view, status) -> None:
        try:
            from PyQt6.QtQuick import QQuickView
            if status == QQuickView.Status.Ready:
                root = view.rootObject()
                if root is None:
                    raise RuntimeError("Qt Quick scene loaded without a root item")
                self._neural_quick_root = root
                self._neural_quick_ready = True
                try:
                    api = view.rendererInterface().graphicsApi()
                    api_name = getattr(api, "name", str(api).split(".")[-1])
                except Exception:
                    api_name = "initializing"
                if "software" in str(api_name).lower():
                    self._neural_quick_ready = False
                    if self._neural_quick_container is not None:
                        self._neural_quick_container.hide()
                    print("[HUD] Qt Quick is using software rendering; switching to the scaled QPainter fallback.")
                    self.update()
                    return
                print(f"[HUD] Neural renderer: Qt Quick scene graph ({api_name}).")
                self._sync_neural_quick(force=True)
                self.update()
            elif status == QQuickView.Status.Error:
                errors = "; ".join(str(error) for error in view.errors())
                self._neural_quick_ready = False
                if self._neural_quick_container is not None:
                    self._neural_quick_container.hide()
                print(f"[HUD] Qt Quick neural scene failed; using QPainter fallback: {errors}")
                self.update()
        except Exception as exc:
            self._neural_quick_ready = False
            if self._neural_quick_container is not None:
                self._neural_quick_container.hide()
            print(f"[HUD] Qt Quick neural scene setup failed; using QPainter fallback: {exc}")
            self.update()

    def _sync_neural_quick(self, force: bool = False) -> None:
        """Keep the GPU scene's visibility and live JARVIS state in sync."""
        neural_mode = self.hud_style in ("neural", "neural_orb")
        container = self._neural_quick_container
        if getattr(self, "_hand_3d_active", False):
            if self._neural_quick_root is not None:
                self._neural_quick_root.setProperty("active", False)
            if container is not None and container.isVisible():
                container.hide()
            return
        if container is None:
            if neural_mode and self._on_screen() and not self._neural_quick_attempted:
                self._start_neural_quick()
            return
        if not neural_mode or not self._on_screen():
            if self._neural_quick_root is not None:
                self._neural_quick_root.setProperty("active", False)
            if container.isVisible():
                container.hide()
            return
        if not self._neural_quick_ready or self._neural_quick_root is None:
            return
        if container.geometry() != self.rect():
            container.setGeometry(self.rect())
        if not container.isVisible():
            container.show()
            container.raise_()
        now = time.monotonic()
        mode = 1 if self.hud_style == "neural_orb" else 0
        if not force and now - self._neural_quick_last_sync < 0.033 \
                and mode == self._neural_quick_last_mode:
            return
        self._neural_quick_last_sync = now
        self._neural_quick_last_mode = mode
        state = "SPEAKING" if self.speaking else (
            "THINKING" if self.state in ("THINKING", "PROCESSING") else
            ("LISTENING" if self.state == "LISTENING" else "STANDBY")
        )
        root = self._neural_quick_root
        root.setProperty("active", True)
        root.setProperty("mode", mode)
        root.setProperty("activityState", state)
        root.setProperty("energy", float(max(0.0, min(1.0, self._neural_energy))))
        root.setProperty("amplitude", float(max(0.0, min(1.0, self._amp_disp))))
        root.setProperty("callCount", int(self._neural_call_count))

    def _step(self):
        self._tick += 1
        now = time.time()

        if abs(self._hand_zoom_target - self._hand_zoom) > 0.001:
            self._hand_zoom += (self._hand_zoom_target - self._hand_zoom) * 0.20

        # ── Live audio reactivity ────────────────────────────────────────────
        # A viseme schedule, if one is playing, gives both the level and the
        # mouth shape for this exact instant; otherwise fall back to the peak
        # level the audio threads pushed in.
        v_open = v_wide = v_level = None
        v_seq = None
        sched = self._visemes
        if sched is not None:
            frames, t0, hop = sched
            i = int((now - t0) / hop)
            if 0 <= i < len(frames):
                # Hand over *every* frame since the last tick, not just the one
                # under the cursor. This timer runs at 60 Hz but the paint is
                # throttled and the machine may be busy, so a tick can span two
                # or three 20 ms frames — and a consonant closure is only two
                # frames long. Sampling one and discarding the rest is how the
                # closures between words went missing.
                j = self._vis_i if self._vis_i is not None else i
                v_seq = frames[max(0, j):i + 1]
                self._vis_i = max(j, i + 1)
                v_level, v_open, v_wide = frames[i]
                if v_seq:
                    peak = max(f[0] for f in v_seq)
                    if peak > self._live_amp:
                        self._live_amp = peak
            elif i >= len(frames):
                self._visemes = None        # schedule spent
                self._vis_i = None

        # Audio threads push peaks into _live_amp; decay it toward silence so
        # gaps between chunks fade out instead of freezing, then smooth it.
        self._live_amp *= 0.86
        self._amp_disp += (self._live_amp - self._amp_disp) * 0.45
        amp = self._amp_disp

        # The avatar animates off the very same smoothed level the waveform
        # uses — one audio source, so the mouth can never drift out of sync.
        dt = now - self._step_t
        self._step_t = now
        # Integrated, not derived from absolute time: multiplying wall-clock by
        # a rate that changes with state jumps the rings the instant JARVIS
        # starts talking. Same lesson the head's sway taught.
        self._core_phase += min(0.10, max(0.0, dt))
        network_target = 0.12
        if self.state in ("THINKING", "PROCESSING"):
            network_target = 0.82
        elif self.speaking:
            network_target = 0.42 + amp * 0.48
        elif self.state == "LISTENING":
            network_target = 0.24 + amp * 0.40
        if self.muted:
            network_target *= 0.45
        self._neural_energy += (network_target - self._neural_energy) * 0.16
        self._neural_flash *= 0.91
        self._neural_phase += min(0.12, max(0.0, dt)) * (1.7 + self._neural_energy * 5.5)
        self._sync_neural_quick()

        if self._avatar is not None and self.hud_style == "face":
            self._avatar.step(dt, amp, speaking=self.speaking,
                              muted=self.muted, state=self.state,
                              v_open=v_open, v_wide=v_wide or 0.0,
                              v_level=v_level, v_seq=v_seq,
                              v_hop=(sched[2] if sched is not None else 0.02))
        else:
            # Fallback core: slow "breathing" base target, lifted by the level.
            if now - self._last_t > (0.12 if self.speaking else 0.5):
                if self.speaking:
                    self._base_scale = 1.03
                    self._base_halo  = 122.0
                elif self.muted:
                    self._base_scale = random.uniform(0.998, 1.002)
                    self._base_halo  = random.uniform(15, 28)
                else:
                    self._base_scale = random.uniform(1.001, 1.008)
                    self._base_halo  = random.uniform(48, 68)
                self._last_t = now

            if self.muted:
                self._tgt_scale, self._tgt_halo = self._base_scale, self._base_halo
            elif self.speaking:
                self._tgt_scale = self._base_scale + amp * 0.13
                self._tgt_halo  = self._base_halo  + amp * 95.0
            else:
                self._tgt_scale = self._base_scale + amp * 0.06
                self._tgt_halo  = self._base_halo  + amp * 75.0

            sp = 0.38 if self.speaking else (0.30 if amp > 0.02 else 0.15)
            self._scale += (self._tgt_scale - self._scale) * sp
            self._halo  += (self._tgt_halo  - self._halo)  * sp

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
            _blinked = True
        else:
            _blinked = False

        # Repaint throttling — advancing the animation state above is cheap at
        # 60 Hz, but the paint is heavy. Active (speaking, audio, thinking) runs
        # at ~30 Hz, which is the frame rate animation has used for talking
        # characters forever and is indistinguishable here; idle drops to ~20 Hz
        # so a sleeping HUD stops pinning a CPU core. The visuals stay smooth
        # either way because the animation state keeps stepping at 60 Hz.
        self._paint_tick = (self._paint_tick + 1) % 6
        active = (self.speaking or amp > 0.02
                  or self.state in ("THINKING", "PROCESSING")
                  or (self.hud_style in ("neural", "neural_orb")
                      and self._neural_flash > 0.025))
        neural_fullrate = (self.hud_style in ("neural", "neural_orb")
                           and (self._neural_gl_hardware
                                or self._neural_render_scale <= 0.75))
        if _blinked or neural_fullrate \
                or (self._paint_tick % 2 == 0 if active
                    else self._paint_tick % 3 == 0):
            # Nothing is on screen when the window is hidden or minimised, so
            # rendering the avatar into it is pure waste — and this app is meant
            # to sit running all day. The animation state above keeps stepping,
            # so it picks up mid-motion instead of snapping when you come back.
            if self._on_screen() and not (
                self._neural_quick_ready
                and self.hud_style in ("neural", "neural_orb")
                and not self._hand_3d_active
            ):
                self.update()

    def _on_screen(self) -> bool:
        """True only when this canvas can actually be seen by the user."""
        try:
            if not self.isVisible():
                return False
            win = self.window()
            return not (win.isMinimized() or win.isHidden())
        except Exception:
            return True      # never let a visibility check stop the HUD drawing

    # ── reactor core ─────────────────────────────────────────────────────────
    # The centrepiece for anyone who did not want a face looking back at them.
    # Built from the same budget as the head — QPainter on the HUD render surface — and
    # from the same principle: everything on it means something. The rings turn
    # at a rate the state sets, the spectrum ring is the real audio level, and
    # the core brightens with the voice. Nothing here is decoration that moves
    # for its own sake, which is what made the old glowing orb feel dead.

    def _core_colours(self):
        if self.muted:
            return qcol(C.MUTED_C), qcol(C.MUTED_C)
        if self.speaking:
            return qcol(C.PRI), qcol(C.ACC)
        if self.state in ("THINKING", "PROCESSING"):
            return qcol(C.PRI), qcol(C.ACC2)
        if self.state == "LISTENING":
            return qcol(C.PRI), qcol(C.GREEN)
        return qcol(C.PRI), qcol(C.PRI_DIM)

    def _paint_core(self, p: QPainter, cx: float, cy: float, r: float,
                    W: float = 0.0, H: float = 0.0):
        """Draw the reactor at (cx, cy) with outer radius r, using the whole
        canvas (W x H) for the marks that frame it."""
        main, acc = self._core_colours()
        bg = qcol(C.BG)
        amp = self._amp_disp
        t = self._core_phase
        live = (self.speaking or amp > 0.04) and not self.muted

        def blend(col: QColor, a: float) -> QColor:
            """Pre-mix onto the background instead of asking Qt to composite.
            The raster engine's opaque path is several times faster than its
            translucent one, and everything here is a line or an arc."""
            k = max(0.0, min(1.0, a))
            return QColor(int(bg.red()   + (col.red()   - bg.red())   * k),
                          int(bg.green() + (col.green() - bg.green()) * k),
                          int(bg.blue()  + (col.blue()  - bg.blue())  * k))

        p.setBrush(Qt.BrushStyle.NoBrush)

        # 1. The atmosphere. One radial gradient doing what a stack of discs did
        #    badly: a wide, soft body of light that gives the thing presence
        #    before any detail is read. This single element decides whether the
        #    HUD looks vast or looks small, so it is drawn first and drawn big.
        # Concentrated rather than spread: a gradient reaching the outer rim
        # washes the whole disc a flat dim blue and reads as fog. Ending it at
        # two thirds leaves it a body of light with somewhere to fall off to,
        # which is what makes it look lit rather than tinted.
        lift = 1.0 + 0.55 * amp + (0.18 if self.speaking else 0.0)
        p.setPen(Qt.PenStyle.NoPen)
        for gr, a0, a1 in ((r * 0.70, 0.30, 0.0), (r * 0.34, 0.34, 0.0)):
            g = QRadialGradient(cx, cy, gr)
            g.setColorAt(0.00, blend(main, min(0.95, a0 * lift)))
            g.setColorAt(0.45, blend(main, min(0.95, a0 * lift * 0.52)))
            g.setColorAt(0.78, blend(main, min(0.95, a0 * lift * 0.18)))
            g.setColorAt(1.00, blend(main, a1))
            p.setBrush(QBrush(g))
            p.drawEllipse(QRectF(cx - gr, cy - gr, gr * 2, gr * 2))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # 2. Frame marks at the corners of the whole canvas, not of the circle.
        #    They are what set the scale: the eye reads the reactor as filling
        #    the room rather than sitting in the middle of it.
        if W > 40 and H > 40:
            m, arm = min(W, H) * 0.035, min(W, H) * 0.055
            p.setPen(QPen(blend(main, 0.45), 1.4))
            for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                x = cx + sx * (W / 2 - m)
                y = cy + sy * (H / 2 - m)
                p.drawLine(QLineF(x, y, x - sx * arm, y))
                p.drawLine(QLineF(x, y, x, y - sy * arm))

        # 3. Crosshair across the full canvas, broken around the core so it
        #    frames the reactor rather than crossing it.
        p.setPen(QPen(blend(main, 0.16), 1))
        gap = r * 0.62
        if W > 40:
            p.drawLine(QLineF(cx - W / 2, cy, cx - gap, cy))
            p.drawLine(QLineF(cx + gap, cy, cx + W / 2, cy))
        if H > 40:
            p.drawLine(QLineF(cx, cy - H / 2, cx, cy - gap))
            p.drawLine(QLineF(cx, cy + gap, cx, cy + H / 2))

        # 4. Two thin outer circles. Sparse on purpose — a dense ring reads as a
        #    grey band at this size, and restraint is what made the original
        #    look expensive.
        for rr, a in ((1.00, 0.34), (0.93, 0.16)):
            rad = r * rr
            p.setPen(QPen(blend(main, a), 1))
            p.drawEllipse(QRectF(cx - rad, cy - rad, rad * 2, rad * 2))

        # 5. Long, sparse graduations: 24 majors reaching well in from the rim,
        #    with shorter minors between them.
        major, minor = [], []
        for i in range(72):
            a = math.radians(i * 5.0)
            ca, sa = math.cos(a), math.sin(a)
            if i % 3 == 0:
                major.append(QLineF(cx + ca * r * 0.885, cy + sa * r * 0.885,
                                    cx + ca * r * 0.985, cy + sa * r * 0.985))
            else:
                minor.append(QLineF(cx + ca * r * 0.945, cy + sa * r * 0.945,
                                    cx + ca * r * 0.985, cy + sa * r * 0.985))
        p.setPen(QPen(blend(main, 0.42), 1.3))
        p.drawLines(major)
        p.setPen(QPen(blend(main, 0.18), 1))
        p.drawLines(minor)

        # 6. Sweeping arcs. Long spans, not dashes — the original's grandeur
        #    came from a few big strokes. Speed is the state: idle drifts,
        #    thinking hurries, speaking runs.
        rate = 1.0 + (1.9 if self.state in ("THINKING", "PROCESSING") else 0.0) \
                   + (1.2 if self.speaking else 0.0)
        for k, (rr, span, count, dirn, col, a, wid) in enumerate((
                (0.955, 118, 2, +1, acc,  0.75, 2.0),
                (0.845, 82,  3, -1, main, 0.38, 1.3),
                (0.760, 150, 1, +1, acc,  0.45, 1.6),
                (0.660, 64,  4, -1, main, 0.26, 1.1),
                (0.545, 128, 2, +1, main, 0.30, 1.2))):
            rad = r * rr
            p.setPen(QPen(blend(col, a), wid))
            box = QRectF(cx - rad, cy - rad, rad * 2, rad * 2)
            base = (t * rate * (9 + k * 6) * dirn) % 360.0
            for sgm in range(count):
                p.drawArc(box, int((base + sgm * (360.0 / count)) * 16),
                          int(span * 16))

        # 7. The voice, as a ring of graduations that grow with it. Kept out at
        #    a wide radius so it never crowds the middle.
        n = 60
        ring = r * 0.415
        spikes = []
        for i in range(n):
            a = math.radians(i * (360.0 / n))
            ca, sa = math.cos(a), math.sin(a)
            wob = 0.5 + 0.5 * math.sin(t * 2.3 + i * 0.42)
            idle = 0.018 + 0.012 * math.sin(t * 1.2 + i * 0.7)
            h = r * (idle + (amp * 0.20 * wob if live else 0.0))
            spikes.append(QLineF(cx + ca * ring, cy + sa * ring,
                                 cx + ca * (ring + h), cy + sa * (ring + h)))
        p.setPen(QPen(blend(acc if live else main, 0.25 + 0.5 * amp), 1.6))
        p.drawLines(spikes)

        # 8. The inner ring the name sits in.
        inner = r * 0.355
        p.setPen(QPen(blend(acc, 0.30 + 0.45 * amp), 1.5))
        p.drawEllipse(QRectF(cx - inner, cy - inner, inner * 2, inner * 2))

        # 9. The name, sized from the string rather than from the radius alone:
        #    "J.A.R.V.I.S" and a name someone renamed to "MAX" are very
        #    different widths, and a fixed fraction of r spills one of them past
        #    the ring it is supposed to sit inside.
        name = self._assistant_name or ""
        if name:
            space = max(1.0, r * 0.018)
            fsz = max(8, int(min(r * 0.105,
                                 (inner * 1.75) / max(1, len(name)) * 1.6 - space)))
            f = QFont("Courier New", fsz, QFont.Weight.Bold)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, space)
            p.setFont(f)
            p.setPen(QPen(blend(qcol(C.WHITE), 0.6 + 0.4 * min(1.0, amp * 2)), 1))
            p.drawText(QRectF(cx - r, cy - fsz, r * 2, fsz * 2),
                       Qt.AlignmentFlag.AlignCenter, name)

    def paintEvent(self, event):
        # QOpenGLWidget prepares and binds its framebuffer in its own paintEvent
        # before calling our paintGL(). Keep a QWidget-only fallback for hosts
        # where the optional Qt OpenGL module is unavailable.
        if _OPENGL_CANVAS_AVAILABLE:
            super().paintEvent(event)
        else:
            self._paint_canvas()

    def _paint_canvas(self):
        if (self._neural_quick_ready and self.hud_style in ("neural", "neural_orb")
                and not self._hand_3d_active):
            self._sync_neural_quick()
            return
        p = QPainter(self)
        if not p.isActive():      # device not ready (e.g. 0-size during layout) — skip cleanly
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # grid dots — blitted from a cached layer; rebuilt only when the size
        # or the theme's ghost colour changes (so live re-theming still works).
        if self.hud_style not in ("neural", "neural_orb"):
            _gkey = (W, H, C.PRI_GHO)
            if self._grid_cache is None or self._grid_key != _gkey:
                self._grid_cache = self._make_grid(W, H)
                self._grid_key   = _gkey
            p.drawPixmap(0, 0, self._grid_cache)

        # ── holographic head ────────────────────────────────────────────────
        # Sized to the band between the top of the canvas and the status line,
        # capped by width, so it fills the HUD at any window size — including
        # fullscreen — without ever colliding with the status text below.
        _sy_status = cy + fw * 0.40
        if self._avatar is not None and self.hud_style == "face":
            _band_t = 12.0
            _band_h = max(60.0, _sy_status - 12.0 - _band_t)
            _r_head = min(fw * 0.355, _band_h / (self._avatar.SPAN + 0.08))
            _head_cy = _band_t + (_band_h - self._avatar.SPAN * _r_head) / 2.0 + _r_head

            if self.muted:
                _main = _acc = qcol(C.MUTED_C)
            else:
                _main = qcol(C.PRI)
                if self.speaking:
                    _acc = qcol(C.ACC)
                elif self.state in ("THINKING", "PROCESSING"):
                    _acc = qcol(C.ACC2)
                elif self.state == "LISTENING":
                    _acc = qcol(C.GREEN)
                else:
                    _acc = qcol(C.PRI)
            self._avatar.paint(p, cx, _head_cy, _r_head, _main, _acc, qcol(C.BG))

        elif self.hud_style in ("neural", "neural_orb"):
            if self._hand_3d_active:
                p.save()
                p.translate(cx, cy)
                p.scale(self._hand_zoom, self._hand_zoom)
                p.translate(-cx, -cy)
                self._paint_neural_hand_3d(p, W, H, cx, cy, fw)
                p.restore()
            else:
                p.save()
                p.translate(cx, cy)
                p.rotate(self._hand_rotation)
                yaw = math.radians(self._hand_yaw)
                pitch = math.radians(self._hand_tilt)
                p.shear(math.sin(yaw) * 0.24, -math.sin(pitch) * 0.18)
                p.scale(0.82 + 0.18 * abs(math.cos(yaw)),
                        0.82 + 0.18 * abs(math.cos(pitch)))
                p.scale(self._hand_zoom, self._hand_zoom)
                p.translate(-cx, -cy)
                if _OPENGL_CANVAS_AVAILABLE and self._neural_gl_hardware:
                    self._paint_neural_network(
                        p, W, H, cx, cy, fw, orb_mode=self.hud_style == "neural_orb"
                    )
                else:
                    self._paint_neural_network_scaled(
                        p, W, H, cx, cy, fw, orb_mode=self.hud_style == "neural_orb"
                    )
                p.restore()

        # JARVIS logo / reactor core — kept as the original selectable mode
        # and as a fallback if the face mesh is unavailable.
        else:
            _band_t = 12.0
            _band_h = max(60.0, _sy_status - 12.0 - _band_t)
            _r = min(W * 0.46, _band_h / 2.0)
            self._paint_core(p, cx, _band_t + _band_h / 2.0, _r, W, _band_h)

        # Optical-bench reticle around the avatar/reactor. The unequal corner
        # brackets and calibration ticks borrow from instrument faceplates,
        # giving the centre display a designed frame instead of a floating orb.
        _m = max(12.0, min(W, H) * 0.035)
        _a = max(10.0, min(W, H) * 0.045)
        _lines = []
        for _x, _y, _sx, _sy in (
            (_m, _m, 1, 1), (W - _m, _m, -1, 1),
            (_m, H - _m, 1, -1), (W - _m, H - _m, -1, -1),
        ):
            _lines.extend((QLineF(_x, _y, _x + _sx * _a, _y),
                           QLineF(_x, _y, _x, _y + _sy * _a)))
        p.setPen(QPen(qcol(C.BORDER_A), 1.0))
        p.drawLines(_lines)
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1.0))
        p.drawText(QRectF(_m + 4, _m - 2, 148, 12),
                   Qt.AlignmentFlag.AlignLeft, "OPTIC ARRAY  //  01")
        p.drawText(QRectF(W - _m - 152, _m - 2, 148, 12),
                   Qt.AlignmentFlag.AlignRight, "SENSOR MATRIX  //  LIVE")
        _ticks = []
        for _i in range(1, 8):
            _ty = _m + (H - 2 * _m) * _i / 8
            _length = 7.0 if _i % 2 else 12.0
            _ticks.extend((QLineF(_m, _ty, _m + _length, _ty),
                           QLineF(W - _m - _length, _ty, W - _m, _ty)))
        p.setPen(QPen(qcol(C.BORDER), 1.0))
        p.drawLines(_ticks)

        # Privacy Lock overlay is driven by the existing shared AuthManager.
        # Do not create a second security state machine in the UI.
        try:
            from core.security import get_auth_manager
            _privacy_locked = get_auth_manager().is_silent()
        except Exception:
            _privacy_locked = False
        if _privacy_locked:
            p.fillRect(self.rect(), qcol("#090002"))
            p.setPen(QPen(qcol("#FF5268"), 3))
            p.setBrush(QBrush(qcol("#200005")))
            shield_r = min(W, H) * 0.25
            p.drawEllipse(QRectF(cx - shield_r, cy - shield_r, shield_r * 2, shield_r * 2))
            p.setFont(QFont("Courier New", 16, QFont.Weight.Bold))
            p.setPen(QPen(qcol("#FF5268"), 1))
            p.drawText(QRectF(0, cy - 20, W, 40), Qt.AlignmentFlag.AlignCenter, "PRIVACY LOCK")
            p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            p.drawText(QRectF(0, cy + 30, W, 34), Qt.AlignmentFlag.AlignCenter,
                       "SYSTEM LOCKED — PRIVATE ACCESS BLOCKED")
            p.end()
            return

        # status text
        sy = _sy_status
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform — reacts to the real audio level (mic while listening,
        # JARVIS's own voice while speaking). Falls back to a gentle idle
        # ripple when there's no sound. _amp_disp is the smoothed 0–1 level.
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        amp = self._amp_disp
        mid = (N - 1) / 2.0
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            else:
                env     = (1.0 - abs(i - mid) / mid) ** 0.7      # center-weighted hump
                shimmer = 0.55 + 0.45 * math.sin(self._tick * 0.18 + i * 0.7)
                idle    = 3.0 + 2.0 * math.sin(self._tick * 0.09 + i * 0.6)
                hgt     = int(max(2, min(24, idle + amp * 22.0 * env * shimmer)))
                if amp > 0.05:
                    cl = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
                else:
                    cl = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

        p.end()   # end deterministically so the backing store never flushes an active painter


class NeuralImmersiveOverlay(QWidget):
    """Full-window neural view with a small, persistent desktop control strip."""

    def __init__(self, face_path: str, assistant_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("NeuralImmersiveOverlay")
        # This is a real opaque window layer over the desktop console. The
        # explicit paint below prevents console text/widgets bleeding through
        # during resize, repaint, or transparent child-widget updates.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#NeuralImmersiveOverlay { background-color: #03050C; }")
        self.hud = HudCanvas(face_path, assistant_name, self, enable_avatar=False)
        self.hud.hud_style = "neural"
        self.on_command = None
        self.on_mute = None
        self.on_interrupt = None
        self.on_wake = None
        self.on_console = None
        self.on_hand_control = None
        self.on_hand_reset = None
        self._neural_hand_view = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 10, 20, 12)
        root.setSpacing(4)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        brand = QLabel("J.A.R.V.I.S  /  NEURAL FIELD")
        brand.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        brand.setStyleSheet("color: #AFC1F4; background: transparent;")
        bar.addWidget(brand)
        self.state_label = QLabel("INITIALISING")
        self.state_label.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.state_label.setStyleSheet("color: #56E5FF; background: transparent;")
        bar.addWidget(self.state_label)
        bar.addStretch(1)

        self.mute_button = self._button("MIC  /  ON", "#62F0B2")
        self.mute_button.clicked.connect(lambda: self.on_mute and self.on_mute())
        bar.addWidget(self.mute_button)
        interrupt_button = self._button("INTERRUPT  [ESC]", "#FF6682")
        interrupt_button.clicked.connect(
            lambda: self.on_interrupt and self.on_interrupt()
        )
        bar.addWidget(interrupt_button)
        self.wake_button = self._button("SLEEP / WAKE", "#FFBF55")
        self.wake_button.clicked.connect(lambda: self.on_wake and self.on_wake())
        bar.addWidget(self.wake_button)
        self.hand_button = self._button("HAND CONTROL", "#55E9FF")
        self.hand_button.setToolTip(
            "Ask for camera permission, then rotate the neural field with an open palm and resize by pinching."
        )
        self.hand_button.clicked.connect(
            lambda: self.on_hand_control and self.on_hand_control()
        )
        bar.addWidget(self.hand_button)
        self.hand_reset_button = self._button("RESET FIELD", "#AFC1F4")
        self.hand_reset_button.setToolTip("Center and restore the neural field scale")
        self.hand_reset_button.clicked.connect(
            lambda: self.on_hand_reset and self.on_hand_reset()
        )
        bar.addWidget(self.hand_reset_button)
        console_button = self._button("OPEN CONSOLE", "#BFA4FF")
        console_button.clicked.connect(lambda: self.on_console and self.on_console())
        bar.addWidget(console_button)
        root.addLayout(bar)

        root.addWidget(self.hud, stretch=1)

        if _load_webengine():
            self._neural_hand_view = QWebEngineView(self)
            self._neural_hand_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self._neural_hand_view.setStyleSheet("background: transparent; border: none;")
            self._neural_hand_view.page().setBackgroundColor(QColor(0, 0, 0, 0))
            self._neural_hand_view.hide()

        command_bar = QHBoxLayout()
        command_bar.setSpacing(7)
        prompt = QLabel("COMMAND  ›")
        prompt.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        prompt.setStyleSheet("color: #AFC1F4; background: transparent;")
        command_bar.addWidget(prompt)
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Type to JARVIS…")
        self.command_input.setFixedHeight(34)
        self.command_input.setFont(QFont("Consolas", 10))
        self.command_input.setStyleSheet("""
            QLineEdit { background: rgba(7, 12, 26, 220); color: #F1F4FF;
                border: 1px solid #36446A; border-radius: 4px; padding: 4px 9px; }
            QLineEdit:focus { border-color: #A66CFF; }
        """)
        self.command_input.returnPressed.connect(self._send_command)
        command_bar.addWidget(self.command_input, stretch=1)
        send = self._button("SEND", "#57DFFF")
        send.setFixedWidth(74)
        send.clicked.connect(self._send_command)
        command_bar.addWidget(send)
        root.addLayout(command_bar)

    @staticmethod
    def _button(text: str, color: str) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(30)
        button.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        button.setStyleSheet(f"""
            QPushButton {{ color: {color}; background: rgba(8, 13, 28, 225);
                border: 1px solid {color}; border-radius: 3px; padding: 0 10px; }}
            QPushButton:hover {{ background: rgba(28, 34, 61, 245); }}
        """)
        return button

    def _send_command(self) -> None:
        text = self.command_input.text().strip()
        if not text:
            return
        self.command_input.clear()
        if self.on_command:
            self.on_command(text)

    def set_state(self, state: str) -> None:
        self.hud.state = state
        self.hud.speaking = state == "SPEAKING"
        display = str(state or "").replace("_", " ").upper()
        self.state_label.setText(display)
        color = {
            "SPEAKING": "#FF70A4",
            "THINKING": "#FFB33F",
            "PROCESSING": "#D65BFF",
            "LISTENING": "#55F2A5",
            "SLEEPING": "#8C9BB8",
            "MUTED": "#FF5268",
            "ERROR": "#FF5268",
            "DISCONNECTED": "#FF5268",
        }.get(display, "#57DFFF")
        self.state_label.setStyleSheet(f"color: {color}; background: transparent;")
        self.wake_button.setText("WAKE JARVIS" if display == "SLEEPING" else "SLEEP / WAKE")

    def paintEvent(self, event):
        painter = QPainter(self)
        if painter.isActive():
            painter.fillRect(self.rect(), QColor("#03050C"))
            painter.end()

    def set_muted(self, muted: bool) -> None:
        self.hud.muted = bool(muted)
        self.mute_button.setText("MIC  /  MUTED" if muted else "MIC  /  ON")
        self.mute_button.setStyleSheet(self._button_style("#FF5268" if muted else "#62F0B2"))

    def set_hand_control_active(self, active: bool) -> None:
        self.hand_button.setText("STOP HAND" if active else "HAND CONTROL")
        self.hand_button.setStyleSheet(
            self._button_style("#FF6682" if active else "#55E9FF")
        )
        if self._neural_hand_view is not None:
            self._neural_hand_view.setVisible(bool(active))
            if active:
                self._neural_hand_view.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._neural_hand_view is not None:
            size = 258
            self._neural_hand_view.setGeometry(
                max(12, self.width() - size - 22), 54, size, size
            )

    @staticmethod
    def _button_style(color: str) -> str:
        return f"""
            QPushButton {{ color: {color}; background: rgba(8, 13, 28, 225);
                border: 1px solid {color}; border-radius: 3px; padding: 0 10px; }}
            QPushButton:hover {{ background: rgba(28, 34, 61, 245); }}
        """



# HUD widgets and overlay panels live in ui/overlays.py. Imported here, after the
# theme helpers above are defined, because overlays.py imports those from ui.
from .overlays import (  # noqa: E402, F401 - re-exported as part of the ui API
    MetricBar,
    LogWidget,
    _file_category,
    _fmt_size,
    FileDropZone,
    _DropCanvas,
    _CameraPreview,
    ProviderTile,
    SetupOverlay,
    HueWheel,
    CustomizeOverlay,
    VoicePersonalityOverlay,
    PluginManagerOverlay,
    _HudOverlay,
    ConfirmBanner,
    AudioDeviceOverlay,
    MemoryOverlay,
    ClipboardPanel,
    PluginSettingsOverlay,
    RemoteKeyOverlay,
    AIProviderOverlay,
    NewsBriefingOverlay,
    _FILE_ICONS,
    _EXT_TO_CAT,
)


class MainWindow(QMainWindow):
    _close_sig       = pyqtSignal()
    _log_sig        = pyqtSignal(str)
    _state_sig      = pyqtSignal(str)
    _logo_level_sig = pyqtSignal(object)  # audio amplitude, queued from audio workers
    _audio_level_sig = pyqtSignal(float)  # HUD waveform level, applied on the Qt thread
    _visemes_sig = pyqtSignal(object, float, float)  # frames, hop, playback start time
    _avatar_cue_sig = pyqtSignal(str)
    _hud_pulse_sig  = pyqtSignal(str)
    _content_sig    = pyqtSignal(str, str)   # (title, text) — thread-safe content display
    _workspace_sig  = pyqtSignal(str, object) # (view type, payload) — thread-safe HUD viewer
    _holo_news_sig  = pyqtSignal(str)          # voice-requested publisher/article in Holo
    _holo_stop_sig  = pyqtSignal()
    _earth_sig      = pyqtSignal(str, str, str)  # destination, origin, mode
    _reconfig_sig   = pyqtSignal()           # trigger setup overlay from any thread
    _camera_sig     = pyqtSignal(bytes)      # show camera frame preview (small overlay)
    _cam_stream_sig = pyqtSignal(bool)       # True=start live stream, False=stop
    _cam_frame_sig  = pyqtSignal(bytes)      # live camera frame → HUD area
    _clipboard_sig  = pyqtSignal(str)        # clipboard text changed (thread-safe)
    _confirm_sig    = pyqtSignal(str, str)   # (title, detail) — irreversible-action gate
    _confirm_hide_sig = pyqtSignal()
    _voice_ui_command_sig = pyqtSignal(object)  # parsed voice command → Qt thread
    _pin_prompt_sig = pyqtSignal(object)  # marshal owner PIN dialogs to the Qt thread
    _neural_hand_start_sig = pyqtSignal()     # marshal camera startup from confirmation worker to Qt
    _wake_dl_sig    = pyqtSignal(bool, str)  # wake-word install finished (ok, message)
    _quiz_sig       = pyqtSignal(str, object, object)  # (topic, questions, grader)
    _quiz_hide_sig  = pyqtSignal()
    _review_sig     = pyqtSignal(str, str, object, object)  # document review payload
    _voice_id_enabled_sig = pyqtSignal(bool)

    def __init__(self, face_path: str):
        super().__init__()
        self._session_started_at = time.monotonic()
        self._face_path = face_path

        # Load customization from config
        _cfg = _read_full_config()
        self._assistant_name: str = (_cfg.get("assistant_name") or "JARVIS").strip()
        _display = self._assistant_name.upper()

        # Apply the saved UI colour BEFORE panels/stylesheets are built
        _ui_color = (_cfg.get("ui_color") or "").strip()
        if _ui_color and _ui_color.lower() != DEFAULT_UI_COLOR:
            apply_ui_accent(_ui_color)

        self.setWindowTitle(f"{_display} — {APP_VERSION}")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command   = None
        self.on_remote_clicked = None   # callable: () -> (url, key) | None
        self.on_interrupt      = None   # callable: () -> None — stop JARVIS mid-speech
        self.on_voice_change   = None   # callable: () -> None — rebuild session with new voice
        self.on_audio_device_change = None  # callable: () -> None — reopen audio streams
        self.on_voice_personality_change = None  # callable: () -> None — apply saved response style
        self.on_voice_preview = None   # callable: (vocal settings) -> bool
        self._confirm_overlay  = None   # live ConfirmBanner, if one is on screen
        self._voice_control_overlay = None  # active modal-like overlay for voice-target scoping
        self.get_plugins       = None   # callable: () -> list[dict], set by JarvisLive
        self.get_plugin_settings = None # callable: () -> list[dict] settings schemas, set by JarvisLive
        self.on_wake_toggle    = None   # callable: (enable: bool) -> str, set by JarvisLive
        self.on_wake_manual    = None   # callable: () -> None — manual sleep/wake
        self.on_voice_id_action = None  # callable: (action: str) -> status text
        self.on_push_to_talk   = None   # callable: (enable: bool) -> str scope
        self.ptt_hold          = None   # callable: (held: bool) -> None — windowed chord
        self.wake_get_state    = None   # callable: () -> dict {enabled, awake, ready}
        self._muted            = False
        self._current_file: str | None = None
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._customize_overlay: CustomizeOverlay | None = None
        self._personality_overlay: VoicePersonalityOverlay | None = None
        self._provider_overlay: AIProviderOverlay | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        # Keep the hologram as the primary focus on launch. Telemetry remains
        # available from the compact header control without consuming HUD width.
        self._left_panel.hide()
        body.addWidget(self._left_panel, stretch=0)

        # Center column: HUD + resizable content panel via QSplitter
        self.hud = HudCanvas(face_path, _display)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._content_panel = self._build_content_panel()
        self._quiz_panel = self._build_quiz_panel()

        # Live camera container — replaces HUD when camera stream is active
        _cam_cont = QWidget()
        _cam_cont.setStyleSheet("background: #000308;")
        _cam_v = QVBoxLayout(_cam_cont)
        _cam_v.setContentsMargins(0, 0, 0, 0)
        _cam_v.setSpacing(0)
        _cam_hdr = QHBoxLayout()
        _cam_hdr.setContentsMargins(8, 5, 8, 5)
        _cam_title = QLabel("◈  CAMERA FEED")
        _cam_title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _cam_hdr.addWidget(_cam_title)
        _cam_hdr.addStretch()
        _cam_x = QPushButton("✕  CLOSE")
        _cam_x.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_x.setCursor(Qt.CursorShape.PointingHandCursor)
        _cam_x.setStyleSheet(f"""
            QPushButton {{
                color: {C.TEXT_DIM}; background: transparent;
                border: none; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        _cam_x.clicked.connect(self.stop_camera_stream)
        _cam_hdr.addWidget(_cam_x)
        _cam_v.addLayout(_cam_hdr)
        self._cam_live_lbl = QLabel()
        self._cam_live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_live_lbl.setStyleSheet("background: transparent;")
        self._cam_live_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        _cam_v.addWidget(self._cam_live_lbl, stretch=1)

        # Bihansa Mode Hologram & Preferences
        try:
            from ui.hologram.bihansa_hologram import BihansaHologramWidget
            from ui.hologram.bihansa_settings import BihansaModeSettings
            self._bihansa_settings = BihansaModeSettings()
            self._bihansa_hologram = BihansaHologramWidget(self.centralWidget())
            self._bihansa_hologram.set_reduced_motion(self._bihansa_settings.reduced_motion)
            self._bihansa_hologram.set_glow_intensity(self._bihansa_settings.glow_intensity)
            self._bihansa_hologram.set_animation_speed(self._bihansa_settings.animation_speed)
        except Exception:
            self._bihansa_settings = None
            self._bihansa_hologram = None

        self._hologram_mode_stack = QStackedWidget()
        self._hologram_mode_stack.addWidget(self.hud)
        if self._bihansa_hologram is not None:
            self._hologram_mode_stack.addWidget(self._bihansa_hologram)

        # Stack: 0 = animated HUD (mode stack), 1 = live camera
        self._hud_cam_stack = QStackedWidget()
        self._hud_cam_stack.addWidget(self._hologram_mode_stack)
        self._hud_cam_stack.addWidget(_cam_cont)
        EarthGlobePanel = _earth_panel_class()
        self._earth_panel = EarthGlobePanel()
        self._earth_panel.close_requested.connect(self._close_earth)
        self._hud_cam_stack.addWidget(self._earth_panel)
        HudWorkspace = _workspace_class()
        self._workspace = HudWorkspace()

        # Keep media/data views beside the hologram instead of replacing its canvas.
        self._workspace_side = QFrame()
        self._workspace_side.setObjectName("WorkspaceGlassPanel")
        self._workspace_side.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._workspace_side.setMinimumWidth(230)
        self._workspace_side.setMaximumWidth(390)
        self._workspace_side.setStyleSheet("""
            QFrame#WorkspaceGlassPanel {
                background: rgba(13, 24, 29, 232);
                border: 1px solid rgba(113, 212, 194, 145);
                border-radius: 10px;
            }
        """)
        self._workspace_side_layout = QVBoxLayout(self._workspace_side)
        self._workspace_side_layout.setContentsMargins(5, 5, 5, 5)
        self._workspace_side_layout.setSpacing(0)
        self._workspace_header = SmartPanelHeader(self._workspace_side)
        self._workspace_header.view_requested.connect(self._on_workspace_shortcut)
        self._workspace_header.close_requested.connect(self._close_workspace)
        self._workspace.tabs.currentChanged.connect(self._sync_workspace_header)
        if self._workspace._web_view is not None:
            self._workspace._web_view.urlChanged.connect(
                self._sync_workspace_web_header
            )
        self._workspace_side_layout.addWidget(self._workspace_header)
        self._workspace_side_layout.addWidget(self._workspace, 1)
        self._workspace_side.hide()
        self._news_briefing_overlay = NewsBriefingOverlay(self._workspace_side)
        self._workspace.news_briefing_items.connect(self._show_news_briefing_overlay)
        self._workspace.news_briefing_ended.connect(self._hide_news_briefing_overlay)
        self._workspace.news_briefing_image_ready.connect(self._set_news_briefing_image)
        self._workspace.news_image_failed.connect(self._set_news_briefing_image_failed)
        self._workspace.close_requested.connect(self._close_workspace)
        self._workspace.interrupt_requested.connect(self._do_interrupt)
        self._workspace.feature_requested.connect(self._open_holo_feature)
        self._workspace.neural_hand_update.connect(self._on_neural_hand_update)
        self._holo_news_sig.connect(self._open_holo_news_voice)
        self._workspace.route_requested.connect(lambda destination, origin: self._show_earth(destination, origin, "flight_route"))
        self._workspace.flight_radar_requested.connect(self._start_flight_radar_from_tab)
        self._workspace.flight_radar_location_requested.connect(self._start_flight_radar_from_tab)
        self._workspace.flight_radar_map_requested.connect(lambda: self._show_earth("", "", "flights"))
        self._earth_panel.flight_radar_updated.connect(self._workspace.show_live_flights)
        self._holo_stop_sig.connect(self._workspace.stop_holo_camera)
        self._earth_open = False
        self._cam_active = False
        self._workspace_open = False

        self._stage_split = QSplitter(Qt.Orientation.Horizontal)
        self._stage_split.setObjectName("HologramWorkspaceSplit")
        self._stage_split.setHandleWidth(5)
        self._stage_split.setStyleSheet(f"""
            QSplitter::handle {{
                background: rgba(113, 212, 194, 72);
                width: 5px;
            }}
            QSplitter::handle:hover {{ background: {C.PRI_DIM}; }}
        """)
        self._stage_split.addWidget(self._hud_cam_stack)
        self._stage_split.addWidget(self._workspace_side)
        self._stage_split.setStretchFactor(0, 5)
        self._stage_split.setStretchFactor(1, 3)
        self._stage_split.setCollapsible(0, False)
        self._stage_split.setCollapsible(1, True)
        self._stage_split.setSizes([900, 0])

        self._center_split = QSplitter(Qt.Orientation.Vertical)
        self._center_split.setStyleSheet(f"""
            QSplitter::handle {{
                background: {C.BORDER};
                height: 4px;
            }}
            QSplitter::handle:hover {{
                background: {C.PRI_DIM};
            }}
        """)
        self._center_split.addWidget(self._stage_split)
        self._center_split.addWidget(self._content_panel)
        self._center_split.addWidget(self._quiz_panel)
        self._center_split.setStretchFactor(0, 3)
        self._center_split.setStretchFactor(1, 1)
        self._center_split.setCollapsible(0, False)
        body.addWidget(self._center_split, stretch=5)

        self._right_panel = self._build_right_panel()
        # Transcript and file history are optional; keep the HUD uncluttered.
        self._right_panel.hide()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        # Quick-access drawer (floating overlay, built after central widget layout is done)
        self._quick_drawer = self._build_quick_drawer()
        self._update_autostart_btn(self._check_autostart())
        from memory.config_manager import get_brief_enabled as _gbe
        self._update_brief_btn(_gbe())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metric update timer
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        # Telemetry is hidden on launch, so avoid polling system metrics until
        # the user opens that panel.
        if self._left_panel.isVisible():
            self._metric_tmr.start(2000)
            self._update_metrics()

        self._close_sig.connect(self.close)
        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._logo_level_sig.connect(self._set_logo_audio_level)
        self._audio_level_sig.connect(self._apply_audio_level)
        self._visemes_sig.connect(self._apply_visemes)
        self._avatar_cue_sig.connect(self.hud.react_avatar_text)
        self._hud_pulse_sig.connect(self._on_hud_activity)
        self._content_sig.connect(self._show_content)
        self._workspace_sig.connect(self._show_workspace)
        self._earth_sig.connect(self._show_earth)
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._confirm_sig.connect(self._show_confirm_banner)
        self._confirm_hide_sig.connect(self._hide_confirm_banner)
        self._voice_ui_command_sig.connect(self._dispatch_voice_ui_command)
        self._pin_prompt_sig.connect(self._run_pin_prompt)
        self._neural_hand_start_sig.connect(self._start_neural_hand_control_after_confirmation)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._cam_frame_sig.connect(self._on_cam_frame)
        self._voice_id_enabled_sig.connect(self._apply_voice_id_enabled)
        self._clipboard_sig.connect(self._show_clipboard_panel)
        self._wake_dl_sig.connect(self._on_wake_install_done)
        self._quiz_sig.connect(self._show_quiz)
        self._quiz_hide_sig.connect(self._hide_quiz)
        self._review_sig.connect(self._show_review)
        self._cam_stop = threading.Event()

        # The supplied JARVIS mark runs as a small, draggable desktop overlay.
        # Its position persists across launches; state and audio are driven by
        # the same UI signals as the rest of the HUD.
        # Keep the logo as an independent top-level window: an owned Qt.Tool
        # window is hidden by Windows when its owner is minimized.
        self._jarvis_logo_overlay = JarvisLogoOverlay()
        self._jarvis_logo_overlay.set_state("INITIALISING")
        self._jarvis_logo_overlay.hide()

        # Camera preview overlay (child of central widget, positioned in resizeEvent)
        self._cam_preview = _CameraPreview(self.centralWidget())

        # Clipboard panel (child of central widget, bottom-center)
        self._clipboard_panel = ClipboardPanel(self.centralWidget())
        self._clipboard_panel.action_requested.connect(self._on_clipboard_action)
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)

        # The immersive neural display is a top-level child overlay. Its own
        # canvas mirrors live state while the normal console remains intact
        # underneath and is one button away.
        self._immersive_overlay = NeuralImmersiveOverlay(
            face_path, _display, self.centralWidget()
        )
        self._immersive_overlay.on_command = self._submit_immersive_command
        self._immersive_overlay.on_mute = self._toggle_mute
        self._immersive_overlay.on_interrupt = self._do_interrupt
        self._immersive_overlay.on_wake = self._tap_wake_manual
        self._immersive_overlay.on_console = self._leave_immersive_view
        self._immersive_overlay.on_hand_control = self._toggle_neural_hand_control
        self._immersive_overlay.on_hand_reset = self._reset_neural_hand_pose
        self._immersive_overlay.set_muted(self._muted)
        self._immersive_overlay.set_state(self.hud.state)
        self._immersive_overlay.hide()
        # The second canvas is dormant until its full-screen view is requested.
        self._immersive_overlay.hud._tmr.stop()
        self._immersive_open = False
        self._neural_hand_active = False
        self._neural_hand_page = None
        self._neural_hand_profile = None
        if self._immersive_overlay._neural_hand_view is not None:
            server = self._workspace._holo_server
            if server is not None and _load_webengine():
                profile = self._workspace._holo_profile
                if profile is None:
                    profile = QWebEngineProfile(self._immersive_overlay._neural_hand_view)
                self._neural_hand_profile = profile
                self._neural_hand_page = QWebEnginePage(
                    profile, self._immersive_overlay._neural_hand_view
                )
                self._neural_hand_page.setBackgroundColor(QColor(0, 0, 0, 0))
                self._neural_hand_page.featurePermissionRequested.connect(
                    self._grant_neural_hand_camera
                )
                self._immersive_overlay._neural_hand_view.setPage(self._neural_hand_page)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_intr = QShortcut(QKeySequence("Escape"), self)
        sc_intr.activated.connect(self._handle_escape)

    def _show_camera_frame(self, img_bytes: bytes):
        """Slot — display camera preview overlay (main thread)."""
        self._cam_preview.show_frame(img_bytes)
        cw = self.centralWidget()
        pw = _CameraPreview._W
        ph = self._cam_preview.height()
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )

    # --- Live camera stream in HUD area ------------------------------------
    def _on_cam_stream(self, start: bool) -> None:
        self._cam_active = bool(start)
        if start:
            self._earth_open = False
            self._hud_cam_stack.setCurrentIndex(1)
        else:
            self._cam_live_lbl.clear()
            if not self._earth_open:
                self._hud_cam_stack.setCurrentIndex(0)

    def _show_earth(self, destination: str = "", origin: str = "", mode: str = "show") -> None:
        self._holo_stop_sig.emit()
        was_fullscreen = self._workspace._is_fullscreen
        self._workspace.restore_to_embedded(self._workspace_side)
        if was_fullscreen:
            self._workspace_side_layout.addWidget(self._workspace)
        self._workspace_side.hide()
        if self._cam_active:
            self.stop_camera_stream()
        self._workspace_open = False
        self._earth_open = True
        self._earth_panel.open_view(destination, origin, mode)
        self._hud_cam_stack.setCurrentWidget(self._earth_panel)

    def _close_earth(self) -> None:
        self._earth_panel.stop_flight_radar()
        self._earth_open = False
        self._hud_cam_stack.setCurrentIndex(1 if self._cam_active else 0)

    def _start_flight_radar_from_tab(self, manual_place: str = "") -> None:
        """Start the shared Earth radar feed while keeping the Flights tab visible."""
        if not manual_place:
            self._workspace.set_live_flights_status("REQUESTING SYSTEM LOCATION  ·  JARVIS will ask before using it")
        if self._cam_active:
            self.stop_camera_stream()
        self._earth_panel.start_flight_radar_in_background(manual_place)

    def _sync_workspace_web_header(self, url: QUrl) -> None:
        """Keep the URL entry and smart header synchronized after web navigation."""
        self._workspace._url_entry.setText(url.toString())
        self._sync_workspace_header(self._workspace.tabs.currentIndex())

    def _sync_workspace_header(self, index: int) -> None:
        """Keep the HTML navigation highlight aligned with native workspace tabs."""
        if index < 0 or not self._workspace_side.isVisible():
            return
        key = next(
            (name for name, tab_index in self._workspace._page_index.items()
             if tab_index == index),
            "command",
        )
        active = {
            "timers": "timers", "news": "news", "video": "media",
            "system": "system",
        }.get(key, "command")
        if key == "web":
            current_url = self._workspace._url_entry.text().casefold()
            active = "music" if "music.youtube.com" in current_url else "media"
        selected_title = self._workspace.tabs.tabText(index).strip()
        if not selected_title:
            selected_title = self._workspace._view_title.text()
        self._workspace_header.set_context(
            active, title=selected_title, status="ACTIVE"
        )

    def _open_bento_dashboard(self) -> None:
        """Open the optional Bento overview as a separate lightweight window."""
        dialog = getattr(self, "_bento_dialog", None)
        if dialog is not None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            timer = getattr(self, "_bento_timer", None)
            if timer is not None and not timer.isActive():
                timer.start()
            self._refresh_bento_dashboard()
            return

        dialog = QDialog(self)
        dialog.setObjectName("BentoDashboard")
        dialog.setWindowTitle("JARVIS  /  BENTO COMMAND DASHBOARD")
        dialog.setModal(False)
        dialog.resize(760, 500)
        dialog.setMinimumSize(620, 420)
        dialog.setStyleSheet(f"""
            QDialog#BentoDashboard {{
                background: {C.BG};
                color: {C.TEXT};
            }}
            QFrame#BentoCard {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER_B};
                border-radius: 9px;
            }}
            QLabel#BentoEyebrow {{
                color: {C.PRI_DIM};
                background: transparent;
                font: 8pt 'Courier New';
                letter-spacing: 1px;
            }}
            QLabel#BentoValue {{
                color: {C.TEXT};
                background: transparent;
                font: bold 19pt 'Segoe UI';
            }}
            QLabel#BentoDetail {{
                color: {C.TEXT_MED};
                background: transparent;
                font: 8pt 'Segoe UI';
            }}
            QPushButton {{
                color: {C.PRI};
                background: {C.PANEL2};
                border: 1px solid {C.BORDER_B};
                border-radius: 5px;
                padding: 8px 12px;
                font: bold 8pt 'Courier New';
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO};
                border-color: {C.PRI};
            }}
        """)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        heading = QHBoxLayout()
        title = QLabel("▦  COMMAND OVERVIEW")
        title.setStyleSheet(f"color: {C.PRI}; background: transparent; font: bold 13pt 'Courier New';")
        heading.addWidget(title)
        heading.addStretch()
        subtitle = QLabel("LIVE SYSTEM SNAPSHOT")
        subtitle.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; font: 8pt 'Courier New';")
        heading.addWidget(subtitle)
        root.addLayout(heading)

        grid = QGridLayout()
        grid.setSpacing(10)
        self._bento_value_labels = {}

        cards = (
            ("ASSISTANT STATE", "assistant", "INITIALISING", "Voice and hologram state"),
            ("CPU LOAD", "cpu", "--", "Host processor utilisation"),
            ("MEMORY", "memory", "--", "Host memory utilisation"),
            ("UPTIME", "uptime", "--", "Assistant session uptime"),
            ("VOICE INPUT", "voice", "READY", "Microphone availability"),
            ("ACTIVE VIEW", "view", "HOLOGRAM", "Current command surface"),
        )
        for index, (eyebrow, key, initial, detail) in enumerate(cards):
            card = QFrame()
            card.setObjectName("BentoCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 13, 14, 13)
            card_layout.setSpacing(7)
            small = QLabel(eyebrow)
            small.setObjectName("BentoEyebrow")
            value = QLabel(initial)
            value.setObjectName("BentoValue")
            value.setWordWrap(True)
            desc = QLabel(detail)
            desc.setObjectName("BentoDetail")
            desc.setWordWrap(True)
            card_layout.addWidget(small)
            card_layout.addWidget(value)
            card_layout.addStretch()
            card_layout.addWidget(desc)
            grid.addWidget(card, index // 3, index % 3)
            self._bento_value_labels[key] = value
        for column in range(3):
            grid.setColumnStretch(column, 1)
        for row in range(2):
            grid.setRowStretch(row, 1)
        root.addLayout(grid, 1)

        actions = QHBoxLayout()
        for label, key in (
            ("TIMER", "timers"),
            ("MUSIC", "music"),
            ("NEWS", "news"),
            ("MEDIA", "media"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, view=key: self._on_workspace_shortcut(view)
            )
            actions.addWidget(button)
        actions.addStretch()
        close_button = QPushButton("CLOSE")
        close_button.clicked.connect(dialog.close)
        actions.addWidget(close_button)
        root.addLayout(actions)

        self._bento_dialog = dialog
        self._bento_timer = QTimer(dialog)
        self._bento_timer.setInterval(3000)
        self._bento_timer.timeout.connect(self._refresh_bento_dashboard)
        dialog.finished.connect(self._bento_timer.stop)
        self._refresh_bento_dashboard()
        self._bento_timer.start()
        fade = QGraphicsOpacityEffect(dialog)
        dialog.setGraphicsEffect(fade)
        fade.setOpacity(0.0)
        self._bento_fade = QPropertyAnimation(fade, b"opacity", dialog)
        self._bento_fade.setDuration(220)
        self._bento_fade.setStartValue(0.0)
        self._bento_fade.setEndValue(1.0)
        self._bento_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        dialog.show()
        self._bento_fade.start()

    def _refresh_bento_dashboard(self) -> None:
        """Refresh only while the optional Bento window is open."""
        labels = getattr(self, "_bento_value_labels", None)
        if not labels:
            return
        try:
            labels["assistant"].setText(str(getattr(self.hud, "state", "READY")).upper())
        except Exception:
            labels["assistant"].setText("READY")
        try:
            labels["cpu"].setText(f"{psutil.cpu_percent(interval=None):.0f}%")
            labels["memory"].setText(f"{psutil.virtual_memory().percent:.0f}%")
            elapsed = max(0, int(time.monotonic() - self._session_started_at))
            hours, remainder = divmod(elapsed, 3600)
            labels["uptime"].setText(f"{hours:02d}:{remainder // 60:02d}")
        except Exception:
            labels["cpu"].setText("--")
            labels["memory"].setText("--")
        labels["voice"].setText("MUTED" if self._muted else "ACTIVE")
        labels["view"].setText("SMART GLASS" if self._workspace_open else "HOLOGRAM")

    def _on_workspace_shortcut(self, key: str) -> None:
        """Handle the HTML smart-panel shortcuts through a strict local allowlist."""
        if self._cam_active:
            self.stop_camera_stream()
        if key == "timers":
            self._workspace.show_view("timers", "TIMERS / REMINDERS")
        elif key == "music":
            self._workspace.show_webpage("https://music.youtube.com/", "YOUTUBE MUSIC")
        elif key == "news":
            self._workspace.show_news(self._workspace._last_news_items, "LIVE HEADLINES")
            self._workspace.show_view("news", "LIVE HEADLINES")
        elif key == "media":
            self._workspace.show_view("video", "MEDIA PLAYER")
        elif key == "system":
            self._workspace.show_system_panel("overview")
        else:
            return
        self._earth_open = False
        self._workspace_open = True
        self._show_workspace_side(key)

    def _show_workspace_side(self, active_view: str = "command") -> None:
        """Reveal the smart glass workspace beside the unchanged hologram canvas."""
        if self._workspace.parentWidget() is not self._workspace_side:
            self._workspace_side_layout.addWidget(self._workspace, 1)
        self._workspace_header.set_context(active_view, status="ACTIVE")
        self._workspace_side.show()
        total = max(1, self._stage_split.width())
        side_width = min(390, max(230, int(total * 0.40)))
        side_width = min(side_width, max(230, total - 180))
        self._stage_split.setSizes([max(180, total - side_width), side_width])

    def _show_workspace(self, kind: str, payload) -> None:
        data = payload if isinstance(payload, dict) else {"value": payload}
        if kind == "briefing_news":
            self._workspace.show_briefing_news(
                data.get("items", data.get("text", "")),
                data.get("title", "NEWSFIRST + ADA DERANA / LIVE BRIEFING"),
            )
            self._workspace_open = True
            self._show_workspace_side("news")
            return
        if kind == "briefing_news_hide":
            self._workspace.hide_briefing_news()
            return
        self._earth_panel.stop_flight_radar()
        if self._cam_active:
            self.stop_camera_stream()
        if kind != "holo":
            self._workspace.stop_holo_camera()
            was_fullscreen = self._workspace._is_fullscreen
            self._workspace.restore_to_embedded(self._workspace_side)
            if was_fullscreen:
                self._workspace_side_layout.addWidget(self._workspace)
        self._earth_open = False
        self._workspace_open = True
        if kind == "holo":
            self._workspace.show_holo_gestures()
            self._workspace_side.hide()
        elif kind == "video_pause":
            self._workspace._pause_video()
        elif kind == "video_seek":
            self._workspace.seek_video(int(data.get("seconds", 10)))
        elif kind == "video_stop":
            self._workspace.stop_video()
        elif kind == "video_mute":
            self._workspace.set_video_muted(bool(data.get("muted", True)))
        elif kind == "video":
            self._workspace.show_video(data.get("source", ""), data.get("title", "VIDEO"))
        elif kind == "web":
            self._workspace.show_webpage(data.get("url", ""), data.get("title", "ARTICLE"))
        elif kind == "images":
            self._workspace.show_images(data.get("images", []), data.get("query", "IMAGE RESULTS"))
        elif kind == "document":
            self._workspace.show_document(data.get("path", ""), data.get("summary", ""))
        elif kind == "news":
            self._workspace.show_news(data.get("items", data.get("text", "")), data.get("title", "HEADLINES"))
        elif kind == "email":
            self._workspace.show_email(data.get("items", []), data.get("title", "INBOX"))
        elif kind == "calendar":
            self._workspace.show_calendar(data.get("items", []), data.get("title", "AGENDA"))
        elif kind == "weather":
            self._workspace.show_weather(data.get("report", {}))
        elif kind == "flights":
            self._workspace.show_flights(data.get("items", []), data.get("origin", ""), data.get("destination", ""), data.get("date", ""))
        elif kind == "reminder":
            target = data.get("target")
            if isinstance(target, str):
                try:
                    from datetime import datetime
                    target = datetime.fromisoformat(target)
                except Exception:
                    target = None
            if target is not None:
                self._workspace.add_reminder(data.get("message", "Reminder"), target)
            self._workspace.show_view("timers", "COUNTDOWN / REMINDERS")
        elif kind == "timer":
            self._workspace.start_countdown(data.get("minutes", 25), data.get("label", "COUNTDOWN"))
        elif kind == "market":
            self._workspace.show_market_query(data.get("symbol", ""))
        elif kind == "system":
            self._workspace.show_system_panel(data.get("focus") or data.get("metric"))
        else:
            self._workspace.show_view(kind)
        if kind != "holo":
            active_view = {
                "timer": "timers", "reminder": "timers", "timers": "timers",
                "news": "news", "video": "media", "video_pause": "media",
                "video_seek": "media", "video_stop": "media", "video_mute": "media",
                "system": "system",
            }.get(kind, "command")
            if kind == "web":
                active_view = "music" if "music.youtube.com" in str(data.get("url", "")).casefold() else "media"
            self._show_workspace_side(active_view)

    def _show_news_briefing_overlay(self, items) -> None:
        self._show_workspace_side("news")
        self._news_briefing_overlay.set_items(items)

    def _hide_news_briefing_overlay(self) -> None:
        self._news_briefing_overlay.dismiss()

    def _set_news_briefing_image(self, index: int, article_url: str, data: bytes, content_type: str) -> None:
        self._news_briefing_overlay.set_image(index, article_url, data, content_type)

    def _set_news_briefing_image_failed(self, index: int, article_url: str) -> None:
        self._news_briefing_overlay.set_image_failed(index, article_url)

    def _close_workspace(self) -> None:
        self._workspace.stop_holo_camera()
        was_fullscreen = self._workspace._is_fullscreen
        self._workspace.restore_to_embedded(self._workspace_side)
        if was_fullscreen:
            self._workspace_side_layout.addWidget(self._workspace)
        self._workspace_open = False
        self._workspace_side.hide()
        self._hud_cam_stack.setCurrentIndex(1 if self._cam_active else 0)

    def _open_holo_feature(self, feature: str) -> None:
        """Route a Holo gesture to an existing workspace side tab without invoking tools."""
        if feature in {"news", "newsfirst", "adaderana"}:
            title = "LIVE HEADLINES" if feature == "news" else f"{feature.upper()} HEADLINES"
            self._workspace.show_news(self._workspace._last_news_items, title)
            self._workspace.show_view("news", title)
            self._workspace_open = True
            self._show_workspace_side("news")
            return
        self._close_workspace()
        if feature == "earth":
            self._show_earth("", "", "show")
            return
        titles = {
            "video": "MEDIA PLAYER", "web": "WEB / ARTICLE", "images": "IMAGE GALLERY",
            "document": "DOCUMENTS", "news": "LIVE HEADLINES", "email": "EMAIL",
            "newsfirst": "NEWSFIRST WEBSITE", "adaderana": "ADA DERANA WEBSITE",
            "calendar": "CALENDAR", "system": "SYSTEM STATUS", "weather": "WEATHER",
            "flights": "FLIGHT FINDER", "timers": "TIMERS / REMINDERS", "market": "MARKET WATCH",
        }
        if feature in self._workspace._page_index:
            self._workspace.show_view(feature, titles.get(feature, feature.upper()))
            self._workspace_open = True
            active = {
                "timers": "timers", "news": "news", "video": "media", "system": "system",
            }.get(feature, "command")
            self._show_workspace_side(active)

    def _open_holo_news_voice(self, source: str) -> None:
        """Show requested headlines beside the hologram, not in its canvas."""
        if self._cam_active:
            self.stop_camera_stream()
        was_fullscreen = self._workspace._is_fullscreen
        self._workspace.restore_to_embedded(self._workspace_side)
        if was_fullscreen:
            self._workspace_side_layout.addWidget(self._workspace)
        title = f"{str(source or 'LIVE').upper()} HEADLINES"
        self._workspace.show_news(self._workspace._last_news_items, title)
        self._workspace.show_view("news", title)
        self._workspace_open = True
        self._show_workspace_side("news")

    def _on_cam_frame(self, data: bytes) -> None:
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()
            if w > 1 and h > 1:
                self._cam_live_lbl.setPixmap(
                    px.scaled(w, h,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )

    def start_camera_stream(self) -> None:
        self._holo_stop_sig.emit()
        self._cam_stop.clear()
        self._cam_stream_sig.emit(True)
        t = threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream")
        t.start()

    def _cam_loop(self) -> None:
        try:
            import cv2
            # Reuse camera index detected by screen_processor (cached in api_keys.json)
            cam_idx = 0
            try:
                import json as _j
                cfg = _j.loads((CONFIG_DIR / "api_keys.json").read_text())
                cam_idx = int(cfg.get("camera_index", 0))
            except Exception:
                failsoft.suppress('ui:MainWindow._cam_loop')
            try:
                backend = cv2.CAP_DSHOW if _OS == "Windows" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return
            # warm-up frames
            for _ in range(5):
                cap.read()
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    self._cam_frame_sig.emit(buf.tobytes())
            cap.release()
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()

    # ------------------------------------------------------------------
    # Icon generation — arc-reactor style, rendered with Pillow
    # ------------------------------------------------------------------
    @staticmethod
    def _build_jarvis_icon(out_path: Path) -> bool:
        """
        Render a JARVIS arc-reactor icon at 4× resolution and downsample
        for crisp results at all sizes. Saves a multi-res .ico to out_path.
        Returns True on success.
        """
        try:
            import math
            import PIL.Image
            import PIL.ImageDraw
            import PIL.ImageFilter
        except ImportError:
            return False

        CYAN   = (0, 212, 255)
        DIM    = (0, 100, 140)
        DARK   = (0, 6, 10)
        GLOW   = (0, 160, 200)
        WHITE  = (220, 240, 255)

        def _render(sz: int) -> PIL.Image.Image:
            S  = sz * 4                     # draw at 4× then downscale
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d   = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2

            # ── filled background circle ──────────────────────────────────
            R = S // 2 - 2
            d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=(*DARK, 255))

            # ── outer border ring ─────────────────────────────────────────
            lw = max(2, S // 40)
            d.ellipse([cx-R, cy-R, cx+R, cy+R],
                      outline=(*CYAN, 220), width=lw)

            # ── mid decorative ring ───────────────────────────────────────
            R2 = int(R * 0.72)
            d.ellipse([cx-R2, cy-R2, cx+R2, cy+R2],
                      outline=(*DIM, 180), width=max(1, lw // 2))

            # ── 6 radial spokes (hex bolt) ────────────────────────────────
            R_inner = int(R * 0.30)
            R_outer = int(R * 0.62)
            spoke_w = max(1, S // 80)
            for i in range(6):
                angle = math.radians(i * 60 - 30)
                x1 = cx + int(R_inner * math.cos(angle))
                y1 = cy + int(R_inner * math.sin(angle))
                x2 = cx + int(R_outer * math.cos(angle))
                y2 = cy + int(R_outer * math.sin(angle))
                d.line([x1, y1, x2, y2], fill=(*GLOW, 200), width=spoke_w)

            # ── 6 tick marks on outer ring ────────────────────────────────
            for i in range(6):
                angle = math.radians(i * 60)
                for dr in range(lw * 2):
                    rx = (R - lw - dr)
                    d.point(
                        [cx + int(rx * math.cos(angle)),
                         cy + int(rx * math.sin(angle))],
                        fill=(*WHITE, 220),
                    )

            # ── inner glowing ring ────────────────────────────────────────
            Ri = int(R * 0.26)
            d.ellipse([cx-Ri, cy-Ri, cx+Ri, cy+Ri],
                      outline=(*CYAN, 255), width=max(2, lw))

            # ── bright glow soft blur applied before core ─────────────────
            # (draw a slightly larger cyan circle on a separate layer)
            glow_layer = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow_layer)
            Rc = int(R * 0.13)
            gd.ellipse([cx-Rc*2, cy-Rc*2, cx+Rc*2, cy+Rc*2],
                       fill=(*CYAN, 110))
            glow_layer = glow_layer.filter(PIL.ImageFilter.GaussianBlur(S // 14))
            img = PIL.Image.alpha_composite(img, glow_layer)
            d   = PIL.ImageDraw.Draw(img)

            # ── core dot ──────────────────────────────────────────────────
            d.ellipse([cx-Rc, cy-Rc, cx+Rc, cy+Rc], fill=(*WHITE, 255))

            # ── downscale to target size ──────────────────────────────────
            return img.resize((sz, sz), PIL.Image.LANCZOS)

        try:
            sizes  = [256, 128, 64, 48, 32, 16]
            frames = [_render(s) for s in sizes]
            frames[0].save(
                out_path,
                format="ICO",
                append_images=frames[1:],
                sizes=[(s, s) for s in sizes],
            )
            return True
        except Exception as e:
            print(f"[Shortcut] ⚠️  Icon generation failed: {e}")
            return False

    @staticmethod
    def _create_lnk_windows(lnk: str, target: str, args: str,
                             work_dir: str, icon_loc: str) -> None:
        """
        Create a Windows .lnk shortcut WITHOUT launching PowerShell or cmd.
        Tries win32com (pywin32) first; falls back to wscript.exe + VBScript.
        wscript.exe is a GUI-mode host — it never opens a console window.
        """
        # ── Option 1: pywin32 (pure Python COM, zero subprocess) ──────────
        try:
            from win32com.client import Dispatch   # type: ignore
            sh = Dispatch("WScript.Shell")
            sc = sh.CreateShortCut(lnk)
            sc.TargetPath       = target
            sc.Arguments        = f'"{args}"'
            sc.WorkingDirectory = work_dir
            sc.Description      = "J.A.R.V.I.S AI Assistant"
            sc.IconLocation     = icon_loc
            sc.save()
            return
        except ImportError:
            pass

        # ── Option 2: wscript.exe + VBScript (always available on Windows,
        #    GUI-mode executable — never opens a console window) ────────────
        vbs = "\n".join([
            'Set ws = CreateObject("WScript.Shell")',
            f'Set sc = ws.CreateShortcut("{lnk}")',
            f'sc.TargetPath = "{target}"',
            f'sc.Arguments = Chr(34) & "{args}" & Chr(34)',
            f'sc.WorkingDirectory = "{work_dir}"',
            'sc.Description = "J.A.R.V.I.S AI Assistant"',
            f'sc.IconLocation = "{icon_loc}"',
            'sc.Save',
        ])
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(vbs)
            proc = subprocess.Popen(
                ["wscript.exe", "/nologo", tmp],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            proc.wait(timeout=10)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                failsoft.suppress('ui:MainWindow._create_lnk_windows')

    @staticmethod
    def _get_desktop_dir() -> Path:
        """
        Resolve the user's REAL desktop directory instead of assuming
        ~/Desktop, which breaks when:
          • OneDrive "Known Folder Move" relocates the desktop
            (C:/Users/x/OneDrive/Desktop) — very common on Win 10/11;
          • the XDG desktop is localized on Linux (~/Masaüstü,
            ~/Schreibtisch, ~/Bureau, …).
        Falls back to ~/Desktop only as a last resort.
        """
        home = Path.home()
        _os = platform.system()

        if _os == "Windows":
            # ── 1) SHGetKnownFolderPath(FOLDERID_Desktop) — the canonical
            #       answer; follows OneDrive redirection. No dependencies. ──
            try:
                import ctypes
                from ctypes import wintypes

                class _GUID(ctypes.Structure):
                    _fields_ = [("Data1", wintypes.DWORD),
                                ("Data2", wintypes.WORD),
                                ("Data3", wintypes.WORD),
                                ("Data4", ctypes.c_ubyte * 8)]

                # FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
                fid = _GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                            (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9,
                                                 0x9A, 0x87, 0xC6, 0x41))
                buf = ctypes.c_wchar_p()
                if ctypes.windll.shell32.SHGetKnownFolderPath(
                        ctypes.byref(fid), 0, None, ctypes.byref(buf)) == 0:
                    p = Path(buf.value)
                    ctypes.windll.ole32.CoTaskMemFree(buf)
                    if p.is_dir():
                        return p
            except Exception:
                failsoft.suppress('ui:MainWindow._get_desktop_dir')

            # ── 2) Registry: User Shell Folders (may contain %VARS%) ──────
            try:
                import winreg
                with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion"
                        r"\Explorer\User Shell Folders") as key:
                    val, _t = winreg.QueryValueEx(key, "Desktop")
                p = Path(os.path.expandvars(val))
                if p.is_dir():
                    return p
            except Exception:
                failsoft.suppress('ui:MainWindow._get_desktop_dir')

        elif _os == "Linux":
            # ── xdg-user-dir honours localized names (~/Masaüstü, …) ──────
            try:
                out = subprocess.run(["xdg-user-dir", "DESKTOP"],
                                     capture_output=True, text=True, timeout=5)
                p = Path(out.stdout.strip())
                if out.stdout.strip() and p != home and p.is_dir():
                    return p
            except Exception:
                failsoft.suppress('ui:MainWindow._get_desktop_dir')
            try:
                cfg = home / ".config" / "user-dirs.dirs"
                for line in cfg.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("XDG_DESKTOP_DIR"):
                        val = line.split("=", 1)[1].strip().strip('"')
                        p = Path(val.replace("$HOME", str(home)))
                        if p != home and p.is_dir():
                            return p
            except Exception:
                failsoft.suppress('ui:MainWindow._get_desktop_dir')

        # macOS: ~/Desktop is always the real path (localization is
        # display-only). Everything else lands here as a last resort.
        return home / "Desktop"

    def _create_desktop_shortcut(self):
        """
        Create a desktop shortcut on Windows / macOS / Linux.
        Never opens a terminal, console, or PowerShell window on any platform.
        """
        import shlex
        import stat as _stat
        argv, work_dir = self._autostart_target()
        launch_args = str(Path(argv[1])) if len(argv) > 1 else ""
        target = Path(argv[0])
        desktop = self._get_desktop_dir()

        # User-provided JARVIS mark (.ico — the matching .png is used by Linux).
        # Keep a generated fallback for older/frozen copies without the asset.
        ico_path = BASE_DIR / "assets" / "branding" / "jarvis_desktop.ico"
        if not ico_path.is_file():
            ico_path = Path(work_dir) / "config" / "jarvis.ico"
            if not ico_path.exists():
                self._build_jarvis_icon(ico_path)

        try:
            _os = platform.system()

            # ── Windows ───────────────────────────────────────────────────────
            if _os == "Windows":
                if not getattr(sys, "frozen", False):
                    pythonw = target.with_name("pythonw.exe")
                    if pythonw.is_file():
                        target = pythonw
                lnk      = str(desktop / "J.A.R.V.I.S.lnk")
                icon_loc = str(ico_path) if ico_path.exists() else f"{target},0"
                self._create_lnk_windows(lnk, str(target), launch_args,
                                         work_dir, icon_loc)

            # ── macOS — proper .app bundle (no Terminal window) ───────────────
            elif _os == "Darwin":
                app     = desktop / "J.A.R.V.I.S.app"
                mac_dir = app / "Contents" / "MacOS"
                res_dir = app / "Contents" / "Resources"
                mac_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(exist_ok=True)

                # Launcher executable (bash — runs as background process,
                # macOS does NOT open Terminal for executables inside .app bundles)
                launcher = mac_dir / "JARVIS"
                command = " ".join(shlex.quote(arg) for arg in argv)
                launcher.write_text(
                    "#!/bin/sh\n"
                    f"cd {shlex.quote(work_dir)} || exit 1\n"
                    f"exec {command}\n",
                    encoding="utf-8",
                )
                launcher.chmod(launcher.stat().st_mode
                               | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

                # Minimal Info.plist (required for .app recognition)
                (app / "Contents" / "Info.plist").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n'
                    '  <key>CFBundleExecutable</key><string>JARVIS</string>\n'
                    '  <key>CFBundleIdentifier</key>'
                    '<string>com.jarvis.assistant</string>\n'
                    '  <key>CFBundleName</key><string>J.A.R.V.I.S</string>\n'
                    '  <key>CFBundlePackageType</key><string>APPL</string>\n'
                    '  <key>CFBundleVersion</key><string>1.0</string>\n'
                    '</dict></plist>\n'
                )

                # Optional: copy icon as .icns (skip silently if Pillow is missing)
                try:
                    import PIL.Image
                    icns = res_dir / "AppIcon.icns"
                    PIL.Image.open(ico_path).save(icns, format="ICNS")
                    # Inject icon reference into plist
                    plist = app / "Contents" / "Info.plist"
                    txt = plist.read_text()
                    plist.write_text(
                        txt.replace(
                            '</dict></plist>',
                            '  <key>CFBundleIconFile</key>'
                            '<string>AppIcon</string>\n</dict></plist>\n',
                        )
                    )
                except Exception:
                    failsoft.suppress('ui:MainWindow._create_desktop_shortcut')

            # ── Linux — .desktop file (Terminal=false, no console) ────────────
            else:
                # Export .ico → .png for better desktop integration
                png_path = ico_path.with_suffix(".png")
                if not png_path.exists() and ico_path.exists():
                    try:
                        import PIL.Image
                        PIL.Image.open(ico_path).resize(
                            (256, 256), PIL.Image.LANCZOS
                        ).save(png_path, format="PNG")
                    except Exception:
                        png_path = ico_path  # fallback to .ico

                icon_line = (f"Icon={self._desktop_entry_path(str(png_path))}\n"
                             if png_path.exists() else "")
                desk = desktop / "J.A.R.V.I.S.desktop"
                exec_line = " ".join(self._desktop_exec_arg(arg) for arg in argv)
                desk.write_text(
                    "[Desktop Entry]\n"
                    "Name=J.A.R.V.I.S\n"
                    f"Exec={exec_line}\n"
                    f"Path={self._desktop_entry_path(work_dir)}\n"
                    "Type=Application\n"
                    "Terminal=false\n"
                    "Categories=Utility;\n"
                    + icon_line,
                    encoding="utf-8",
                )
                desk.chmod(desk.stat().st_mode | 0o755)

            self._log.append_log("SYS: Desktop shortcut created.")
        except Exception as e:
            self._log.append_log(f"ERR: Shortcut failed — {e}")

    def _present_default_view(self):
        """Start in the saved immersive neural view after setup is complete."""
        if self._ready and self.hud.hud_style in ("neural", "neural_orb"):
            self._enter_immersive_view()

    def _enter_immersive_view(self, style: str | None = None):
        if not getattr(self, "_ready", False):
            return
        from memory.config_manager import save_hud_style
        active_style = style or (
            self.hud.hud_style
            if self.hud.hud_style in ("neural", "neural_orb") else "neural"
        )
        if active_style not in ("neural", "neural_orb"):
            active_style = "neural"
        self.hud.hud_style = active_style
        self._immersive_overlay.hud.hud_style = active_style
        save_hud_style(active_style)
        if hasattr(self, "_hud_btn"):
            index = self._hud_btn.findData(active_style)
            if index >= 0:
                self._hud_btn.blockSignals(True)
                self._hud_btn.setCurrentIndex(index)
                self._hud_btn.blockSignals(False)
        if not self._immersive_open:
            self._immersive_previous_fullscreen = self.isFullScreen()
        # Only the visible canvas should run its animation loop. A 20 ms tick
        # keeps the throttled paint near 25 fps while lowering CPU use.
        self.hud._tmr.stop()
        self._immersive_overlay.hud._tmr.setInterval(20)
        self._immersive_overlay.hud._tmr.start()
        self.showFullScreen()
        # Do not burn a second animation loop behind the full-window canvas.
        if self._hud_cam_stack.currentWidget() is self.hud:
            self.hud.hide()
        cw = self.centralWidget()
        self._immersive_overlay.setGeometry(cw.rect())
        self._immersive_overlay.show()
        self._immersive_overlay.raise_()
        self._voice_control_overlay = self._immersive_overlay
        self._immersive_open = True
        self._immersive_overlay.hud.update()

    def _toggle_neural_hand_control(self):
        if self._neural_hand_active:
            self._stop_neural_hand_control()
            return
        if not self._ready:
            self._log.append_log("SYS: Complete JARVIS setup before enabling neural hand control.")
            return
        view = self._immersive_overlay._neural_hand_view
        server = self._workspace._holo_server
        if view is None or server is None or self._neural_hand_page is None:
            self._log.append_log(
                "ERR: Hand control needs PyQt6-WebEngine and the bundled Holo tracking assets."
            )
            return

        # Use the same HUD confirmation banner and exact voice phrases as
        # sensitive actions. The callback runs on core.confirm's worker thread;
        # the signal below safely returns camera/UI work to Qt's main thread.
        from core.confirm import request

        result = request(
            "neural-camera",
            "Enable hand control camera",
            "JARVIS will auto-detect and start the built-in laptop camera for local hand tracking. "
            "A small circular preview stays at the top right. Video is processed locally, "
            "not recorded or uploaded. Say CONFIRM ACTION or CANCEL ACTION, or use the HUD buttons.",
            self._request_neural_hand_start,
        )
        if not result.startswith("[CONFIRMATION_PENDING]"):
            self._log.append_log(f"SYS: {result}")

    def _request_neural_hand_start(self) -> str:
        self._neural_hand_start_sig.emit()
        return "The local camera startup request was granted."

    def _start_neural_hand_control_after_confirmation(self):
        if self._neural_hand_active:
            return
        view = self._immersive_overlay._neural_hand_view
        server = self._workspace._holo_server
        if view is None or server is None or self._neural_hand_page is None:
            self._log.append_log("ERR: Neural hand-control camera is unavailable.")
            return
        self._neural_hand_active = True
        self._immersive_overlay.hud._hand_3d_active = True
        self._immersive_overlay.hud._sync_neural_quick(force=True)
        self._immersive_overlay.hud.update()
        if not self._immersive_open:
            style = self.hud.hud_style if self.hud.hud_style in ("neural", "neural_orb") else "neural"
            self._enter_immersive_view(style)
        self._immersive_overlay.set_hand_control_active(True)
        self._neural_hand_btn.setText("✋ STOP")
        self._neural_hand_btn.setStyleSheet(
            "QPushButton { color:#FF6682; background:transparent; border:1px solid #FF6682; "
            "border-radius:3px; padding:0 7px; }"
        )
        url = QUrl(server.url + "neural_control.html")
        view = self._immersive_overlay._neural_hand_view
        view.load(url)
        view.show()
        view.raise_()

    def _grant_neural_hand_camera(self, origin, feature) -> None:
        page = self._neural_hand_page
        server = self._workspace._holo_server
        if page is None or not _load_webengine():
            return
        try:
            host = QUrl(origin).host().lower()
            port = QUrl(origin).port()
            expected_port = QUrl(server.url).port() if server else -1
            is_video = feature == QWebEnginePage.Feature.MediaVideoCapture
            allowed = self._neural_hand_active and host == "127.0.0.1" \
                and port == expected_port and is_video
            policy = QWebEnginePage.PermissionPolicy
            page.setFeaturePermission(
                origin, feature,
                policy.PermissionGrantedByUser if allowed else policy.PermissionDeniedByUser,
            )
        except Exception:
            return

    def _on_neural_hand_update(self, pose: object) -> None:
        if not self._neural_hand_active:
            return
        try:
            self._immersive_overlay.hud.apply_neural_hand_pose(pose)
        except RuntimeError:
            pass

    def _reset_neural_hand_pose(self) -> None:
        for canvas in (self.hud, self._immersive_overlay.hud):
            canvas._hand_rotation = 0.0
            canvas._hand_yaw = 0.0
            canvas._hand_tilt = 0.0
            canvas._hand_zoom = 1.0
            canvas._hand_zoom_target = 1.0
            canvas._hand_prev_point = None
            canvas._hand_pinching = False
            canvas._hand_prev_angle = None
            canvas.update()

    def _stop_neural_hand_control(self) -> None:
        self._neural_hand_active = False
        self._immersive_overlay.hud._hand_3d_active = False
        self._immersive_overlay.hud.update()
        view = self._immersive_overlay._neural_hand_view
        if view is not None:
            try:
                view.page().runJavaScript(
                    "if (window.jarvisStopNeuralHands) window.jarvisStopNeuralHands();"
                )
                view.hide()
            except RuntimeError:
                pass
        if hasattr(self, "_immersive_overlay"):
            self._immersive_overlay.set_hand_control_active(False)
        if hasattr(self, "_neural_hand_btn"):
            self._neural_hand_btn.setText("✋ HAND")
            self._neural_hand_btn.setStyleSheet(f"""
                QPushButton {{ color:#55E9FF; background:transparent;
                    border:1px solid {C.BORDER_A}; border-radius:3px; padding:0 7px; }}
                QPushButton:hover {{ color:{C.WHITE}; border-color:#55E9FF;
                    background:{C.PRI_GHO}; }}
            """)

    def _leave_immersive_view(self):
        if not getattr(self, "_immersive_open", False):
            return
        if self._neural_hand_active:
            self._stop_neural_hand_control()
        self._immersive_overlay.hide()
        if getattr(self, "_voice_control_overlay", None) is self._immersive_overlay:
            self._voice_control_overlay = None
        self._immersive_overlay.hud._tmr.stop()
        self.hud._tmr.setInterval(16)
        self.hud._tmr.start()
        self._immersive_open = False
        if self._hud_cam_stack.currentWidget() is self.hud:
            self.hud.show()
        if getattr(self, "_immersive_previous_fullscreen", False):
            self.showFullScreen()
        else:
            self.showNormal()
            self.resize(_DEFAULT_W, _DEFAULT_H)
            screen = QApplication.primaryScreen().availableGeometry()
            self.move((screen.width() - _DEFAULT_W) // 2,
                      (screen.height() - _DEFAULT_H) // 2)

    def _submit_immersive_command(self, text: str):
        self._log.append_log(f"You: {text}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()

    def _toggle_fullscreen(self):
        if self._immersive_open:
            self._leave_immersive_view()
        elif self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if getattr(self, "_immersive_open", False):
            self._immersive_overlay.setGeometry(cw.rect())
        if hasattr(self, "_news_briefing_overlay"):
            self._news_briefing_overlay.reposition()
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._customize_overlay and self._customize_overlay.isVisible():
            ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
            self._customize_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._provider_overlay and self._provider_overlay.isVisible():
            ow, oh = AIProviderOverlay._OW, min(AIProviderOverlay._OH, cw.height() - 16)
            self._provider_overlay.setGeometry(
                max(0, (cw.width() - ow) // 2),
                max(0, (cw.height() - oh) // 2), ow, oh,
            )
        # Camera preview — bottom-right corner of the center/HUD area
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )
        # Clipboard panel — bottom-center
        if hasattr(self, '_clipboard_panel') and self._clipboard_panel.isVisible():
            self._position_clipboard_panel()
        # Quick drawer — reposition if open
        if hasattr(self, '_quick_drawer') and self._quick_drawer.isVisible():
            self._position_quick_drawer()

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(62)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        self._nav_menu_btn = _HoverMenuButton()
        self._nav_menu_btn.setText("☰")
        self._nav_menu_btn.setFixedSize(28, 28)
        self._nav_menu_btn.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        self._nav_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._nav_menu_btn.setToolTip("Hover for quick command windows")
        self._nav_menu_btn.setStyleSheet(f"""
            QToolButton {{
                color: {C.PRI}; background: {C.PANEL};
                border: 1px solid {C.BORDER_B}; border-radius: 4px;
            }}
            QToolButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """)
        self._nav_menu = QMenu(self._nav_menu_btn)
        self._nav_menu.setStyleSheet(f"""
            QMenu {{
                background: {C.DARK}; color: {C.TEXT};
                border: 1px solid {C.BORDER_B}; padding: 6px;
            }}
            QMenu::item {{ padding: 8px 28px 8px 12px; border-radius: 3px; }}
            QMenu::item:selected {{ color: {C.PRI}; background: {C.PRI_GHO}; }}
            QMenu::separator {{ height: 1px; background: {C.BORDER}; margin: 4px 6px; }}
        """)
        for key, label in (
            ("timers", "◷   TIMER & REMINDERS"),
            ("music", "♫   YOUTUBE MUSIC"),
            ("news", "◉   LIVE NEWS"),
            ("media", "▣   MEDIA PLAYER"),
            ("system", "⌘   SYSTEM STATUS"),
        ):
            action = self._nav_menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, view=key: self._on_workspace_shortcut(view)
            )
        self._nav_menu.addSeparator()
        dashboard_action = self._nav_menu.addAction("▦   BENTO DASHBOARD")
        dashboard_action.triggered.connect(self._open_bento_dashboard)
        self._nav_menu_btn.setMenu(self._nav_menu)
        lay.addWidget(self._nav_menu_btn)
        lay.addWidget(_badge(APP_VERSION, C.PRI_DIM))
        lay.addSpacing(8)
        self._drawer_btn = QPushButton("⚙")
        self._drawer_btn.setFixedSize(26, 26)
        self._drawer_btn.setFont(QFont("Courier New", 11))
        self._drawer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_btn.setToolTip("Settings & Controls")
        self._drawer_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 4px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI_DIM}; }}
            QPushButton:checked {{ color: {C.PRI}; border-color: {C.PRI}; background: {C.PRI_GHO}; }}
        """)
        self._drawer_btn.setCheckable(True)
        self._drawer_btn.clicked.connect(self._toggle_drawer)
        lay.addWidget(self._drawer_btn)

        self._telemetry_btn = QPushButton("▤")
        self._telemetry_btn.setFixedSize(26, 26)
        self._telemetry_btn.setFont(QFont("Courier New", 11))
        self._telemetry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._telemetry_btn.setCheckable(True)
        self._telemetry_btn.setChecked(False)
        self._telemetry_btn.setToolTip("Show / hide system telemetry")
        self._telemetry_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 4px;
            }}
            QPushButton:hover, QPushButton:checked {{
                color: {C.PRI}; border-color: {C.PRI_DIM};
                background: {C.PRI_GHO};
            }}
        """)
        self._telemetry_btn.clicked.connect(self._toggle_telemetry_panel)
        lay.addWidget(self._telemetry_btn)

        self._activity_btn = QPushButton("☷")
        self._activity_btn.setFixedSize(26, 26)
        self._activity_btn.setFont(QFont("Courier New", 11))
        self._activity_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._activity_btn.setCheckable(True)
        self._activity_btn.setToolTip("Show / hide activity log and file bay")
        self._activity_btn.setStyleSheet(self._telemetry_btn.styleSheet())
        self._activity_btn.clicked.connect(self._toggle_activity_panel)
        lay.addWidget(self._activity_btn)

        self._neural_view_btn = QPushButton("◉ FIELD")
        self._neural_view_btn.setFixedHeight(26)
        self._neural_view_btn.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        self._neural_view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._neural_view_btn.setToolTip("Open full-screen Visualization 1: the synapse field")
        self._neural_view_btn.setStyleSheet(f"""
            QPushButton {{ color: {C.PRI}; background: transparent;
                border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 0 7px; }}
            QPushButton:hover {{ color: {C.WHITE}; border-color: {C.PRI};
                background: {C.PRI_GHO}; }}
        """)
        self._neural_view_btn.clicked.connect(
            lambda _checked=False: self._enter_immersive_view("neural")
        )
        self._neural_hand_btn = QPushButton("✋ HAND")
        self._neural_hand_btn.setFixedHeight(26)
        self._neural_hand_btn.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        self._neural_hand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._neural_hand_btn.setToolTip(
            "Enable local hand control for rotating and resizing the neural field"
        )
        self._neural_hand_btn.setStyleSheet(f"""
            QPushButton {{ color:#55E9FF; background:transparent;
                border:1px solid {C.BORDER_A}; border-radius:3px; padding:0 7px; }}
            QPushButton:hover {{ color:{C.WHITE}; border-color:#55E9FF;
                background:{C.PRI_GHO}; }}
        """)
        self._neural_hand_btn.clicked.connect(self._toggle_neural_hand_control)
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        _disp = self._assistant_name.upper()
        self._title_lbl = QLabel(_disp)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(self._title_lbl)
        _sub_text = ("AUTONOMOUS SYSTEMS INTERFACE  //  UNIT 07"
                     if _disp in ("JARVIS", "J.A.R.V.I.S")
                     else "PERSONAL SYSTEMS INTERFACE")
        self._sub_lbl = QLabel(_sub_text)
        self._sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_lbl.setFont(QFont("Courier New", 7))
        self._sub_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(self._sub_lbl)
        lay.addLayout(mid)
        lay.addStretch()

        self._right_menu_btn = QToolButton()
        self._right_menu_btn.setText("⋮")
        self._right_menu_btn.setFixedSize(25, 28)
        self._right_menu_btn.setFont(QFont("Courier New", 15, QFont.Weight.Bold))
        self._right_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._right_menu_btn.setToolTip("Quick controls and assistant mode")
        self._right_menu_btn.setStyleSheet(f"""
            QToolButton {{
                color: {C.TEXT_DIM}; background: transparent;
                border: 1px solid {C.BORDER}; border-radius: 4px;
            }}
            QToolButton:hover {{ color: {C.PRI}; border-color: {C.PRI_DIM}; }}
        """)
        self._right_menu = QMenu(self._right_menu_btn)
        self._right_menu.setStyleSheet(self._nav_menu.styleSheet())
        dash_action = self._right_menu.addAction("▦  Bento Dashboard")
        dash_action.triggered.connect(self._open_bento_dashboard)
        self._right_menu.addSeparator()
        telemetry_action = self._right_menu.addAction("▤  Toggle Telemetry")
        telemetry_action.triggered.connect(
            lambda _checked=False: self._toggle_telemetry_panel(
                not self._left_panel.isVisible()
            )
        )
        activity_action = self._right_menu.addAction("☷  Toggle Activity")
        activity_action.triggered.connect(
            lambda _checked=False: self._toggle_activity_panel(
                not self._right_panel.isVisible()
            )
        )
        settings_action = self._right_menu.addAction("⚙  Settings & Controls")
        settings_action.triggered.connect(
            lambda _checked=False: self._drawer_btn.click()
        )
        self._right_menu.addSeparator()
        jarvis_action = self._right_menu.addAction("JARVIS Mode")
        jarvis_action.triggered.connect(lambda: self._mode_btn.setCurrentIndex(0))
        bihansa_action = self._right_menu.addAction("BIHANSA Mode")
        bihansa_action.triggered.connect(lambda: self._mode_btn.setCurrentIndex(1))
        self._right_menu_btn.setMenu(self._right_menu)
        self._right_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        lay.addWidget(self._right_menu_btn)

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _toggle_telemetry_panel(self, checked: bool) -> None:
        """Show or hide the optional telemetry rail without affecting the HUD."""
        panel = getattr(self, "_left_panel", None)
        if panel is None:
            return
        panel.setVisible(bool(checked))
        timer = getattr(self, "_metric_tmr", None)
        if timer is not None:
            if checked:
                timer.start(2000)
                self._update_metrics()
            else:
                timer.stop()
        if hasattr(self, "_telemetry_btn"):
            self._telemetry_btn.setChecked(bool(checked))

    def _toggle_activity_panel(self, checked: bool) -> None:
        """Show or hide the optional transcript and incoming-file panel."""
        panel = getattr(self, "_right_panel", None)
        if panel is None:
            return
        panel.setVisible(bool(checked))
        if hasattr(self, "_activity_btn"):
            self._activity_btn.setChecked(bool(checked))

    def _handle_escape(self) -> None:
        """Close transient drawers first; use Escape as interrupt otherwise."""
        for widget_name, button_name in (
            ("_quick_drawer", "_drawer_btn"),
            ("_right_panel", "_activity_btn"),
            ("_left_panel", "_telemetry_btn"),
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None and widget.isVisible():
                if widget_name == "_left_panel":
                    # Route through the toggle so hidden telemetry also stops polling.
                    self._toggle_telemetry_panel(False)
                else:
                    widget.hide()
                    button = getattr(self, button_name, None)
                    if button is not None:
                        button.setChecked(False)
                return
        self._do_interrupt()

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(6)

        hdr = QLabel("◈  SYSTEM TELEMETRY  /  LIVE")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)
        lay.addSpacing(2)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(4)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Courier New", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addSpacing(4)

        lay.addStretch()

        for txt, col in [
            ("JARVIS CORE\nINITIALISING",  C.GREEN),
            ("RISK GATE\nARMED",     C.PRI),
            ("NODE SERIAL\n07  /  " + APP_PROTOCOL,   C.TEXT_DIM),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 4px;"
            )
            if txt.startswith("JARVIS CORE"):
                self._core_status_lbl = lbl
            lay.addWidget(lbl)

        return w
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"▸ {txt}")
            l.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            return l

        lay.addWidget(_sec("MISSION TRANSCRIPT  /  LIVE"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("INCOMING DATA  /  FILE BAY"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Courier New", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        self._interrupt_btn = QPushButton("✋  INTERRUPT  [ESC]")
        self._interrupt_btn.setFixedHeight(34)
        self._interrupt_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interrupt_btn.setStyleSheet(f"""
            QPushButton {{
                background: #140008; color: {C.MUTED_C};
                border: 1px solid {C.MUTED_C}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: #200010; border: 1px solid #ff6688;
            }}
            QPushButton:pressed {{
                background: #300018;
            }}
        """)
        self._interrupt_btn.clicked.connect(self._do_interrupt)

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()

        # Keep command entry and safety controls in the persistent bottom bar;
        # this panel is now reserved for optional transcript and file history.
        self._command_input_row = self._build_input_row()
        return w

    def _build_quick_drawer(self) -> QWidget:
        """Floating overlay panel shown when the ⚙ header button is toggled."""
        _BTN_STYLE_PRI = f"""
            QPushButton {{
                background: #00091a; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """
        _BTN_STYLE_DIM = f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}
        """

        w = QWidget(self.centralWidget())
        w.setObjectName("QuickDrawer")
        w.setStyleSheet(f"""
            QWidget#QuickDrawer {{
                background: {C.DARK};
                border: 1px solid {C.BORDER_B};
                border-top: none;
                border-radius: 0 0 6px 6px;
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(5)

        hdr = QLabel("◈ CONTROLS")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)

        # Advanced visualisation tools live in the controls drawer rather than
        # competing with the assistant identity in the clean command-centre header.
        self._neural_view_btn.setFixedHeight(26)
        self._neural_hand_btn.setFixedHeight(26)
        lay.addWidget(self._neural_view_btn)
        lay.addWidget(self._neural_hand_btn)

        remote_btn = QPushButton("◉  REMOTE CONTROL")
        remote_btn.setFixedHeight(30)
        remote_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remote_btn.setStyleSheet(_BTN_STYLE_PRI)
        remote_btn.clicked.connect(self._open_remote)
        lay.addWidget(remote_btn)

        fs_btn = QPushButton("⛶  FULLSCREEN  [F11]")
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont("Courier New", 7))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(_BTN_STYLE_DIM)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        sc_btn = QPushButton("⊞  CREATE DESKTOP SHORTCUT")
        sc_btn.setFixedHeight(26)
        sc_btn.setFont(QFont("Courier New", 7))
        sc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sc_btn.setStyleSheet(_BTN_STYLE_DIM)
        sc_btn.clicked.connect(self._create_desktop_shortcut)
        lay.addWidget(sc_btn)

        self._autostart_btn = QPushButton("◉  AUTO-START: OFF")
        self._autostart_btn.setFixedHeight(26)
        self._autostart_btn.setFont(QFont("Courier New", 7))
        self._autostart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._autostart_btn.clicked.connect(self._toggle_autostart)
        lay.addWidget(self._autostart_btn)

        self._startup_video_btn = QPushButton()
        self._startup_video_btn.setFixedHeight(26)
        self._startup_video_btn.setFont(QFont("Courier New", 7))
        self._startup_video_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._startup_video_btn.setToolTip(
            "Choose whether the optional intro video plays before the HUD on launch."
        )
        self._startup_video_btn.clicked.connect(self._toggle_startup_video)
        lay.addWidget(self._startup_video_btn)
        self._refresh_startup_video_btn()

        cust_btn = QPushButton("⚙  CUSTOMISE ASSISTANT")
        cust_btn.setFixedHeight(26)
        cust_btn.setFont(QFont("Courier New", 7))
        cust_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cust_btn.setStyleSheet(_BTN_STYLE_DIM)
        cust_btn.clicked.connect(self._open_customize)
        lay.addWidget(cust_btn)

        personality_btn = QPushButton("◈  RESPONSE PERSONALITY")
        personality_btn.setFixedHeight(26)
        personality_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        personality_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        personality_btn.setStyleSheet(_BTN_STYLE_DIM)
        personality_btn.clicked.connect(self._open_voice_personality)
        provider_btn = QPushButton("◈  AI PROVIDER / KEYS")
        provider_btn.setFixedHeight(26)
        provider_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        provider_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        provider_btn.setStyleSheet(_BTN_STYLE_DIM)
        provider_btn.clicked.connect(self._open_provider_settings)
        lay.addWidget(provider_btn)
        lay.addWidget(personality_btn)

        self._brief_btn = QPushButton()
        self._brief_btn.setFixedHeight(26)
        self._brief_btn.setFont(QFont("Courier New", 7))
        self._brief_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._brief_btn.clicked.connect(self._toggle_brief)
        lay.addWidget(self._brief_btn)

        # ── Wake word ──────────────────────────────────────────────────────────
        self._wake_btn = QPushButton()
        self._wake_btn.setFixedHeight(26)
        self._wake_btn.setFont(QFont("Courier New", 7))
        self._wake_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wake_btn.clicked.connect(self._toggle_wake_word)
        lay.addWidget(self._wake_btn)

        self._wake_sleep_btn = QPushButton()
        self._wake_sleep_btn.setFixedHeight(26)
        self._wake_sleep_btn.setFont(QFont("Courier New", 7))
        self._wake_sleep_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wake_sleep_btn.clicked.connect(self._tap_wake_manual)
        lay.addWidget(self._wake_sleep_btn)
        self._voice_id_btn = QPushButton("🔐  VOICE ID: SET UP / TOGGLE")
        self._voice_id_btn.setFixedHeight(26)
        self._voice_id_btn.setFont(QFont("Courier New", 7))
        self._voice_id_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._voice_id_btn.setStyleSheet(_BTN_STYLE_DIM)
        self._voice_id_btn.setToolTip(
            "Click to set up or toggle speaker checks. Right-click to re-enroll or remove the profile."
        )
        self._voice_id_btn.clicked.connect(self._toggle_voice_id)
        self._voice_id_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._voice_id_btn.customContextMenuRequested.connect(self._voice_id_menu)
        lay.addWidget(self._voice_id_btn)
        # Neutral placeholder now; the real state (which may load the model to
        # check readiness) is resolved lazily the first time the drawer opens.
        self._wake_btn.setText("🎙  WAKE WORD")
        self._wake_btn.setStyleSheet(_BTN_STYLE_DIM)
        self._wake_sleep_btn.hide()

        self._ptt_btn = QPushButton()
        self._ptt_btn.setFixedHeight(26)
        self._ptt_btn.setFont(QFont("Courier New", 7))
        self._ptt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ptt_btn.clicked.connect(self._toggle_ptt)
        lay.addWidget(self._ptt_btn)

        self._refresh_talk_btns()

        self._mode_btn = QComboBox()
        self._mode_btn.setFixedHeight(26)
        self._mode_btn.setFont(QFont("Courier New", 7))
        self._mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_btn.addItem("MODE: JARVIS", "jarvis")
        self._mode_btn.addItem("MODE: BIHANSA", "bihansa")
        self._mode_btn.currentIndexChanged.connect(self._on_assistant_mode_selected)
        lay.addWidget(self._mode_btn)
        self._refresh_assistant_mode_btn()

        bihansa_btn = QPushButton("⚙  BIHANSA SETTINGS")
        bihansa_btn.setFixedHeight(26)
        bihansa_btn.setFont(QFont("Courier New", 7))
        bihansa_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bihansa_btn.setStyleSheet(_BTN_STYLE_DIM)
        bihansa_btn.clicked.connect(self._open_bihansa_settings_dialog)
        lay.addWidget(bihansa_btn)

        self._hud_btn = QComboBox()
        self._hud_btn.setFixedHeight(26)
        self._hud_btn.setFont(QFont("Courier New", 7))
        self._hud_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hud_btn.addItem("HUD: VISUALIZATION 1", "neural")
        self._hud_btn.addItem("HUD: VISUALIZATION 2", "neural_orb")
        self._hud_btn.addItem("HUD: AI HOLOGRAM", "face")
        self._hud_btn.addItem("HUD: JARVIS LOGO", "core")
        self._hud_btn.currentIndexChanged.connect(self._on_hud_style_selected)
        lay.addWidget(self._hud_btn)
        self._refresh_hud_btn()

        self._neural_scale_btn = QComboBox()
        self._neural_scale_btn.setFixedHeight(26)
        self._neural_scale_btn.setFont(QFont("Courier New", 7))
        self._neural_scale_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._neural_scale_btn.addItem("CPU FALLBACK: 1.0×", 1.0)
        self._neural_scale_btn.addItem("CPU FALLBACK: 0.75×", 0.75)
        self._neural_scale_btn.addItem("CPU FALLBACK: 0.6×", 0.6)
        self._neural_scale_btn.currentIndexChanged.connect(
            self._on_neural_render_scale_selected
        )
        lay.addWidget(self._neural_scale_btn)
        self._refresh_neural_render_scale_btn()

        audio_btn = QPushButton("🎧  AUDIO DEVICES")
        audio_btn.setFixedHeight(26)
        audio_btn.setFont(QFont("Courier New", 7))
        audio_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        audio_btn.setStyleSheet(_BTN_STYLE_DIM)
        audio_btn.clicked.connect(self._open_audio_devices)
        lay.addWidget(audio_btn)

        mem_btn = QPushButton("🧠  MEMORY")
        mem_btn.setFixedHeight(26)
        mem_btn.setFont(QFont("Courier New", 7))
        mem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mem_btn.setStyleSheet(_BTN_STYLE_DIM)
        mem_btn.clicked.connect(self._open_memory_panel)
        lay.addWidget(mem_btn)

        plugin_btn = QPushButton("🧩  PLUGINS")
        plugin_btn.setFixedHeight(26)
        plugin_btn.setFont(QFont("Courier New", 7))
        plugin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        plugin_btn.setStyleSheet(_BTN_STYLE_DIM)
        plugin_btn.clicked.connect(self._open_plugin_manager)
        lay.addWidget(plugin_btn)

        settings_btn = QPushButton("⚙  PLUGIN SETTINGS")
        settings_btn.setFixedHeight(26)
        settings_btn.setFont(QFont("Courier New", 7))
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setStyleSheet(_BTN_STYLE_DIM)
        settings_btn.clicked.connect(self._open_plugin_settings)
        lay.addWidget(settings_btn)

        w.adjustSize()
        return w

    def _toggle_drawer(self, checked: bool):
        if checked:
            self._refresh_wake_btns()   # resolve wake state on open (lazy)
            self._position_quick_drawer()
            self._quick_drawer.show()
            self._quick_drawer.raise_()
        else:
            self._quick_drawer.hide()

    def _position_quick_drawer(self):
        if not hasattr(self, '_quick_drawer'):
            return
        _W = 220
        self._quick_drawer.setFixedWidth(_W)
        self._quick_drawer.adjustSize()
        self._quick_drawer.setGeometry(12, 54, _W, self._quick_drawer.sizeHint().height())

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d14; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_content_panel(self) -> QWidget:
        """
        Collapsible panel below the HUD — shows search results, news, briefings.
        Hidden by default; appears when show_content() is called.
        """
        w = QWidget()
        w.setObjectName("ContentPanel")
        w.setStyleSheet(f"""
            QWidget#ContentPanel {{
                background: {C.PANEL};
                border-top: 1px solid {C.BORDER_B};
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 7, 12, 8)
        lay.setSpacing(5)

        # ── header row ───────────────────────────────────────────────────────
        hdr = QHBoxLayout(); hdr.setSpacing(6)

        dot = QLabel("◈")
        dot.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)

        self._content_title_lbl = QLabel("BRIEFING")
        self._content_title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._content_title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;"
        )
        hdr.addWidget(self._content_title_lbl)
        hdr.addStretch()

        self._content_ts_lbl = QLabel("")
        self._content_ts_lbl.setFont(QFont("Courier New", 7))
        self._content_ts_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr.addWidget(self._content_ts_lbl)

        dismiss = QPushButton("DISMISS  ✕")
        dismiss.setFont(QFont("Courier New", 7))
        dismiss.setFixedHeight(18)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        dismiss.clicked.connect(w.hide)
        hdr.addWidget(dismiss)
        lay.addLayout(hdr)

        # ── separator ─────────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep)

        # ── text display ──────────────────────────────────────────────────────
        self._content_display = QTextEdit()
        self._content_display.setReadOnly(True)
        self._content_display.setFont(QFont("Courier New", 8))
        self._content_display.setMinimumHeight(60)
        self._content_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._content_display.setStyleSheet(f"""
            QTextEdit {{
                background: {C.DARK};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 3px;
                padding: 6px 8px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 3px; min-height: 16px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
        """)
        lay.addWidget(self._content_display)

        return w

    def _show_content(self, title: str, text: str):
        """Slot — runs on Qt main thread. Updates and shows the content panel."""
        import time as _time
        # The panel opens below the head, so the head looks down at it. It is a
        # tiny thing that answers "did that land?" before you read a word.
        self.hud.glance(0.0, -0.85, hold=1.3)
        self._content_title_lbl.setText(title.upper()[:48])
        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))
        self._content_display.setPlainText(text)
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start
        )
        first_show = not self._content_panel.isVisible()
        self._content_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 220, 120), 220])

    # ── document review ──────────────────────────────────────────────────────
    # Rendered as rich text into the content panel that already exists, rather
    # than into a panel of its own. A review is read, not clicked, so QTextEdit
    # gives scrolling, selection and copy for nothing, and the HUD gains no
    # widget it has to lay out. Severity decides colour and order here because
    # that is presentation; the plugin supplies no styling and knows no palette,
    # which is also what lets a re-theme repaint a review correctly.

    # Severity is marked by a symbol and a colour, not by a word. The findings
    # themselves are in the user's language, and "[SERIOUS]" sitting inside a
    # Turkish sentence is the kind of seam this project tries not to have —
    # while translating the tag would mean a table per language, which is worse.
    # A shape carries it in every language, and shape plus colour still reads
    # for someone who cannot separate red from amber. What the marks mean
    # arrives the way everything else does: JARVIS says it out loud.
    _REVIEW_MARKS = {"serious": ("RED", "▲"), "caution": ("ACC2", "●"), "note": ("PRI_DIM", "·")}

    @staticmethod
    def _esc(s) -> str:
        return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("\n", "<br>"))

    def _show_review(self, title: str, summary: str, findings, unclear):
        """Slot — Qt main thread. Lays a document review into the content panel."""
        e = self._esc
        parts = [f'<div style="color:{C.TEXT}; font-family:Courier New;">']

        if summary:
            parts.append(
                f'<div style="color:{C.WHITE}; border-left:2px solid {C.PRI};'
                f' padding-left:8px; margin-bottom:10px;">{e(summary)}</div>')

        for f in (findings or []):
            key, mark = self._REVIEW_MARKS.get(f.get("severity"), ("PRI_DIM", "·"))
            colour = getattr(C, key)
            parts.append(f'<div style="margin-bottom:11px;">')
            parts.append(
                f'<span style="color:{colour}; font-weight:bold;">{mark}</span> '
                f'<span style="color:{C.WHITE}; font-weight:bold;">'
                f'{e(f.get("heading"))}</span>')
            if f.get("detail"):
                parts.append(f'<div style="margin-left:12px;">{e(f["detail"])}</div>')
            if f.get("quote"):
                # The document's own wording, visually separated from the
                # explanation so the two are never mistaken for each other.
                parts.append(
                    f'<div style="margin-left:12px; color:{C.TEXT_DIM};'
                    f' border-left:1px solid {C.BORDER}; padding-left:7px;">'
                    f'&ldquo;{e(f["quote"])}&rdquo;</div>')
            if f.get("suggestion"):
                parts.append(
                    f'<div style="margin-left:12px; color:{C.PRI};">'
                    f'&rarr; {e(f["suggestion"])}</div>')
            parts.append('</div>')

        if unclear:
            parts.append(
                f'<div style="margin-top:6px; border-top:1px solid {C.BORDER};'
                f' padding-top:7px; color:{C.TEXT_MED};">'
                'The document does not settle:</div>')
            for u in unclear:
                parts.append(
                    f'<div style="margin-left:12px; color:{C.TEXT_MED};">'
                    f'&middot; {e(u)}</div>')
        parts.append('</div>')

        import time as _time
        self.hud.glance(0.0, -0.85, hold=1.3)
        # Left as written, not upper-cased. The other content-panel titles are
        # the app's own English labels, but this one is the document's name in
        # the user's language, and str.upper() applies English casing rules to
        # it: Turkish "Sözleşmesi" comes back "SÖZLEŞMESI", having lost the
        # dotted capital İ. Python has no locale-aware upper to reach for, and
        # imposing one language's rules on all of them is the bug, not the fix.
        self._content_title_lbl.setText((title or "Document")[:48])
        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))
        self._content_display.setHtml("".join(parts))
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start)
        first_show = not self._content_panel.isVisible()
        self._content_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 260, 120), 260, 0])

    # ── quiz panel ───────────────────────────────────────────────────────────
    # An interactive twin of the content panel. The plugin only ever hands over
    # questions; everything about asking, marking and reporting happens here,
    # and the finished result is pushed back into the conversation the same way
    # a dropped file is — as a message JARVIS reads and responds to. That keeps
    # the tool call short (it returns the moment the board is up) and leaves the
    # talking to the assistant, in the user's own language.

    def _quiz_btn(self, text: str, primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setFont(QFont("Courier New", 8))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(24)
        edge = C.BORDER_B if primary else C.BORDER
        col = C.PRI if primary else C.TEXT_MED
        b.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {col};
                border: 1px solid {edge}; border-radius: 2px;
                padding: 3px 9px; text-align: left;
            }}
            QPushButton:hover {{ color: {C.WHITE}; border-color: {C.PRI_DIM}; }}
            QPushButton:disabled {{ color: {C.TEXT_DIM}; border-color: {C.BORDER}; }}
        """)
        return b

    def _build_quiz_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("QuizPanel")
        w.setStyleSheet(f"""
            QWidget#QuizPanel {{
                background: {C.PANEL};
                border-top: 1px solid {C.BORDER_B};
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 7, 12, 8)
        lay.setSpacing(6)

        hdr = QHBoxLayout(); hdr.setSpacing(6)
        dot = QLabel("◈")
        dot.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)

        self._quiz_title_lbl = QLabel("QUIZ")
        self._quiz_title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._quiz_title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;")
        hdr.addWidget(self._quiz_title_lbl)
        hdr.addStretch()

        self._quiz_count_lbl = QLabel("")
        self._quiz_count_lbl.setFont(QFont("Courier New", 7))
        self._quiz_count_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr.addWidget(self._quiz_count_lbl)

        quit_btn = QPushButton("DISMISS  ✕")
        quit_btn.setFont(QFont("Courier New", 7))
        quit_btn.setFixedHeight(18)
        quit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        quit_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        quit_btn.clicked.connect(self._hide_quiz)
        hdr.addWidget(quit_btn)
        lay.addLayout(hdr)

        rule = QFrame(); rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {C.BORDER};")
        lay.addWidget(rule)

        self._quiz_q_lbl = QLabel("")
        self._quiz_q_lbl.setWordWrap(True)
        self._quiz_q_lbl.setFont(QFont("Courier New", 9))
        self._quiz_q_lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
        lay.addWidget(self._quiz_q_lbl)

        self._quiz_answers = QWidget()
        self._quiz_answers.setStyleSheet("background: transparent;")
        self._quiz_answers_lay = QVBoxLayout(self._quiz_answers)
        self._quiz_answers_lay.setContentsMargins(0, 2, 0, 0)
        self._quiz_answers_lay.setSpacing(4)
        lay.addWidget(self._quiz_answers)

        self._quiz_note_lbl = QLabel("")
        self._quiz_note_lbl.setWordWrap(True)
        self._quiz_note_lbl.setFont(QFont("Courier New", 8))
        self._quiz_note_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._quiz_note_lbl.hide()
        lay.addWidget(self._quiz_note_lbl)

        foot = QHBoxLayout()
        foot.addStretch()
        self._quiz_next_btn = self._quiz_btn("NEXT  →", primary=True)
        self._quiz_next_btn.setFixedWidth(110)
        self._quiz_next_btn.clicked.connect(self._quiz_next)
        self._quiz_next_btn.hide()
        foot.addWidget(self._quiz_next_btn)
        lay.addLayout(foot)

        self._quiz = None
        return w

    def _show_quiz(self, topic: str, questions, grader=None):
        """Slot — Qt main thread. Puts a fresh quiz on the board."""
        if not questions:
            return
        self._quiz = {
            "topic": topic or "",
            "questions": list(questions),
            "grader": grader,
            "i": 0,
            "results": [],
            "answered": False,
        }
        self._quiz_title_lbl.setText((topic or "quiz").upper()[:48])
        self.hud.glance(0.0, -0.85, hold=1.3)
        first_show = not self._quiz_panel.isVisible()
        self._quiz_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 250, 120), 0, 250])
        self._quiz_render()

    def _hide_quiz(self):
        self._quiz = None
        self._quiz_panel.hide()

    def _quiz_clear_answers(self):
        while self._quiz_answers_lay.count():
            item = self._quiz_answers_lay.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
                child.deleteLater()

    def _quiz_render(self):
        q = self._quiz["questions"][self._quiz["i"]]
        n, total = self._quiz["i"] + 1, len(self._quiz["questions"])
        self._quiz_count_lbl.setText(f"{n} / {total}")
        self._quiz_q_lbl.setText(q.get("question", ""))
        self._quiz_note_lbl.hide()
        self._quiz_next_btn.hide()
        self._quiz["answered"] = False
        self._quiz_clear_answers()

        opts = q.get("options") or []
        if opts:
            for text in opts:
                b = self._quiz_btn("   " + text)
                b.clicked.connect(lambda _=False, t=text: self._quiz_submit(t))
                self._quiz_answers_lay.addWidget(b)
        else:
            row = QWidget(); row.setStyleSheet("background: transparent;")
            h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
            field = QLineEdit()
            field.setFont(QFont("Courier New", 9))
            field.setPlaceholderText("your answer")
            field.setStyleSheet(f"""
                QLineEdit {{
                    background: {C.PANEL2}; color: {C.WHITE};
                    border: 1px solid {C.BORDER}; border-radius: 2px; padding: 4px 7px;
                }}
                QLineEdit:focus {{ border-color: {C.PRI_DIM}; }}
            """)
            send = self._quiz_btn("ANSWER", primary=True)
            send.setFixedWidth(90)
            field.returnPressed.connect(lambda: self._quiz_submit(field.text()))
            send.clicked.connect(lambda: self._quiz_submit(field.text()))
            h.addWidget(field, stretch=1)
            h.addWidget(send)
            self._quiz_answers_lay.addWidget(row)
            field.setFocus()

    def _quiz_submit(self, given: str):
        if self._quiz is None or self._quiz["answered"]:
            return
        self._quiz["answered"] = True
        q = self._quiz["questions"][self._quiz["i"]]
        grader = self._quiz.get("grader")
        verdict = None
        if callable(grader):
            try:
                verdict = grader(q, given)
            except Exception:
                verdict = None
        self._quiz["results"].append({
            "question": q.get("question", ""),
            "type": q.get("type", ""),
            "given": str(given or "").strip(),
            "answer": q.get("answer", ""),
            "correct": verdict,
        })

        for i in range(self._quiz_answers_lay.count()):
            wdg = self._quiz_answers_lay.itemAt(i).widget()
            if wdg is not None:
                wdg.setEnabled(False)

        if verdict is True:
            mark, colour = "✓  correct", C.GREEN
        elif verdict is False:
            mark, colour = "✕  " + str(q.get("answer", "")), C.RED
        else:
            # Open answers and near-miss gap-fills are JARVIS's to judge. Saying
            # so is honest; marking it wrong here would be a guess.
            mark, colour = "…  noted — I'll go over this one with you", C.ACC2
        note = q.get("note") or ""
        self._quiz_note_lbl.setText(mark + (("\n" + note) if note else ""))
        self._quiz_note_lbl.setStyleSheet(f"color: {colour}; background: transparent;")
        self._quiz_note_lbl.show()

        last = self._quiz["i"] >= len(self._quiz["questions"]) - 1
        self._quiz_next_btn.setText("FINISH  →" if last else "NEXT  →")
        self._quiz_next_btn.show()
        self._quiz_next_btn.setFocus()

    def _quiz_next(self):
        if self._quiz is None:
            return
        if self._quiz["i"] >= len(self._quiz["questions"]) - 1:
            self._quiz_finish()
        else:
            self._quiz["i"] += 1
            self._quiz_render()

    def _quiz_finish(self):
        if self._quiz is None:
            return
        topic = self._quiz["topic"]
        results = self._quiz["results"]
        right = sum(1 for r in results if r["correct"] is True)
        unsure = sum(1 for r in results if r["correct"] is None)
        total = len(results)
        self._quiz_panel.hide()
        self._quiz = None

        self._log.append_log(f"QUIZ: {topic or 'quiz'} — {right}/{total} correct")

        # Hand it back to JARVIS as a message, not as a tool return: the tool
        # call ended minutes ago. This is the same channel a dropped file uses.
        lines = [f"[QUIZ_DONE] topic={topic or 'general'} | "
                 f"auto-marked {right}/{total} correct"
                 + (f", {unsure} still need your marking" if unsure else "")]
        for i, r in enumerate(results, 1):
            state = ("correct" if r["correct"] is True
                     else "wrong" if r["correct"] is False else "NEEDS MARKING")
            lines.append(
                f"{i}. [{r['type']}] {r['question']} | they answered: "
                f"{r['given'] or '(blank)'} | expected: {r['answer']} | {state}")
        lines.append(
            "Mark every question flagged NEEDS MARKING yourself — accept an answer "
            "that means the same thing. Then tell them how they did in their own "
            "language: the score, what they got wrong and why, in a couple of "
            "sentences. Offer another round only if it fits. "
            "Remember something only if it would still matter next week — that they "
            "are working through a subject, or keep missing the same thing. A score "
            "from one session is not worth a memory, and a memory per quiz would "
            "bury the things that are.")
        msg = "\n".join(lines)
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _build_footer(self) -> QWidget:
        """Persistent compact command bar; activity history stays in its drawer."""
        w = QWidget()
        w.setFixedHeight(58)
        w.setStyleSheet(
            f"background: {C.DARK}; border-top: 1px solid {C.BORDER};"
        )
        root = QVBoxLayout(w)
        root.setContentsMargins(10, 5, 10, 5)
        root.setSpacing(3)

        command = QHBoxLayout()
        command.setSpacing(6)
        command.addLayout(self._command_input_row, 1)
        self._interrupt_btn.setFixedSize(112, 30)
        self._mute_btn.setFixedSize(150, 30)
        command.addWidget(self._interrupt_btn)
        command.addWidget(self._mute_btn)
        root.addLayout(command)

        meta = QHBoxLayout()
        meta.setContentsMargins(2, 0, 2, 0)
        hint = QLabel("[F4] Mute  ·  [F11] Fullscreen  ·  [ESC] Interrupt")
        hint.setFont(QFont("Courier New", 6))
        hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        meta.addWidget(hint)
        meta.addStretch()
        credit = QLabel("JARVIS  /  COMMAND CENTER")
        credit.setFont(QFont("Courier New", 6))
        credit.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        meta.addWidget(credit)
        root.addLayout(meta)
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell {self._assistant_name} what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def notify_phone_connected(self) -> None:
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay.mark_connected()

    def _open_remote(self):
        if not self.on_remote_clicked:
            self._log.append_log("SYS: Dashboard not running — remote unavailable.")
            return
        result = self.on_remote_clicked()
        if not result:
            self._log.append_log("SYS: Could not generate remote key.")
            return
        url    = result[0]
        key    = result[1]
        auto   = result[2] if len(result) >= 3 else ""
        manual = result[3] if len(result) >= 4 else url
        if self._remote_overlay:
            self._remote_overlay._do_close()
        cw  = self.centralWidget()
        ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
        ov  = RemoteKeyOverlay(url, key, auto_login_url=auto, manual_url=manual,
                               expiry_secs=600, parent=cw)
        ov.set_new_key_callback(self.on_remote_clicked)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.closed.connect(lambda: setattr(self, '_remote_overlay', None))
        ov.show()
        ov.raise_()
        self._voice_control_overlay = ov
        self._remote_overlay = ov
        self._log.append_log(f"SYS: Remote key generated — manual: {manual or url}")

    # ── Auto-start ──────────────────────────────────────────────────────────────

    @staticmethod
    def _autostart_target() -> tuple[list[str], str]:
        """Return argv and the app's real working directory for login launch.

        Login services start without the same current directory as a terminal.
        Keep paths as argv elements until each OS-specific file format is written,
        and support frozen builds where there is no separately launchable main.py.
        """
        if getattr(sys, "frozen", False):
            # In a one-file PyInstaller build, __file__ points into a temporary
            # extraction directory that is removed when this process exits.
            base = Path(sys.executable).resolve().parent
            return [str(Path(sys.executable).resolve())], str(base)
        base = Path(__file__).resolve().parent
        return [str(Path(sys.executable).resolve()), str(base / "main.py")], str(base)

    @staticmethod
    def _desktop_exec_arg(value: str) -> str:
        """Quote one argument according to the freedesktop Exec field rules."""
        escaped = (value.replace("\\", "\\\\").replace('"', '\\"')
                   .replace("$", "\\$").replace("`", "\\`").replace("%", "%%"))
        return f'"{escaped}"'

    @staticmethod
    def _desktop_entry_path(value: str) -> str:
        """Escape a path value in a freedesktop .desktop file."""
        return (value.replace("\\", "\\\\").replace("\n", "\\n")
                .replace("\t", "\\t").replace("\r", "\\r")
                .replace(" ", "\\s"))

    def _check_autostart(self) -> bool:
        """Returns True if auto-start is currently registered on this OS."""
        try:
            if _OS == "Windows":
                import winreg
                try:
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_READ,
                    )
                except FileNotFoundError:
                    return False
                with key:
                    try:
                        winreg.QueryValueEx(key, "JARVIS_AI")
                        return True
                    except FileNotFoundError:
                        return False
            elif _OS == "Darwin":
                return (Path.home() / "Library" / "LaunchAgents"
                        / "com.jarvis.assistant.plist").exists()
            else:
                return (Path.home() / ".config" / "autostart" / "jarvis.desktop").exists()
        except Exception:
            return False

    def _toggle_autostart(self):
        currently_on = self._check_autostart()
        try:
            argv, work_dir = self._autostart_target()
            if _OS == "Windows":
                import winreg
                run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.CreateKeyEx(
                    winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE
                ) as reg:
                    if currently_on:
                        winreg.DeleteValue(reg, "JARVIS_AI")
                    else:
                        target = Path(argv[0])
                        # pythonw avoids opening a console at login; a packaged
                        # GUI executable should be launched directly.
                        if not getattr(sys, "frozen", False):
                            pythonw = target.with_name("pythonw.exe")
                            if pythonw.is_file():
                                target = pythonw
                        command = " ".join(
                            f'"{arg}"' for arg in [str(target), *argv[1:]]
                        )
                        winreg.SetValueEx(
                            reg, "JARVIS_AI", 0, winreg.REG_SZ, command
                        )
            elif _OS == "Darwin":
                import plistlib
                plist_dir = Path.home() / "Library" / "LaunchAgents"
                plist_dir.mkdir(parents=True, exist_ok=True)
                plist = plist_dir / "com.jarvis.assistant.plist"
                if currently_on:
                    plist.unlink(missing_ok=True)
                else:
                    payload = {
                        "Label": "com.jarvis.assistant",
                        "ProgramArguments": argv,
                        "WorkingDirectory": work_dir,
                        "RunAtLoad": True,
                    }
                    plist.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML))
            else:
                desk_dir = Path.home() / ".config" / "autostart"
                desk_dir.mkdir(parents=True, exist_ok=True)
                desk = desk_dir / "jarvis.desktop"
                if currently_on:
                    desk.unlink(missing_ok=True)
                else:
                    exec_line = " ".join(
                        self._desktop_exec_arg(arg) for arg in argv
                    )
                    desk.write_text(
                        "[Desktop Entry]\n"
                        f"Name={self._assistant_name}\n"
                        f"Exec={exec_line}\n"
                        f"Path={self._desktop_entry_path(work_dir)}\n"
                        "Type=Application\nTerminal=false\n"
                        "X-GNOME-Autostart-enabled=true\n"
                    )
            enabled = self._check_autostart()
            if enabled == currently_on:
                raise RuntimeError("the operating system did not update its auto-start entry")
            self._update_autostart_btn(enabled)
            self._log.append_log(
                f"SYS: Auto-start {'enabled' if enabled else 'disabled'}.")
        except Exception as e:
            self._log.append_log(f"ERR: Auto-start failed — {e}")

    def _update_autostart_btn(self, enabled: bool):
        if not hasattr(self, '_autostart_btn'):
            return
        if enabled:
            self._autostart_btn.setText("◉  AUTO-START: ON")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._autostart_btn.setText("◉  AUTO-START: OFF")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    def _refresh_startup_video_btn(self):
        if not hasattr(self, "_startup_video_btn"):
            return
        from memory.config_manager import get_startup_video_enabled
        enabled = get_startup_video_enabled()
        self._startup_video_btn.setText(
            f"▶  STARTUP INTRO VIDEO: {'ON' if enabled else 'OFF'}"
        )
        if enabled:
            self._startup_video_btn.setStyleSheet(f"""
                QPushButton {{ background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                    text-align: left; padding: 0 8px; }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._startup_video_btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                    text-align: left; padding: 0 8px; }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    def _toggle_startup_video(self):
        from memory.config_manager import (
            get_startup_video_enabled, save_startup_video_enabled,
        )
        enabled = not get_startup_video_enabled()
        save_startup_video_enabled(enabled)
        self._refresh_startup_video_btn()
        self._log.append_log(
            f"SYS: Startup intro video {'enabled' if enabled else 'disabled'}; "
            "the change applies next launch."
        )

    def _toggle_brief(self):
        from memory.config_manager import get_brief_enabled, save_brief_enabled
        new_val = not get_brief_enabled()
        save_brief_enabled(new_val)
        self._update_brief_btn(new_val)

    # ── Wake word settings ───────────────────────────────────────────────────

    def _wake_state(self) -> dict:
        """Combined state for the two wake-word buttons. Readiness is a cheap,
        deterministic on-disk check now (see core.wake_word.is_ready), so there
        is nothing to cache — the button never flickers to a stale value."""
        if self.wake_get_state:
            try:
                s = self.wake_get_state()
                return {"ready": bool(s.get("ready")),
                        "enabled": bool(s.get("enabled")),
                        "awake": bool(s.get("awake")),
                        "clap_ready": bool(s.get("clap_ready"))}
            except Exception:
                failsoft.suppress('ui:MainWindow._wake_state')
        # Before JarvisLive has wired its callback (drawer built at startup).
        ready, enabled = False, False
        try:
            from core.wake_word import is_ready
            from memory.config_manager import get_wake_word_enabled
            ready, enabled = is_ready(), get_wake_word_enabled()
        except Exception:
            failsoft.suppress('ui:MainWindow._wake_state')
        return {"ready": ready, "enabled": enabled, "awake": True,
                "clap_ready": False}

    def _refresh_wake_btns(self):
        if not hasattr(self, '_wake_btn'):
            return
        st = self._wake_state()
        _on = f"""
            QPushButton {{ background: #001a08; color: {C.GREEN};
                border: 1px solid {C.GREEN_D}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ background: #002010; }}"""
        _off = f"""
            QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}"""
        self._wake_btn.setEnabled(True)
        if not st["ready"]:
            self._wake_btn.setText("⬇  WAKE WORD: DOWNLOAD")
            self._wake_btn.setStyleSheet(_off)
            if st.get("clap_ready"):
                self._wake_sleep_btn.show()
                self._wake_sleep_btn.setText("😴  SLEEP NOW" if st["awake"] else "👏  WAKE NOW")
                self._wake_sleep_btn.setStyleSheet(_off)
            else:
                self._wake_sleep_btn.hide()
        elif st["enabled"]:
            self._wake_btn.setText("🎙  WAKE WORD: ON")
            self._wake_btn.setStyleSheet(_on)
            self._wake_sleep_btn.show()
            self._wake_sleep_btn.setText("😴  SLEEP NOW" if st["awake"] else "👂  WAKE NOW")
            self._wake_sleep_btn.setStyleSheet(_off)
        else:
            self._wake_btn.setText("🎙  WAKE WORD: OFF")
            self._wake_btn.setStyleSheet(_off)
            if st.get("clap_ready"):
                self._wake_sleep_btn.show()
                self._wake_sleep_btn.setText("😴  SLEEP NOW" if st["awake"] else "👏  WAKE NOW")
                self._wake_sleep_btn.setStyleSheet(_off)
            else:
                self._wake_sleep_btn.hide()

    def _refresh_talk_btns(self):
        """Repaint the push-to-talk row from the saved setting."""
        if not hasattr(self, "_ptt_btn"):
            return
        from core.hotkey import chord_label
        from memory.config_manager import get_push_to_talk_enabled
        _on = f"""
            QPushButton {{ background: #001a08; color: {C.GREEN};
                border: 1px solid {C.GREEN_D}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ background: #002010; }}"""
        _off = f"""
            QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}"""

        ptt = get_push_to_talk_enabled()
        self._ptt_btn.setText(f"🎚  PUSH-TO-TALK: {chord_label()}" if ptt
                              else "🎚  PUSH-TO-TALK: OFF")
        self._ptt_btn.setStyleSheet(_on if ptt else _off)
        self._ptt_btn.setToolTip(
            "Microphone stays closed until you hold the key — nothing is sent "
            "while you are not holding it." if ptt
            else "Hold a key to talk instead of streaming the mic continuously.")


    def _refresh_hud_btn(self):
        from memory.config_manager import get_hud_style
        style = f"""
            QComboBox {{ background: {C.PANEL2}; color: {C.PRI};
                border: 1px solid {C.BORDER_A}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QComboBox:hover {{ color: {C.WHITE}; border: 1px solid {C.BORDER_B}; }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{ background: {C.PANEL2}; color: {C.TEXT};
                selection-background-color: {C.BORDER_A}; }}"""
        self._hud_btn.setStyleSheet(style)
        current = get_hud_style()
        index = self._hud_btn.findData(current)
        self._hud_btn.blockSignals(True)
        self._hud_btn.setCurrentIndex(max(0, index))
        self._hud_btn.blockSignals(False)
        descriptions = {
            "face": "Animated face mesh: keeps its gaze and mouth movement synced to JARVIS speech.",
            "core": "JARVIS logo/reactor: the existing identity mark, animated by assistant state and voice.",
            "neural": "Visualization 1: a full-screen multicolour synapse field with long firing fibers and live activity pulses.",
            "neural_orb": "Visualization 2: a luminous rotating neural orb with clustered firing nodes and live state response.",
        }
        self._hud_btn.setToolTip(descriptions.get(current, descriptions["face"]))

    def _refresh_neural_render_scale_btn(self):
        from memory.config_manager import get_neural_render_scale
        style = f"""
            QComboBox {{ background: {C.PANEL2}; color: {C.PRI};
                border: 1px solid {C.BORDER_A}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QComboBox:hover {{ color: {C.WHITE}; border: 1px solid {C.BORDER_B}; }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{ background: {C.PANEL2}; color: {C.TEXT};
                selection-background-color: {C.BORDER_A}; }}"""
        self._neural_scale_btn.setStyleSheet(style)
        current = get_neural_render_scale()
        index = self._neural_scale_btn.findData(current)
        self._neural_scale_btn.blockSignals(True)
        self._neural_scale_btn.setCurrentIndex(max(0, index))
        self._neural_scale_btn.blockSignals(False)
        self._neural_scale_btn.setToolTip(
            "Used only if the GPU scene graph cannot start. The GPU renderer "
            "always draws at native resolution; this is the sharpness/performance fallback."
        )

    def _on_neural_render_scale_selected(self, index: int):
        from memory.config_manager import save_neural_render_scale
        scale = self._neural_scale_btn.itemData(index)
        if scale is None:
            return
        scale = float(scale)
        save_neural_render_scale(scale)
        for canvas in (self.hud, self._immersive_overlay.hud):
            canvas._neural_render_scale = scale
            canvas._neural_render_image = None
            canvas.update()
        self._neural_scale_btn.setToolTip(
            f"QPainter fallback set to {scale:g}×. When the GPU scene graph is active, "
            "the neural field remains at native resolution."
        )

    def _on_hud_activity(self, _state: str):
        """Queue an activity pulse on the GUI thread for each assistant call."""
        self.hud.trigger_activity()
        self.hud.update()
        if hasattr(self, "_immersive_overlay"):
            self._immersive_overlay.hud.trigger_activity()
            self._immersive_overlay.hud.update()

    def _refresh_assistant_mode_btn(self):
        from memory.config_manager import get_assistant_mode
        mode = get_assistant_mode()
        idx = 1 if mode == "bihansa" else 0
        if hasattr(self, "_mode_btn"):
            self._mode_btn.blockSignals(True)
            self._mode_btn.setCurrentIndex(idx)
            self._mode_btn.blockSignals(False)
        if hasattr(self, "_hologram_mode_stack"):
            self._hologram_mode_stack.setCurrentIndex(1 if mode == "bihansa" and self._bihansa_hologram else 0)

    def _on_assistant_mode_selected(self, index: int):
        from memory.config_manager import save_assistant_mode
        want = self._mode_btn.itemData(index) or "jarvis"
        if want not in {"jarvis", "bihansa"}:
            want = "jarvis"
        save_assistant_mode(want)
        if hasattr(self, "_bihansa_settings") and self._bihansa_settings:
            self._bihansa_settings.assistant_mode = want
        if hasattr(self, "_hologram_mode_stack"):
            self._hologram_mode_stack.setCurrentIndex(1 if want == "bihansa" and self._bihansa_hologram else 0)
        self._log.append_log(f"SYS: Assistant mode set to '{want.upper()}'.")
        if callable(getattr(self, "on_voice_change", None)):
            self.on_voice_change()

    def _open_bihansa_settings_dialog(self):
        try:
            from ui.hologram.bihansa_settings import BihansaSettingsDialog
            dlg = BihansaSettingsDialog(self, settings=self._bihansa_settings, on_applied=self._on_bihansa_settings_applied)
            dlg.exec()
        except Exception as exc:
            self._log.append_log(f"ERR: Failed to open Bihansa settings: {exc}")

    def _on_bihansa_settings_applied(self):
        if hasattr(self, "_bihansa_settings") and self._bihansa_settings:
            if hasattr(self, "_bihansa_hologram") and self._bihansa_hologram:
                self._bihansa_hologram.set_reduced_motion(self._bihansa_settings.reduced_motion)
                self._bihansa_hologram.set_glow_intensity(self._bihansa_settings.glow_intensity)
                self._bihansa_hologram.set_animation_speed(self._bihansa_settings.animation_speed)
        self._refresh_assistant_mode_btn()
        if callable(getattr(self, "on_voice_change", None)):
            self.on_voice_change()

    def _on_hud_style_selected(self, index: int):
        """Persist and immediately display the selected HUD centrepiece."""
        from memory.config_manager import save_hud_style
        want = self._hud_btn.itemData(index)
        if want not in {"face", "core", "neural", "neural_orb"}:
            return
        save_hud_style(want)
        try:
            self.hud.hud_style = want
            self.hud.update()
            self._immersive_overlay.hud.hud_style = want
            self._immersive_overlay.hud.update()
        except Exception:
            failsoft.suppress('ui:MainWindow._on_hud_style_selected')
        if want in {"neural", "neural_orb"}:
            self._enter_immersive_view(want)
        else:
            self._leave_immersive_view()
        labels = {
            "face": "the animated face mesh",
            "core": "the JARVIS logo",
            "neural": "Visualization 1 — the synapse field",
            "neural_orb": "Visualization 2 — the neural orb",
        }
        self._hud_btn.setToolTip({
            "face": "Animated face mesh: keeps its gaze and mouth movement synced to JARVIS speech.",
            "core": "JARVIS logo/reactor: the existing identity mark, animated by assistant state and voice.",
            "neural": "Visualization 1: a full-screen multicolour synapse field with long firing fibers and live activity pulses.",
            "neural_orb": "Visualization 2: a luminous rotating neural orb with clustered firing nodes and live state response.",
        }[want])
        self._log.append_log(f"SYS: HUD switched to {labels[want]}.")

    def _toggle_ptt(self):
        from memory.config_manager import (get_push_to_talk_enabled,
                                           save_push_to_talk_enabled)
        want = not get_push_to_talk_enabled()
        save_push_to_talk_enabled(want)
        scope = None
        if self.on_push_to_talk:
            try:
                scope = self.on_push_to_talk(want)
            except Exception as e:
                self._log.append_log(f"ERR: Push-to-talk failed — {e}")
                save_push_to_talk_enabled(False)
                want = False
        self._apply_ptt_shortcut(want and scope != "global")
        self._refresh_talk_btns()

    def _apply_ptt_shortcut(self, needed: bool):
        """Bind the chord inside the window when no global hook is available.

        On macOS and Linux there is no dependency-free way to read global key
        state, so the chord is at least live whenever this window has focus.
        Qt gives no key-release for a QShortcut, so a press latches the mic open
        and a short timer closes it; held down, auto-repeat keeps pushing that
        timer out, which behaves like holding a key.
        """
        from PyQt6.QtGui import QKeySequence, QShortcut
        from core.hotkey import qt_sequence

        if not needed:
            sc = getattr(self, "_ptt_sc", None)
            if sc is not None:
                sc.setEnabled(False)
                self._ptt_sc = None
            self._ptt_hold(False)
            return
        if getattr(self, "_ptt_sc", None) is not None:
            return

        self._ptt_release = QTimer(self)
        self._ptt_release.setSingleShot(True)
        self._ptt_release.setInterval(420)
        self._ptt_release.timeout.connect(lambda: self._ptt_hold(False))

        def _press():
            self._ptt_hold(True)
            self._ptt_release.start()

        self._ptt_sc = QShortcut(QKeySequence(qt_sequence()), self)
        self._ptt_sc.setAutoRepeat(True)
        self._ptt_sc.activated.connect(_press)

    def _ptt_hold(self, held: bool):
        """Report a windowed press/release to whoever owns the microphone."""
        cb = getattr(self, "ptt_hold", None)
        if cb:
            try:
                cb(bool(held))
            except Exception:
                failsoft.suppress('ui:MainWindow._ptt_hold')

    def _toggle_wake_word(self):
        st = self._wake_state()
        if not st["ready"]:
            # First time: download openwakeword + model in a worker thread.
            self._wake_btn.setText("⬇  DOWNLOADING… (one-time)")
            self._wake_btn.setEnabled(False)
            def _work():
                try:
                    from core.wake_word import install_and_download
                    ok, msg = install_and_download(
                        logger=lambda m: self._log_sig.emit(f"SYS: {m}"))
                except Exception as e:
                    ok, msg = False, str(e)
                if ok and self.on_wake_toggle:
                    try:
                        self.on_wake_toggle(True)   # auto-enable after a successful download
                    except Exception:
                        failsoft.suppress('ui:MainWindow._toggle_wake_word._work')
                self._wake_dl_sig.emit(ok, msg)
            threading.Thread(target=_work, daemon=True).start()
            return
        # Already downloaded → just flip enabled/disabled through JarvisLive.
        if self.on_wake_toggle:
            try:
                self.on_wake_toggle(not st["enabled"])
            except Exception:
                failsoft.suppress('ui:MainWindow._toggle_wake_word')
        self._refresh_wake_btns()

    def _on_wake_install_done(self, ok: bool, msg: str):
        self._log_sig.emit(f"SYS: {'Wake word ready.' if ok else 'Wake word setup failed: ' + msg}")
        self._refresh_wake_btns()

    def _tap_wake_manual(self):
        if self.on_wake_manual:
            try:
                self.on_wake_manual()
            except Exception:
                failsoft.suppress('ui:MainWindow._tap_wake_manual')
        self._refresh_wake_btns()

    def _toggle_voice_id(self):
        if self.on_voice_id_action:
            try:
                result = self.on_voice_id_action("toggle")
                if result:
                    self._log.append_log(f"SYS: {result}")
            except Exception as e:
                self._log.append_log(f"ERR: Voice ID — {e}")

    def set_voice_id_enabled(self, enabled: bool):
        """Reflect the enforced Voice ID state in the settings control (thread-safe)."""
        self._voice_id_enabled_sig.emit(bool(enabled))

    def _apply_voice_id_enabled(self, enabled: bool):
        button = getattr(self, "_voice_id_btn", None)
        if button is None:
            return
        button.setEnabled(True)
        if enabled:
            button.setText("🔐  VOICE ID: ACTIVE")
            button.setStyleSheet(
                f"QPushButton {{ color: {C.GREEN}; background: #082116; "
                f"border: 1px solid {C.GREEN_D}; border-radius: 3px; }}"
            )
            button.setToolTip(
                "Owner speaker verification is required for sensitive actions and spoken approvals. "
                "Right-click to replace or remove the local profile."
            )
        else:
            button.setText("🔐  VOICE ID: OFF")
            button.setStyleSheet(
                f"QPushButton {{ color: {C.TEXT_MED}; background: transparent; "
                f"border: 1px solid {C.BORDER}; border-radius: 3px; }}"
            )
            button.setToolTip(
                "Click to enroll your voice if no profile exists, or enable an existing profile. "
                "Right-click for enrollment and profile removal options."
            )

    def _voice_id_menu(self, pos):
        if not self.on_voice_id_action:
            return
        from PyQt6.QtWidgets import QMenu, QMessageBox

        menu = QMenu(self)
        reenroll_owner = menu.addAction("Enroll / replace owner voice")
        enroll_sister = menu.addAction("Enroll / replace sister voice")
        remove_sister = menu.addAction("Remove sister voice profile")
        remove_all = menu.addAction("Remove all Voice ID profiles")
        chosen = menu.exec(self._voice_id_btn.mapToGlobal(pos))
        if chosen == reenroll_owner:
            result = self.on_voice_id_action("enroll_owner")
            if result:
                self._log.append_log(f"SYS: {result}")
        elif chosen == enroll_sister:
            result = self.on_voice_id_action("enroll_sister")
            if result:
                self._log.append_log(f"SYS: {result}")
        elif chosen == remove_sister:
            result = self.on_voice_id_action("remove_sister")
            if result:
                self._log.append_log(f"SYS: {result}")
        elif chosen == remove_all:
            answer = QMessageBox.question(
                self,
                "Remove Voice ID",
                "Delete all encrypted voice profiles and disable speaker checks?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                result = self.on_voice_id_action("remove")
                if result:
                    self._log.append_log(f"SYS: {result}")

    def _update_brief_btn(self, enabled: bool):
        if not hasattr(self, '_brief_btn'):
            return
        if enabled:
            self._brief_btn.setText("☀  MORNING BRIEF: ON")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._brief_btn.setText("☀  MORNING BRIEF: OFF")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    # ── Customization ────────────────────────────────────────────────────────────

    def _open_customize(self):
        cfg = _read_full_config()
        if self._customize_overlay:
            self._customize_overlay.hide()
        cw = self.centralWidget()
        ov = CustomizeOverlay(
            cfg.get("assistant_name", "JARVIS") or "JARVIS",
            cfg.get("user_name", ""),
            cfg.get("ui_color", "") or DEFAULT_UI_COLOR,
            cfg.get("voice_name", ""),
            parent=cw,
        )
        ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
        oh = min(oh, cw.height() - 16)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.on_preview = self._preview_ui_color
        ov.saved.connect(self._apply_name_update)
        ov.show()
        ov.raise_()
        self._voice_control_overlay = ov
        self._customize_overlay = ov

    def _open_voice_personality(self):
        from memory.voice_personality import get_voice_personality
        if self._personality_overlay:
            self._personality_overlay.hide()
        ov = VoicePersonalityOverlay(get_voice_personality(), parent=self.centralWidget())
        ov.saved.connect(self._apply_voice_personality)
        ov.preview_requested.connect(self._preview_voice_behavior)
        self._centre_overlay(ov)
        self._personality_overlay = ov

    def _preview_voice_behavior(self, settings: dict) -> None:
        if self.on_voice_preview and self.on_voice_preview(settings):
            self._log.append_log("SYS: Playing a local breath preview through the JARVIS audio stream.")
        else:
            self._log.append_log("SYS: Breath preview is unavailable while audio is busy or disconnected.")

    def _apply_voice_personality(self, settings: dict):
        from memory.voice_personality import MODE_DEFINITIONS, save_voice_personality
        try:
            profile = save_voice_personality(settings)
            label = MODE_DEFINITIONS[profile["mode"]]["label"]
            if profile["mode"] == "custom":
                label = profile["custom_name"]
            self._log.append_log(f"SYS: Response profile saved — {label}")
            if self.on_voice_personality_change:
                self.on_voice_personality_change()
        except Exception as exc:
            self._log.append_log(f"ERR: Response profile save failed — {exc}")

    def _preview_ui_color(self, hex_color: str):
        """Live preview — paints the whole interface the new colour (does NOT write to config)."""
        old = current_palette()
        if apply_ui_accent(hex_color):
            retheme_all_widgets(old, current_palette())

    def _apply_name_update(self, name: str, user_name: str, ui_color: str = "",
                           voice: str = ""):
        """Update all name/theme-dependent UI elements and persist to config."""
        self._assistant_name = name.strip() or "JARVIS"
        display = self._assistant_name.upper()
        self.setWindowTitle(f"{display} — {APP_VERSION}")
        self._title_lbl.setText(display)
        if display in ("JARVIS", "J.A.R.V.I.S"):
            self._sub_lbl.setText("Just A Rather Very Intelligent System")
        else:
            self._sub_lbl.setText("Personal AI Assistant")
        self._log._ai_name_lc = self._assistant_name.lower()
        self.hud._assistant_name = display

        color_changed = False
        if ui_color:
            old = current_palette()
            if apply_ui_accent(ui_color):
                # Live-paint the whole interface (panels, buttons, borders, HUD)
                retheme_all_widgets(old, current_palette())
                color_changed = old["PRI"] != C.PRI

        # Voice change → persist and, if it actually changed, rebuild the Live
        # session so the new voice takes effect (it's fixed at connect time).
        voice_changed = False
        if voice:
            from memory.config_manager import get_voice, save_voice
            if voice != get_voice():
                save_voice(voice)
                voice_changed = True

        try:
            data = _read_full_config()
            data["assistant_name"] = self._assistant_name
            data["user_name"] = user_name.strip()
            if ui_color:
                data["ui_color"] = ui_color.strip().lower()
            from memory.config_manager import write_api_config
            write_api_config(data)
            self._log.append_log(f"SYS: Identity updated — {display}")
            if color_changed:
                self._log.append_log(f"SYS: UI colour applied — {ui_color}")
            if voice_changed:
                self._log.append_log(f"SYS: Voice set — {voice}")
        except Exception as e:
            self._log.append_log(f"ERR: Config save failed — {e}")

        if voice_changed and self.on_voice_change:
            self.on_voice_change()

    def _centre_overlay(self, ov) -> None:
        """Place a floating overlay in the middle of the HUD and show it."""
        self._voice_control_overlay = ov
        cw = self.centralWidget()
        ov.adjustSize()
        ov.setGeometry(
            max(0, (cw.width()  - ov.width())  // 2),
            max(0, (cw.height() - ov.height()) // 2),
            ov.width(), ov.height(),
        )
        ov.show()
        ov.raise_()

    # ── Audio devices ────────────────────────────────────────────────────────

    def _open_provider_settings(self):
        from core.provider_settings import get_provider_settings
        if self._provider_overlay:
            self._provider_overlay.hide()
        ov = AIProviderOverlay(get_provider_settings(), parent=self.centralWidget())
        ov.saved.connect(self._save_provider_settings)
        self._centre_overlay(ov)
        self._provider_overlay = ov

    def _save_provider_settings(self, values: dict):
        from core.provider_settings import save_provider_settings
        try:
            save_provider_settings(**values)
            provider = values.get("provider", "gemini")
            label = {"gemini": "Gemini", "openai": "OpenAI GPT", "anthropic": "Anthropic Claude"}.get(provider, "Gemini")
            self._log.append_log(f"SYS: One-shot AI provider set to {label}. Live voice remains on Gemini.")
        except Exception as exc:
            self._log.append_log(f"ERR: AI provider settings could not be saved ({type(exc).__name__}).")
    def _open_audio_devices(self):
        ov = AudioDeviceOverlay(parent=self.centralWidget())
        ov.picked.connect(self._on_audio_devices_applied)
        self._centre_overlay(ov)
        self._audio_overlay = ov            # keep a reference so it isn't GC'd

    def _on_audio_devices_applied(self):
        self._log.append_log("SYS: Audio devices updated.")
        if self.on_audio_device_change:
            self.on_audio_device_change()

    # ── Memory panel ─────────────────────────────────────────────────────────

    def _open_memory_panel(self):
        ov = MemoryOverlay(parent=self.centralWidget())
        self._centre_overlay(ov)
        self._memory_overlay = ov

    # ── Irreversible-action confirmation ─────────────────────────────────────

    def _show_confirm_banner(self, title: str, detail: str):
        self._hide_confirm_banner()
        ov = ConfirmBanner(title, detail, parent=self.centralWidget())
        ov.answered.connect(self._on_confirm_answered)
        self._centre_overlay(ov)
        self._confirm_overlay = ov

    def _hide_confirm_banner(self):
        ov = getattr(self, "_confirm_overlay", None)
        if ov is not None:
            ov.hide()
            ov.deleteLater()
            self._confirm_overlay = None

    def _on_confirm_answered(self, accepted: bool):
        # Tear the banner down first: core.confirm.resolve() may be about to
        # shut the machine down, and a live widget mid-callback is not where you
        # want to be when that happens.
        self._hide_confirm_banner()
        try:
            from core.confirm import resolve
            resolve(bool(accepted))
        except Exception as e:
            self._log.append_log(f"ERR: Confirmation failed — {e}")

    def queue_voice_ui_command(self, command: VoiceUICommand) -> bool:
        """Queue a parsed voice command for execution on Qt's GUI thread."""
        if not isinstance(command, VoiceUICommand):
            return False
        try:
            self._voice_ui_command_sig.emit(command)
            return True
        except (RuntimeError, TypeError):
            return False

    @staticmethod
    def _voice_control_labels(widget: QWidget) -> list[str]:
        """Collect labels from a visible control and its nearby container context."""
        values: list[str] = []
        for attr in ("text", "objectName", "accessibleName", "toolTip", "statusTip", "windowTitle"):
            try:
                getter = getattr(widget, attr, None)
                value = getter() if callable(getter) else ""
                if value:
                    values.append(str(value))
            except (RuntimeError, TypeError):
                pass
        parent = widget.parentWidget()
        depth = 0
        while parent is not None and depth < 3:
            for attr in ("accessibleName", "windowTitle", "objectName", "toolTip"):
                try:
                    getter = getattr(parent, attr, None)
                    value = getter() if callable(getter) else ""
                    if value:
                        values.append(str(value))
                except (RuntimeError, TypeError):
                    pass
            parent = parent.parentWidget()
            depth += 1
        return values

    @staticmethod
    def _voice_control_score(target: str, labels: list[str]) -> int:
        """Score only exact/whole-token matches to avoid accidental clicks."""
        target_norm = normalize_label(target)
        if not target_norm:
            return 0
        variants = [target_norm]
        aliases = {
            "settings": ("settings", "controls", "gear"),
            "microphone": ("microphone", "mic"),
            "mic": ("mic", "microphone"),
            "ai provider settings": ("ai provider settings", "ai provider keys", "provider keys", "ai provider"),
            "response personality settings": ("response personality settings", "response personality", "personality"),
            "customize assistant": ("customize assistant", "customise assistant"),
            "remote control": ("remote control", "remote"),
            "fullscreen": ("fullscreen", "full screen"),
            "auto start": ("auto start", "autostart"),
            "wake word": ("wake word", "wake-word"),
            "fullscreen": ("fullscreen", "full screen"),
            "console": ("console", "command console"),
            "remote": ("remote", "remote control"),
            "field": ("field", "neural field"),
            "hand control": ("hand control", "hand"),
            "interrupt": ("interrupt", "stop speaking"),
        }
        variants.extend(aliases.get(target_norm, ()))
        normalized_labels = [normalize_label(label) for label in labels if label]
        best = 0
        for variant in set(variants):
            target_words = set(variant.split())
            if not target_words:
                continue
            for label in normalized_labels:
                if not label:
                    continue
                label_words = set(label.split())
                if label == variant:
                    score = 100
                elif variant in label:
                    score = 90
                elif target_words.issubset(label_words):
                    score = 80 + min(10, len(target_words))
                elif variant == "close" and label_words.intersection({"dismiss", "cancel"}):
                    score = 55
                else:
                    score = 0
                best = max(best, score)
        return best

    def _dispatch_voice_ui_command(self, command: VoiceUICommand) -> None:
        """Perform a narrowly matched command on visible JARVIS controls only."""
        if not isinstance(command, VoiceUICommand):
            return

        # Fail closed: generic UI commands must not bypass the owner session.
        try:
            from core import security
            if not security.is_owner_access_allowed():
                self._log.append_log(
                    "SEC: Voice UI control blocked — verify the owner session first."
                )
                return
        except Exception:
            self._log.append_log("SEC: Voice UI control blocked — authentication state unavailable.")
            return

        # The dedicated confirmation gate owns these controls. Do not let a
        # generic "click confirm" command bypass Voice ID/manual-click rules.
        try:
            from core.confirm import pending_title
            pending = pending_title()
        except Exception:
            pending = ""
        if pending:
            self._log.append_log(
                f"SEC: A protected confirmation is pending ({pending}). "
                "Use CONFIRM ACTION / CANCEL ACTION where voice approval is allowed; "
                "manual-click-only requests must be resolved on the HUD."
            )
            return

        # Some Qt child overlays do not set Qt's modal flag. Restrict voice
        # selection to the most recently raised centred overlay while it is
        # visible, so covered background controls cannot receive the command.
        control_root: QWidget = self
        # Native Qt dialogs (file choosers and QMessageBox prompts) are not
        # necessarily children of the window's tracked custom overlays. When
        # one is modal, scope voice actions to that dialog first.
        try:
            modal_widget = QApplication.activeModalWidget()
            if modal_widget is not None and modal_widget.isVisible():
                control_root = modal_widget
        except RuntimeError:
            pass

        active_overlay = getattr(self, "_voice_control_overlay", None)
        if control_root is self and active_overlay is not None:
            try:
                if active_overlay.isVisible():
                    control_root = active_overlay
                else:
                    self._voice_control_overlay = None
            except RuntimeError:
                self._voice_control_overlay = None

        if command.action in {"focus_next", "focus_previous"}:
            moved = control_root.focusNextPrevChild(command.action == "focus_next")
            self._log.append_log(
                "SYS: Focus moved." if moved else "SYS: No next/previous focusable control."
            )
            return

        if command.action in {"next_tab", "previous_tab"}:
            tabs = [
                tab for tab in control_root.findChildren(QTabWidget)
                if tab.isVisible() and tab.isEnabled() and tab.count() > 0
            ]
            if not tabs:
                self._log.append_log("SYS: No visible tab control is available.")
                return
            delta = -1 if command.action == "previous_tab" else 1
            focused = QApplication.focusWidget()
            focused_tab = next(
                (item for item in tabs if focused is not None and
                 (item is focused or item.isAncestorOf(focused))),
                None,
            )
            if focused_tab is None and len(tabs) > 1:
                self._log.append_log(
                    "SYS: Several tab controls are visible. Focus the one you want first."
                )
                return
            tab = focused_tab or tabs[0]
            new_index = tab.currentIndex() + delta
            if 0 <= new_index < tab.count():
                tab.setCurrentIndex(new_index)
                self._log.append_log(f"SYS: Selected tab {tab.tabText(new_index)}.")
            else:
                self._log.append_log("SYS: Already at the first/last tab.")
            return

        if command.action == "scroll":
            areas = [
                area for area in control_root.findChildren(QScrollArea)
                if area.isVisible() and area.isEnabled()
            ]
            if not areas:
                self._log.append_log("SYS: No visible scrollable panel was found.")
                return
            focused = QApplication.focusWidget()
            focused_area = next(
                (item for item in areas if focused is not None and item.isAncestorOf(focused)),
                None,
            )
            if focused_area is None and len(areas) > 1:
                self._log.append_log(
                    "SYS: Several scrollable panels are visible. Focus the panel you want to scroll."
                )
                return
            area = focused_area or areas[0]
            bar = area.verticalScrollBar()
            step = max(1, bar.singleStep()) * 3
            if command.target == "top":
                value = bar.minimum()
            elif command.target == "bottom":
                value = bar.maximum()
            elif command.target == "up":
                value = max(bar.minimum(), bar.value() - step)
            else:
                value = min(bar.maximum(), bar.value() + step)
            bar.setValue(value)
            self._log.append_log(f"SYS: Scrolled {command.target}.")
            return

        target = "close" if command.action == "close_active" else command.target
        if not target:
            self._log.append_log("SYS: Voice UI command needs a button/control name.")
            return
        if is_high_impact_ui_label(target):
            self._log.append_log(
                "SEC: This is a protected action. Use its dedicated confirmation flow; "
                "generic voice-click is disabled for it."
            )
            return

        def _find_matches(root: QWidget) -> list[tuple[int, QAbstractButton, list[str]]]:
            found: list[tuple[int, QAbstractButton, list[str]]] = []
            for candidate in root.findChildren(QAbstractButton):
                try:
                    if not candidate.isVisible() or not candidate.isEnabled():
                        continue
                    labels = self._voice_control_labels(candidate)
                    score = self._voice_control_score(target, labels)
                    if score:
                        found.append((score, candidate, labels))
                except RuntimeError:
                    continue
            return found

        matches = _find_matches(control_root)

        # Many quick actions live inside the settings drawer, which starts
        # hidden. A direct request for one of those actions may open the drawer
        # first, then match the newly visible target. Never open it behind an
        # active overlay or for an arbitrary label.
        drawer_targets = {
            "ai provider settings", "ai provider keys", "provider keys",
            "response personality", "response personality settings",
            "personality", "customize assistant", "customise assistant",
            "remote control", "fullscreen", "full screen", "auto start",
            "autostart", "wake word", "plugin settings", "plugins",
        }
        if (
            not matches
            and control_root is self
            and target in drawer_targets
            and hasattr(self, "_quick_drawer")
            and not self._quick_drawer.isVisible()
        ):
            self._drawer_btn.setChecked(True)
            self._toggle_drawer(True)
            matches = _find_matches(self)

        if not matches:
            self._log.append_log(
                f"SYS: No visible button matched '{target}'. Say 'click' and the exact label."
            )
            return

        highest = max(item[0] for item in matches)
        best = [item for item in matches if item[0] == highest]
        if len(best) != 1:
            labels = sorted({
                normalize_label(item[1].text()) or item[1].objectName() or "unnamed control"
                for item in best
            })
            self._log.append_log(
                f"SYS: '{target}' is ambiguous. Say a more specific label: "
                + ", ".join(labels[:5])
            )
            return

        _, button, labels = best[0]
        if any(is_high_impact_ui_label(label) for label in labels):
            self._log.append_log(
                "SEC: Voice click blocked for a protected control. Use the app's "
                "dedicated confirmation flow or click it manually."
            )
            return
        try:
            label = button.text().strip() or button.toolTip().strip() or target
            if command.action == "set_state":
                desired = command.desired_state
                if desired not in {"on", "off"}:
                    self._log.append_log("SYS: I could not determine the requested on/off state.")
                    return

                # Prefer Qt's real checked state for checkable controls. For
                # non-checkable status buttons, infer state only from explicit
                # words in the button's own visible label.
                current_state = None
                if button.isCheckable():
                    current_state = "on" if button.isChecked() else "off"
                else:
                    label_norm = normalize_label(button.text())
                    off_markers = {
                        "off", "muted", "disabled", "sleeping", "stopped",
                        "inactive", "closed", "paused", "disconnected",
                    }
                    on_markers = {
                        "on", "active", "unmuted", "enabled", "awake",
                        "running", "connected",
                    }
                    words = set(label_norm.split())
                    if words & off_markers:
                        current_state = "off"
                    elif words & on_markers:
                        current_state = "on"

                if current_state is None:
                    self._log.append_log(
                        f"SYS: I found '{label}', but cannot safely tell whether it is "
                        f"already {desired}. Use 'toggle {target}' or inspect the button."
                    )
                    return
                if current_state == desired:
                    self._log.append_log(f"SYS: '{label}' is already {desired}.")
                    return

            button.click()
            self._log.append_log(f"SYS: Voice command activated '{label}'.")
        except RuntimeError:
            self._log.append_log("ERR: That control closed before it could be activated.")

    def _open_plugin_manager(self):
        plugins = self.get_plugins() if self.get_plugins else []
        cw = self.centralWidget()
        ov = PluginManagerOverlay(plugins, parent=cw)
        ov.adjustSize()
        ov.setGeometry(
            (cw.width()  - ov.width())  // 2,
            (cw.height() - ov.height()) // 2,
            ov.width(), ov.height(),
        )
        ov.show()
        ov.raise_()
        self._voice_control_overlay = ov
        self._plugin_manager_overlay = ov   # keep a reference so it isn't GC'd

    def _open_plugin_settings(self):
        sections = self.get_plugin_settings() if self.get_plugin_settings else []
        cw = self.centralWidget()
        ov = PluginSettingsOverlay(sections, parent=cw)
        ow = PluginSettingsOverlay._OW
        oh = min(560, cw.height() - 16)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.show()
        ov.raise_()
        self._voice_control_overlay = ov
        self._plugin_settings_overlay = ov   # keep a reference so it isn't GC'd

    # ── Clipboard intelligence ───────────────────────────────────────────────────

    def _on_clipboard_changed(self):
        try:
            text = QApplication.clipboard().text().strip()
            if len(text) >= 10:
                self._clipboard_sig.emit(text)
        except Exception:
            failsoft.suppress('ui:MainWindow._on_clipboard_changed')

    def _show_clipboard_panel(self, text: str):
        self._clipboard_panel.show_clipboard(text)
        self._position_clipboard_panel()

    def _position_clipboard_panel(self):
        cw = self.centralWidget()
        pw = ClipboardPanel._W
        ph = self._clipboard_panel.sizeHint().height() or ClipboardPanel._H
        x = (cw.width() - pw) // 2
        y = cw.height() - ph - 6
        self._clipboard_panel.setGeometry(x, y, pw, ph)
        self._clipboard_panel.raise_()

    def _on_clipboard_action(self, cmd: str):
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(cmd,), daemon=True).start()

    # ────────────────────────────────────────────────────────────────────────────

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._immersive_overlay.set_muted(self._muted)
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_audio_level(self, level: float) -> None:
        """Apply audio levels to HUD canvases on the Qt GUI thread only."""
        try:
            self.hud.set_audio_level(level)
        except (RuntimeError, TypeError, ValueError):
            pass
        overlay = getattr(self, "_immersive_overlay", None)
        if overlay is not None:
            try:
                overlay.hud.set_audio_level(level)
            except (RuntimeError, TypeError, ValueError):
                pass
        bihansa = getattr(self, "_bihansa_hologram", None)
        if bihansa is not None:
            try:
                bihansa.set_audio_energy(level)
            except (RuntimeError, TypeError, ValueError):
                pass

    def _apply_visemes(self, frames, hop: float, at: float) -> None:
        """Apply mouth-animation frames only on the Qt GUI thread."""
        try:
            self.hud.push_visemes(frames, hop, at)
        except (RuntimeError, TypeError, ValueError):
            pass
        overlay = getattr(self, "_immersive_overlay", None)
        if overlay is not None and getattr(self, "_immersive_open", False):
            try:
                overlay.hud.push_visemes(frames, hop, at)
            except (RuntimeError, TypeError, ValueError):
                pass

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")
        if hasattr(self, "_jarvis_logo_overlay"):
            self._jarvis_logo_overlay.set_state(state)
        if hasattr(self, "_immersive_overlay"):
            self._immersive_overlay.set_state(state)
        if hasattr(self, "_bihansa_hologram") and self._bihansa_hologram is not None:
            try:
                self._bihansa_hologram.set_state(state)
            except (RuntimeError, TypeError, ValueError):
                pass
        self._refresh_wake_btns()
        if hasattr(self, "_core_status_lbl"):
            display = state.replace("_", " ").upper()
            self._core_status_lbl.setText(f"JARVIS CORE\n{display}")
            color = C.ACC if state in ("THINKING", "SLEEPING") else C.GREEN
            if state in ("MUTED", "ERROR", "DISCONNECTED"):
                color = C.RED
            self._core_status_lbl.setStyleSheet(
                f"color: {color}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 4px;"
            )

    def _set_logo_audio_level(self, level) -> None:
        """Update the logo's voice bars on the Qt thread."""
        overlay = getattr(self, "_jarvis_logo_overlay", None)
        if overlay is not None:
            try:
                overlay.set_audio_level(level)
            except (TypeError, ValueError):
                overlay.set_audio_level(None)

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key"))
        except Exception:
            return False

    def _show_setup(self):
        if getattr(self, "_immersive_open", False):
            self._leave_immersive_view()
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        # A compact, centered credential card: one required Gemini key, no provider list.
        ow, oh = 480, 370
        ov.setGeometry(
            max(12, (cw.width() - ow) // 2),
            max(12, (cw.height() - oh) // 2),
            min(ow, max(300, cw.width() - 24)),
            min(oh, max(300, cw.height() - 24)),
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, setup: dict):
        key = str(setup.get("gemini_api_key", "")).strip()
        os.makedirs(CONFIG_DIR, exist_ok=True)
        # Preserve unrelated local preferences; update only credentials supplied here.
        config = _read_full_config()
        config["gemini_api_key"] = key
        for config_key in ("groq_api_key", "openai_api_key", "anthropic_api_key"):
            supplied = str(setup.get(config_key, "") or "").strip()
            if supplied:
                config[config_key] = supplied
        from memory.config_manager import write_api_config
        write_api_config(config)
        from core.provider_settings import save_provider_settings
        save_provider_settings(
            "gemini",
            groq_api_key=str(setup.get("groq_api_key", "") or ""),
            openai_api_key=str(setup.get("openai_api_key", "") or ""),
            anthropic_api_key=str(setup.get("anthropic_api_key", "") or ""),
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._assistant_name = _read_full_config().get("assistant_name", "JARVIS") or "JARVIS"
        self._log.append_log(f"SYS: AI providers initialised. {self._assistant_name} online.")
        QTimer.singleShot(0, self._show_owner_privacy_setup_if_needed)
        if self.hud.hud_style in ("neural", "neural_orb"):
            QTimer.singleShot(0, self._enter_immersive_view)


    def _show_owner_privacy_setup_if_needed(self) -> None:
        """Show one-time local owner PIN setup after API configuration."""
        try:
            from core.security import get_auth_manager
            if get_auth_manager().is_pin_enrolled():
                return
        except Exception as exc:
            self._log.append_log(f"SEC: Owner setup unavailable: {type(exc).__name__}")
            return
        self._show_owner_privacy_setup()


    def _show_owner_privacy_setup(self) -> None:
        """Enroll the owner PIN locally; optional Voice ID enrollment is user-controlled."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QMessageBox
        from core.security import get_auth_manager

        auth = get_auth_manager()
        if auth.is_pin_enrolled():
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("JARVIS — Privacy & Owner Security")
        dialog.setMinimumWidth(470)
        dialog.setModal(True)
        dialog.setStyleSheet(
            f"QDialog {{ background: {C.BG}; color: {C.TEXT}; }}"
            f"QLabel {{ color: {C.TEXT}; }}"
            f"QLineEdit {{ color: {C.TEXT}; background: {C.PANEL2}; padding: 9px; "
            f"border: 1px solid {C.BORDER}; border-radius: 5px; }}"
            f"QPushButton {{ padding: 9px 14px; border-radius: 5px; }}"
        )
        layout = QVBoxLayout(dialog)
        heading = QLabel("PRIVACY & OWNER SECURITY")
        heading.setStyleSheet(f"color: {C.PRI}; font-size: 16px; font-weight: bold;")
        layout.addWidget(heading)
        explanation = QLabel(
            "Create your owner PIN/password. JARVIS will start normally on future launches. "
            "Only sensitive actions require owner verification. Your PIN is hashed locally "
            "and is never sent to the AI provider."
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
        form.addRow("Confirm password", confirm_edit)
        layout.addLayout(form)

        voice_check = QCheckBox("Enroll my voice now (optional)", dialog)
        voice_check.setToolTip("Starts local Voice ID enrollment after the PIN is saved.")
        layout.addWidget(voice_check)
        face_check = QCheckBox("Face verification (not available yet)", dialog)
        face_check.setEnabled(False)
        face_check.setToolTip(
            "Face authorization stays disabled until a reliable, tested biometric verifier is available."
        )
        layout.addWidget(face_check)

        buttons = QHBoxLayout()
        save_button = QPushButton("SAVE & CONTINUE", dialog)
        save_button.setStyleSheet(f"background: {C.PRI}; color: #061018; font-weight: bold;")
        buttons.addWidget(save_button)
        layout.addLayout(buttons)

        def save_pin():
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
                QMessageBox.critical(dialog, "Setup failed", f"Owner PIN could not be saved: {exc}")
                return
            pin_edit.clear()
            confirm_edit.clear()
            dialog.accept()

        save_button.clicked.connect(save_pin)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._log.append_log("SEC: Owner PIN enrolled locally; startup remains unlocked for ordinary use.")
            if voice_check.isChecked() and self.on_voice_id_action:
                try:
                    status = self.on_voice_id_action("enroll_owner")
                    self._log.append_log(f"SEC: {status}")
                    QMessageBox.information(
                        self, "Voice ID enrollment",
                        status + "\n\nVoice matching is optional. If secure live-speaker verification "
                        "is unavailable, JARVIS will fall back to your PIN/password."
                    )
                except Exception as exc:
                    self._log.append_log(f"SEC: Voice enrollment could not start: {type(exc).__name__}")


    def _run_pin_prompt(self, callback):
        callback()

    def closeEvent(self, event):
        if getattr(self, "_neural_hand_active", False):
            self._stop_neural_hand_control()
        try:
            self._jarvis_logo_overlay.close()
        except Exception:
            failsoft.suppress('ui:MainWindow.closeEvent')
        try:
            self._workspace.shutdown_holo()
        except Exception:
            failsoft.suppress('ui:MainWindow.closeEvent')
        try:
            self._earth_panel.shutdown_web_engine()
        except Exception:
            failsoft.suppress('ui:MainWindow.closeEvent')
        super().closeEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            overlay = getattr(self, "_jarvis_logo_overlay", None)
            if overlay is None:
                return
            if self.isMinimized():
                overlay.show()
                overlay.raise_()
            else:
                overlay.hide()


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self.root = _RootShim(self._app)
        self._win.show()
        QTimer.singleShot(0, self._win._present_default_view)
        if self._win._check_config():
            QTimer.singleShot(350, self._win._show_owner_privacy_setup_if_needed)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    @property
    def on_voice_change(self):
        return self._win.on_voice_change

    @on_voice_change.setter
    def on_voice_change(self, cb):
        self._win.on_voice_change = cb

    @property
    def on_audio_device_change(self):
        return self._win.on_audio_device_change

    @on_audio_device_change.setter
    def on_audio_device_change(self, cb):
        self._win.on_audio_device_change = cb

    @property
    def on_voice_personality_change(self):
        return self._win.on_voice_personality_change

    @on_voice_personality_change.setter
    def on_voice_personality_change(self, cb):
        self._win.on_voice_personality_change = cb

    @property
    def on_voice_preview(self):
        return self._win.on_voice_preview

    @on_voice_preview.setter
    def on_voice_preview(self, cb):
        self._win.on_voice_preview = cb

    def queue_voice_ui_command(self, command: VoiceUICommand) -> bool:
        """Thread-safe: queue a validated UI command for the Qt thread."""
        return self._win.queue_voice_ui_command(command)

    def show_confirm(self, title: str, detail: str) -> None:
        """Thread-safe: raise the irreversible-action gate. Called from action
        handlers running in executor threads, so it goes through a signal."""
        detail_limit = 4500 if str(title) == "Instagram account access" else 300
        self._win._confirm_sig.emit(str(title)[:120], str(detail)[:detail_limit])

    def hide_confirm(self) -> None:
        """Thread-safe: take the gate down."""
        self._win._confirm_hide_sig.emit()

    @property
    def get_plugins(self):
        return self._win.get_plugins

    @get_plugins.setter
    def get_plugins(self, cb):
        self._win.get_plugins = cb

    @property
    def get_plugin_settings(self):
        return self._win.get_plugin_settings

    @get_plugin_settings.setter
    def get_plugin_settings(self, cb):
        self._win.get_plugin_settings = cb

    @property
    def on_wake_toggle(self):
        return self._win.on_wake_toggle

    @on_wake_toggle.setter
    def on_wake_toggle(self, cb):
        self._win.on_wake_toggle = cb

    @property
    def on_wake_manual(self):
        return self._win.on_wake_manual

    @on_wake_manual.setter
    def on_wake_manual(self, cb):
        self._win.on_wake_manual = cb

    @property
    def wake_get_state(self):
        return self._win.wake_get_state

    @wake_get_state.setter
    def wake_get_state(self, cb):
        self._win.wake_get_state = cb

    @property
    def on_voice_id_action(self):
        return self._win.on_voice_id_action

    @on_voice_id_action.setter
    def on_voice_id_action(self, cb):
        self._win.on_voice_id_action = cb

    def set_voice_id_enabled(self, enabled: bool):
        self._win.set_voice_id_enabled(enabled)

    def set_audio_level(self, level: float) -> None:
        """Thread-safe: queue audio-level updates for GUI-thread application."""
        try:
            value = float(level)
            self._win._audio_level_sig.emit(value)
            self._win._logo_level_sig.emit(value)
            from audio.visualizer_bridge import get_visualizer_bridge
            get_visualizer_bridge().push_audio_energy(value)
        except (RuntimeError, TypeError, ValueError):
            pass

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        """Ask the avatar to look somewhere for a moment (see HoloAvatar.glance)."""
        try:
            if self._avatar is not None:
                self._avatar.glance(dx, dy, hold)
        except Exception:
            failsoft.suppress('ui:JarvisUI.glance')

    def react_avatar_text(self, text: str) -> None:
        """Queue spoken-text facial cues safely onto the Qt UI thread."""
        try:
            self._win._avatar_cue_sig.emit(str(text or "")[:500])
        except RuntimeError:
            pass

    @property
    def ptt_hold(self):
        return self._win.ptt_hold

    @ptt_hold.setter
    def ptt_hold(self, cb):
        self._win.ptt_hold = cb

    @property
    def on_push_to_talk(self):
        return self._win.on_push_to_talk

    @on_push_to_talk.setter
    def on_push_to_talk(self, cb):
        self._win.on_push_to_talk = cb

    def push_visemes(self, frames, hop: float, at: float) -> None:
        """Thread-safe: queue mouth-animation frames for the Qt GUI thread."""
        try:
            self._win._visemes_sig.emit(list(frames), float(hop), float(at))
        except (RuntimeError, TypeError, ValueError):
            pass

    def notify_phone_connected(self) -> None:
        self._win.notify_phone_connected()

    def set_state(self, state: str):
        normalized = str(state or "").upper()
        if normalized in {"THINKING", "PROCESSING", "SPEAKING"}:
            self._win._hud_pulse_sig.emit(normalized)
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self, stop_event=None):
        while True:
            if stop_event is not None and stop_event.is_set():
                return False
            try:
                if self._win._ready:
                    return True
            except RuntimeError:
                # The native window was closed while setup was still open.
                return False
            time.sleep(0.1)

    def request_close(self):
        """Thread-safe request to close the native desktop window."""
        try:
            self._win._close_sig.emit()
        except RuntimeError:
            # The user may already have closed the Qt window.
            pass

    def show_content(self, title: str, text: str):
        """Thread-safe: display content in the panel below the HUD."""
        self._win._content_sig.emit(title[:48], text[:4000])

    def _show_workspace_view(self, kind: str, payload: dict):
        """Queue a typed viewer update onto the Qt GUI thread."""
        self._win._workspace_sig.emit(str(kind), dict(payload or {}))

    def show_holo_gestures(self):
        """Show the bundled gesture deck in the native HUD and request camera access."""
        self._show_workspace_view("holo", {})

    @property
    def holo_is_fullscreen(self) -> bool:
        try:
            return bool(self._win._workspace._is_fullscreen)
        except RuntimeError:
            return False

    def open_latest_holo_news(self, source: str = "") -> None:
        """Open the active or newest Newsfirst/Ada Derana story in Holo."""
        self._win._holo_news_sig.emit(str(source or ""))

    def close_holo_gestures(self):
        """Return to the avatar and release Holo's camera capture."""
        self._win._workspace.close_requested.emit()

    def show_video(self, source: str, title: str = "VIDEO"):
        self._show_workspace_view("video", {"source": str(source or ""), "title": str(title or "VIDEO")})

    def pause_video(self):
        self._show_workspace_view("video_pause", {})

    def seek_video(self, seconds: int = 10):
        self._show_workspace_view("video_seek", {"seconds": int(seconds)})

    def stop_video(self):
        self._show_workspace_view("video_stop", {})

    def hud_video_is_active(self) -> bool:
        """Lightweight state query used by playback routing before dispatch."""
        try:
            return bool(self._win._workspace._video_active)
        except (AttributeError, RuntimeError):
            return False

    def set_video_muted(self, muted: bool):
        self._show_workspace_view("video_mute", {"muted": bool(muted)})

    def show_webpage(self, url: str, title: str = "ARTICLE"):
        self._show_workspace_view("web", {"url": str(url or ""), "title": str(title or "ARTICLE")})

    def show_images(self, images, query: str = "IMAGE RESULTS"):
        self._show_workspace_view("images", {"images": list(images or []), "query": str(query or "IMAGE RESULTS")})

    def show_document(self, path: str, summary: str = ""):
        self._show_workspace_view("document", {"path": str(path or ""), "summary": str(summary or "")})

    def show_news_cards(self, items, title: str = "HEADLINES"):
        self._show_workspace_view("news", {"items": items, "title": str(title or "HEADLINES")})

    def show_briefing_news(self, items, title: str = "NEWSFIRST + ADA DERANA / LIVE BRIEFING"):
        """Show temporary HUD headline cards without switching the active workspace."""
        self._show_workspace_view("briefing_news", {"items": items, "title": str(title or "LIVE BRIEFING")})

    def hide_briefing_news(self):
        self._show_workspace_view("briefing_news_hide", {})

    def show_email_cards(self, items, title: str = "INBOX"):
        self._show_workspace_view("email", {"items": list(items or []), "title": str(title or "INBOX")})

    def show_calendar_cards(self, items, title: str = "AGENDA"):
        self._show_workspace_view("calendar", {"items": list(items or []), "title": str(title or "AGENDA")})

    def show_weather(self, report: dict):
        self._show_workspace_view("weather", {"report": dict(report or {})})

    def show_flight_cards(self, items, origin: str, destination: str, date: str):
        self._show_workspace_view("flights", {"items": list(items or []), "origin": origin, "destination": destination, "date": date})

    def add_reminder_card(self, message: str, target):
        value = target.isoformat() if hasattr(target, "isoformat") else str(target or "")
        self._show_workspace_view("reminder", {"message": message, "target": value})

    def start_timer(self, minutes: int, label: str = "COUNTDOWN"):
        self._show_workspace_view("timer", {"minutes": int(minutes), "label": str(label or "COUNTDOWN")})

    def show_market_chart(self, symbol: str):
        self._show_workspace_view("market", {"symbol": str(symbol or "")})

    def show_live_panel(self, name: str, focus: str | None = None):
        self._show_workspace_view(str(name or "system"), {"focus": str(focus or "")})

    def show_earth(self, destination: str = "", origin: str = "", mode: str = "show") -> None:
        """Thread-safe: show the in-window globe, locate a place, or plot a route."""
        self._win._earth_sig.emit(
            str(destination or "")[:160], str(origin or "")[:160], str(mode or "show")[:16]
        )

    def show_quiz(self, topic: str, questions, grade=None) -> None:
        """Thread-safe: put an interactive quiz on the board.

        `grade(question, given)` decides each answer — the plugin supplies it so
        the marking rules live with the questions rather than being duplicated
        here. Returning None from it means "JARVIS should judge this one", which
        is how open answers and near-miss gap-fills are handled.

        Returns immediately: the user answers at their own pace and the finished
        result is delivered back through on_text_command.
        """
        self._win._quiz_sig.emit(str(topic or ""), list(questions or []), grade)

    def hide_quiz(self) -> None:
        """Thread-safe: clear any quiz currently on the board."""
        self._win._quiz_hide_sig.emit()

    def show_review(self, title: str, summary: str, findings, unclear=None) -> None:
        """Thread-safe: lay a document review into the panel below the HUD.

        `findings` is a list of {heading, detail, severity, quote, suggestion};
        severity is one of 'serious' / 'caution' / 'note' and decides colour and
        order here, so the caller supplies no styling of its own.
        """
        self._win._review_sig.emit(str(title or ""), str(summary or ""),
                                   list(findings or []), list(unclear or []))

    def prompt_reconfig(self):
        """Thread-safe: show the API key setup overlay (e.g. after an auth error)."""
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def prompt_pin(self) -> str | None:
        """Thread-safe dialog asking for owner PIN/password input."""
        if not hasattr(self, "_win") or self._win is None:
            return None
        from PyQt6.QtWidgets import QInputDialog, QLineEdit, QApplication
        from PyQt6.QtCore import QThread
        import threading

        app = QApplication.instance()
        if app is None:
            return None

        result: list[str | None] = [None]
        done_event = threading.Event()

        def _show():
            if done_event.is_set():
                return
            try:
                text, ok = QInputDialog.getText(
                    self._win,
                    "JARVIS Owner Verification",
                    "Enter Owner PIN / Password:",
                    QLineEdit.EchoMode.Password,
                )
                if ok and text:
                    result[0] = text
            finally:
                done_event.set()

        if QThread.currentThread() == app.thread():
            _show()
        else:
            self._win._pin_prompt_sig.emit(_show)
            if not done_event.wait(timeout=30.0):
                done_event.set()
                return None

        return result[0]

    def show_camera_frame(self, img_bytes: bytes):
        """Thread-safe: show a webcam frame in the small overlay (screen captures)."""
        self._win._camera_sig.emit(img_bytes)

    def start_camera_stream(self) -> None:
        """Thread-safe: start live camera feed in the full HUD area."""
        self._win.start_camera_stream()

    def stop_camera_stream(self) -> None:
        """Thread-safe: stop the live camera feed."""
        self._win.stop_camera_stream()

    @property
    def assistant_name(self) -> str:
        return self._win._assistant_name

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
