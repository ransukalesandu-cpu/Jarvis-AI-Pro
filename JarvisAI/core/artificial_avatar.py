"""Artificial holographic avatar for the Jarvis HUD.

This renderer is deliberately synthetic (not a photo or realistic human mesh).
It implements the same small interface as core.avatar.HoloAvatar so the
existing HUD, voice pipeline, viseme scheduler and facial-text callbacks remain
unchanged. No new third-party dependency is required.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QBrush, QPainterPath, QPen, QPolygonF, QRadialGradient


def _with_alpha(color: QColor, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(max(0, min(255, int(alpha))))
    return result


class HoloAvatar:
    """Angular synthetic face with audio/viseme-driven mouth animation."""

    def __init__(self) -> None:
        self._time = 0.0
        self._mouth = 0.0
        self._mouth_width = 0.0
        self._energy = 0.0
        self._blink = 0.0
        self._next_blink = 2.7
        self._state = "INITIALISING"
        self._speaking = False
        self._muted = False
        self._expression = 0.0
        self._look_x = 0.0
        self._look_y = 0.0
        self._look_target = (0.0, 0.0)
        self._look_until = 0.0

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        self._look_target = (max(-1.0, min(1.0, float(dx))),
                             max(-1.0, min(1.0, float(dy))))
        self._look_until = self._time + max(0.0, float(hold))

    def react_to_text(self, text: str) -> None:
        raw = str(text or "").casefold()
        if any(k in raw for k in ("hello", "hi ", "hey", "ayubowan", "ආයුබෝවන්")):
            self._expression = 0.8
        elif "?" in raw:
            self._expression = 0.35
        else:
            self._expression = 0.0

    def step(self, dt: float, amp: float, speaking: bool = False,
             muted: bool = False, state: str = "",
             v_open: float | None = None, v_wide: float = 0.0,
             v_level: float | None = None,
             v_seq: list | None = None, v_hop: float = 0.02) -> None:
        dt = max(0.001, min(0.10, float(dt)))
        self._time += dt
        self._state = str(state or "IDLE").upper()
        self._speaking = bool(speaking and not muted)
        self._muted = bool(muted)

        # Consume every scheduled viseme frame. This preserves short lip
        # closures (M/B/P) even when the UI timer skips a render frame.
        if self._speaking and v_seq:
            for frame in v_seq:
                try:
                    level, openness, width = frame
                    level = max(0.0, min(1.0, float(level)))
                    openness = max(0.0, min(1.0, float(openness)))
                    width = max(-1.0, min(1.0, float(width)))
                    target = (level ** 0.55) * openness
                    if level < 0.035:
                        target = 0.0
                    frame_dt = max(0.008, min(0.04, float(v_hop)))
                    tau = 0.018 if target > self._mouth else 0.012
                    self._mouth += (target - self._mouth) * (1.0 - math.exp(-frame_dt / tau))
                    self._mouth_width += (width - self._mouth_width) * 0.55
                except (TypeError, ValueError):
                    continue
        elif self._speaking:
            shape = 0.75 if v_open is None else max(0.0, min(1.0, float(v_open)))
            level = max(float(amp), float(v_level or 0.0))
            target = min(1.0, max(0.0, (level ** 0.58) * shape))
            self._mouth += (target - self._mouth) * (1.0 - math.exp(-dt / 0.025))
            if v_wide is not None:
                self._mouth_width += (max(-1.0, min(1.0, float(v_wide))) -
                                      self._mouth_width) * 0.30
        else:
            self._mouth += (0.0 - self._mouth) * (1.0 - math.exp(-dt / 0.06))
            self._mouth_width += (0.0 - self._mouth_width) * 0.15

        self._mouth = max(0.0, min(1.0, self._mouth))
        target_energy = 0.72 if self._speaking else (0.5 if self._state == "LISTENING" else 0.22)
        if self._state in ("THINKING", "PROCESSING"):
            target_energy = 0.9
        if self._muted:
            target_energy = 0.12
        self._energy += (target_energy - self._energy) * (1.0 - math.exp(-dt / 0.22))

        if self._time >= self._next_blink:
            self._blink = 1.0
            self._next_blink = self._time + 2.2 + (math.sin(self._time * 2.1) + 1.0) * 1.2
        self._blink = max(0.0, self._blink - dt * 7.5)
        if self._time > self._look_until:
            self._look_target = (0.0, 0.0)
        self._look_x += (self._look_target[0] - self._look_x) * min(1.0, dt * 5.0)
        self._look_y += (self._look_target[1] - self._look_y) * min(1.0, dt * 5.0)

    def paint(self, p, cx: float, cy: float, r: float,
              primary: QColor, accent: QColor, bg: QColor) -> None:
        r = max(1.0, float(r))
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing, True)

        # Atmospheric rings and a subtle vertical hologram scan.
        halo = QRadialGradient(QPointF(cx, cy - 0.03 * r), r * 1.18)
        halo.setColorAt(0.0, _with_alpha(primary, int(23 + self._energy * 24)))
        halo.setColorAt(0.65, _with_alpha(primary, 10))
        halo.setColorAt(1.0, _with_alpha(primary, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QRectF(cx - r * 1.15, cy - r * 1.15, r * 2.3, r * 2.3))

        for k, alpha in ((1.02, 70), (1.10, 35), (1.18, 18)):
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_with_alpha(primary, int(alpha * (0.6 + self._energy))), max(1.0, r * 0.008)))
            p.drawEllipse(QRectF(cx-r*k, cy-r*k, 2*r*k, 2*r*k))

        # Angular helmet silhouette — unmistakably manufactured, not a human
        # portrait. Coordinates are normalized to the supplied HUD radius.
        def pt(x: float, y: float) -> QPointF:
            return QPointF(cx + x * r, cy + y * r)

        outline = QPolygonF([
            pt(-0.64, -0.70), pt(-0.40, -0.94), pt(0.40, -0.94),
            pt(0.64, -0.70), pt(0.76, -0.12), pt(0.62, 0.52),
            pt(0.30, 0.82), pt(-0.30, 0.82), pt(-0.62, 0.52),
            pt(-0.76, -0.12)
        ])
        face_path = QPainterPath()
        face_path.addPolygon(outline)
        face_path.closeSubpath()
        shell = QRadialGradient(pt(0.0, -0.25), r * 1.15)
        shell.setColorAt(0.0, QColor(18, 62, 83, 235))
        shell.setColorAt(0.65, QColor(8, 26, 40, 245))
        shell.setColorAt(1.0, QColor(4, 13, 25, 250))
        p.setBrush(QBrush(shell))
        p.setPen(QPen(_with_alpha(primary, 210), max(1.4, r * 0.018)))
        p.drawPath(face_path)

        # Forehead armour and temple plates.
        p.setBrush(_with_alpha(primary, 25))
        p.setPen(QPen(_with_alpha(primary, 125), max(1.0, r * 0.009)))
        p.drawPolygon(QPolygonF([pt(-0.39,-0.82), pt(-0.23,-0.90), pt(0.23,-0.90),
                                 pt(0.39,-0.82), pt(0.22,-0.70), pt(-0.22,-0.70)]))
        for side in (-1, 1):
            plate = QPolygonF([pt(side*0.62,-0.55), pt(side*0.48,-0.43),
                               pt(side*0.52,0.20), pt(side*0.66,0.34),
                               pt(side*0.70,-0.10)])
            p.setBrush(_with_alpha(accent, 22))
            p.drawPolygon(plate)
            # Thin circuit tracks on both temples.
            p.setPen(QPen(_with_alpha(primary, 145), max(1.0, r*0.008)))
            p.drawLine(pt(side*0.56,-0.34), pt(side*0.43,-0.24))
            p.drawLine(pt(side*0.43,-0.24), pt(side*0.48,-0.08))
            p.drawLine(pt(side*0.48,-0.08), pt(side*0.39,0.04))
            p.setBrush(_with_alpha(accent, 210))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(pt(side*0.56,-0.34), r*0.022, r*0.022)

        # Brow visor and luminous eyes; gaze moves slightly with glance cues.
        for side in (-1, 1):
            ex = side * 0.31 + self._look_x * 0.035
            ey = -0.28 + self._look_y * 0.025
            eye = QPolygonF([pt(ex-side*0.20, ey-0.055), pt(ex-side*0.12, ey-0.105),
                             pt(ex+side*0.16, ey-0.075), pt(ex+side*0.20, ey+0.005),
                             pt(ex+side*0.07, ey+0.065), pt(ex-side*0.16, ey+0.035)])
            p.setBrush(_with_alpha(primary, 34))
            p.setPen(QPen(_with_alpha(primary, 190), max(1.0, r*0.010)))
            p.drawPolygon(eye)
            eye_h = r * (0.035 + 0.035 * (1.0 - self._blink))
            p.setPen(QPen(_with_alpha(primary, 245), max(2.0, r*0.025), Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(pt(ex-side*0.12, ey), pt(ex+side*0.12, ey))
            p.setPen(QPen(_with_alpha(accent, 180), max(1.0, r*0.008)))
            p.drawLine(pt(ex-side*0.07, ey+eye_h), pt(ex+side*0.07, ey+eye_h))
            glow = QRadialGradient(pt(ex, ey), r*0.20)
            glow.setColorAt(0.0, _with_alpha(primary, 100))
            glow.setColorAt(1.0, _with_alpha(primary, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(QRectF(cx+(ex-0.20)*r, cy+(ey-0.20)*r, r*0.40, r*0.40))

        # Geometric nose sensor and cheek seams.
        p.setPen(QPen(_with_alpha(primary, 155), max(1.0, r*0.010)))
        p.drawLine(pt(0,-0.16), pt(-0.045,0.10))
        p.drawLine(pt(-0.045,0.10), pt(0.0,0.14))
        p.drawLine(pt(0.0,0.14), pt(0.045,0.10))
        for side in (-1, 1):
            p.drawLine(pt(side*0.19,0.18), pt(side*0.39,0.25))
            p.drawLine(pt(side*0.39,0.25), pt(side*0.34,0.38))

        # Voice-synced mouth: a mechanical aperture opens with the scheduled
        # viseme/audio envelope, changes width for rounded vs spread vowels,
        # and closes fully for silence and plosive consonants.
        my = 0.48
        mw = 0.19 + 0.055 * max(-1.0, self._mouth_width)
        mh = 0.018 + 0.105 * self._mouth
        mouth_rect = QRectF(cx-mw*r, cy+(my-mh/2)*r, 2*mw*r, max(2.0, mh*r))
        p.setBrush(QColor(1, 7, 14, 245))
        p.setPen(QPen(_with_alpha(primary, 235), max(1.2, r*0.014)))
        p.drawRoundedRect(mouth_rect, r*0.035, r*0.035)
        if self._mouth > 0.07:
            p.setClipRect(mouth_rect.adjusted(r*0.012, r*0.006, -r*0.012, -r*0.006))
            p.setPen(QPen(_with_alpha(primary, int(100 + 130*self._mouth)), max(1.0, r*0.009)))
            rows = max(1, int(1 + self._mouth * 4))
            for row in range(rows):
                yy = mouth_rect.top() + (row+1)*mouth_rect.height()/(rows+1)
                p.drawLine(QPointF(mouth_rect.left()+r*0.025, yy),
                           QPointF(mouth_rect.right()-r*0.025, yy))
            p.setClipping(False)

        # Chin module, lower jaw seams and animated scanning line.
        p.setBrush(_with_alpha(accent, 28))
        p.setPen(QPen(_with_alpha(primary, 145), max(1.0, r*0.009)))
        p.drawPolygon(QPolygonF([pt(-0.27,0.63), pt(-0.18,0.75), pt(0.18,0.75),
                                 pt(0.27,0.63), pt(0.16,0.58), pt(-0.16,0.58)]))
        p.drawLine(pt(-0.10,0.67), pt(0.10,0.67))
        scan_y = -0.86 + ((self._time * 0.42) % 1.0) * 1.60
        p.setClipPath(face_path)
        p.setPen(QPen(_with_alpha(primary, 36), max(1.0, r*0.012)))
        p.drawLine(pt(-0.70, scan_y), pt(0.70, scan_y))
        p.setClipping(False)

        # Status marker under the face.
        p.setPen(QPen(_with_alpha(primary, 150), max(1.0, r*0.008)))
        p.setBrush(_with_alpha(primary, int(35 + 70*self._energy)))
        p.drawRoundedRect(QRectF(cx-r*0.22, cy+r*0.90, r*0.44, r*0.055), r*0.02, r*0.02)
        p.restore()
