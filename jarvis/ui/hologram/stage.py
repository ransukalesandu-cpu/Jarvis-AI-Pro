"""The hologram stage around the face: heart, orb and the energy wires.

Under the face sits a cyan orb that shows what JARVIS is doing (breathing when
idle, rippling inwards while it listens, spinning arcs while it thinks,
pulsing with the voice while it speaks). Bottom-left, a small heart beats in a
red / pink / orange aura. Five curved energy wires run from the neck to the
heart and on to the orb, and light travels along them with the voice.

Everything animates from one time value (the shared clock in core/ui_state)
so the heart, the pulses and the orb stay in step. Glow sprites are cached
pixmaps, rebuilt only when their size or colour changes; per frame the stage
only scales and fades them and strokes a few paths.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap,
                         QRadialGradient)

from jarvis.core.hologram_theme import JARVIS_PALETTE

WIRES = 5


def _q(rgb, a: float = 255) -> QColor:
    return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(max(0, min(255, a))))


def _mix(a, b, t: float):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _cubic(p0, p1, p2, p3, t: float) -> QPointF:
    u = 1.0 - t
    x = u * u * u * p0.x() + 3 * u * u * t * p1.x() + 3 * u * t * t * p2.x() + t * t * t * p3.x()
    y = u * u * u * p0.y() + 3 * u * u * t * p1.y() + 3 * u * t * t * p2.y() + t * t * t * p3.y()
    return QPointF(x, y)


class HologramStage:
    """Paints the heart, the orb and the wires. One per HUD canvas."""

    def __init__(self, palette=JARVIS_PALETTE):
        self.palette = palette
        self._sprites: dict = {}
        self._level = 0.0
        self.wires = WIRES          # the performance tier lowers these
        self.pulses = True

    # ── cached glow sprites ─────────────────────────────────────────────────
    def _glow(self, radius: int, rgb, core_alpha: int = 200) -> QPixmap:
        radius = max(4, int(radius))
        key = ("glow", radius, tuple(int(c) for c in rgb), core_alpha)
        pm = self._sprites.get(key)
        if pm is None:
            pm = QPixmap(radius * 2, radius * 2)
            pm.fill(Qt.GlobalColor.transparent)
            g = QRadialGradient(radius, radius, radius)
            g.setColorAt(0.0, _q(rgb, core_alpha))
            g.setColorAt(0.35, _q(rgb, core_alpha * 0.45))
            g.setColorAt(1.0, _q(rgb, 0))
            sp = QPainter(pm)
            sp.setPen(Qt.PenStyle.NoPen)
            sp.setBrush(QBrush(g))
            sp.drawEllipse(0, 0, radius * 2, radius * 2)
            sp.end()
            if len(self._sprites) > 24:
                self._sprites.clear()
            self._sprites[key] = pm
        return pm

    def _blit(self, p: QPainter, pm: QPixmap, c: QPointF, scale: float, opacity: float) -> None:
        w = pm.width() * scale
        p.setOpacity(max(0.0, min(1.0, opacity)))
        p.drawPixmap(QRectF(c.x() - w / 2, c.y() - w / 2, w, w), pm, QRectF(pm.rect()))
        p.setOpacity(1.0)

    # ── geometry ────────────────────────────────────────────────────────────
    @staticmethod
    def geometry(W: float, H: float, band_top: float, band_h: float, cx: float):
        """Where the face, orb and heart go inside the canvas.

        The face keeps the top 80% of its band; the orb takes the rest below
        it; the heart sits low on the left of the stage, clear of both.
        """
        face_h = band_h * 0.80
        orb_r = max(10.0, min(band_h * 0.085, W * 0.06))
        orb = QPointF(cx, band_top + face_h + (band_h - face_h) * 0.55)
        heart_r = max(8.0, min(W, H) * 0.045)
        # Inside the stage (core/ui_layout: the middle 40%), low on its left,
        # so a window in the left dock never covers it.
        heart = QPointF(max(heart_r * 2.2, cx - W * 0.165), band_top + band_h * 0.86)
        return face_h, orb, orb_r, heart, heart_r

    def _wire_paths(self, neck: QPointF, heart: QPointF, orb: QPointF, spread: float):
        """Five strands neck -> heart, and five heart -> orb, hanging like
        cables: they dip below the straight line and fan out a little."""
        dx, dy = neck.x() - heart.x(), max(30.0, heart.y() - neck.y())
        ox = orb.x() - heart.x()
        sag = max(40.0, abs(orb.y() - heart.y()) + spread * 6)
        paths = []
        for i in range(WIRES):
            k = (i - (WIRES - 1) / 2) / ((WIRES - 1) / 2)          # -1 .. 1
            a0 = QPointF(neck.x() + k * spread, neck.y())
            a1 = QPointF(neck.x() + k * spread - dx * 0.10, neck.y() + dy * 0.9 + k * spread)
            a2 = QPointF(heart.x() + dx * 0.45, heart.y() + dy * 0.30 + k * spread * 1.5)
            a3 = QPointF(heart.x() + k * spread * 0.25, heart.y() + k * spread * 0.25)
            b1 = QPointF(heart.x() + ox * 0.30, heart.y() + sag * 0.9 + k * spread * 1.5)
            b2 = QPointF(orb.x() - ox * 0.30, orb.y() + sag * 0.7 + k * spread)
            b3 = QPointF(orb.x() + k * spread * 0.3, orb.y() + k * spread * 0.3)
            paths.append(((a0, a1, a2, a3), (a3, b1, b2, b3)))
        return paths

    # ── frame ───────────────────────────────────────────────────────────────
    def paint(self, p: QPainter, *, neck: QPointF, orb: QPointF, orb_r: float,
              heart: QPointF, heart_r: float, t: float, level: float, state: str,
              cyan=None) -> None:
        """Draw wires, heart and orb. ``level`` is the voice level 0..1."""
        pal = self.palette
        cyan = cyan or pal.primary
        self._level += (max(0.0, min(1.0, level)) - self._level) * 0.35
        lv = self._level
        state = (state or "").upper()
        speaking = state == "SPEAKING"
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_wires(p, neck, heart, orb, heart_r, t, lv, cyan)
        self._paint_heart(p, heart, heart_r, t, lv, speaking)
        self._paint_orb(p, orb, orb_r, t, lv, state, cyan)
        p.restore()

    def _paint_wires(self, p, neck, heart, orb, heart_r, t, lv, cyan) -> None:
        pal = self.palette
        spread = max(4.0, heart_r * 0.40)
        heart_rgb = _mix(pal.heart_red, pal.heart_pink, 0.5 + 0.5 * math.sin(t * 0.7))
        p.setBrush(Qt.BrushStyle.NoBrush)
        dots = []
        speed = 0.18 + 0.85 * lv
        paths = self._wire_paths(neck, heart, orb, spread)
        if self.wires < len(paths):                    # keep the middle strands
            lo = (len(paths) - self.wires) // 2
            paths = paths[lo:lo + max(1, self.wires)]
        for i, (seg_a, seg_b) in enumerate(paths):
            for seg, c0, c1 in ((seg_a, cyan, heart_rgb), (seg_b, heart_rgb, cyan)):
                path = QPainterPath(seg[0])
                path.cubicTo(seg[1], seg[2], seg[3])
                col = _mix(c0, c1, 0.5)
                p.setPen(QPen(_q(col, 26 + 40 * lv), 3.2))
                p.drawPath(path)
                p.setPen(QPen(_q(col, 70 + 90 * lv), 1.0))
                p.drawPath(path)
                # Pulses: two per strand, faster and brighter with the voice.
                for j in range(2 if self.pulses else 0):
                    f = (t * speed + i * 0.19 + j * 0.5) % 1.0
                    dots.append((_cubic(*seg, f), _mix(c0, c1, f)))
        for pt, rgb in dots:
            self._blit(p, self._glow(7, rgb, 230), pt, 1.0 + 0.8 * lv, 0.55 + 0.45 * lv)

    def _paint_heart(self, p, c, r, t, lv, speaking) -> None:
        pal = self.palette
        bpm = 92.0 if speaking else 68.0
        beat_t = (t * bpm / 60.0) % 1.0
        # Lub-dub: a strong beat and a softer one just after it.
        beat = math.exp(-((beat_t - 0.05) / 0.06) ** 2) + 0.6 * math.exp(-((beat_t - 0.28) / 0.06) ** 2)
        hue = (t * 0.25) % 3.0                         # red -> pink -> orange -> red
        cols = (pal.heart_red, pal.heart_pink, pal.heart_orange)
        i = int(hue)
        rgb = _mix(cols[i], cols[(i + 1) % 3], hue - i)
        # Aura.
        self._blit(p, self._glow(int(r * 2.6), rgb, 150), c, 1.0 + 0.15 * beat + 0.2 * lv, 0.55 + 0.35 * beat)
        # The heart shape.
        s = r * (0.82 + 0.14 * beat)
        path = QPainterPath(QPointF(c.x(), c.y() + s * 0.95))
        path.cubicTo(QPointF(c.x() - s * 1.35, c.y() + s * 0.05), QPointF(c.x() - s * 0.95, c.y() - s * 1.05),
                     QPointF(c.x(), c.y() - s * 0.42))
        path.cubicTo(QPointF(c.x() + s * 0.95, c.y() - s * 1.05), QPointF(c.x() + s * 1.35, c.y() + s * 0.05),
                     QPointF(c.x(), c.y() + s * 0.95))
        g = QRadialGradient(c.x() - s * 0.2, c.y() - s * 0.3, s * 1.4)
        g.setColorAt(0.0, _q(_mix(rgb, (255, 255, 255), 0.45), 230))
        g.setColorAt(0.6, _q(rgb, 170))
        g.setColorAt(1.0, _q(rgb, 60))
        p.setPen(QPen(_q(_mix(rgb, (255, 255, 255), 0.3), 220), 1.4))
        p.setBrush(QBrush(g))
        p.drawPath(path)

    def _paint_orb(self, p, c, r, t, lv, state, cyan) -> None:
        if state in ("SLEEPING", "STANDBY"):
            dim = 0.35
        else:
            dim = 1.0
        breathe = 0.5 + 0.5 * math.sin(t * 1.4)
        if state == "SPEAKING":
            rr = r * (1.0 + 0.30 * lv)
        elif state == "LISTENING":
            rr = r * (1.0 + 0.06 * breathe)
        else:
            rr = r * (0.96 + 0.06 * breathe)
        self._blit(p, self._glow(int(r * 2.4), cyan, 170), c, rr / r, dim * (0.6 + 0.4 * lv))
        # Core sphere.
        g = QRadialGradient(c.x() - rr * 0.3, c.y() - rr * 0.35, rr * 1.2)
        g.setColorAt(0.0, _q((235, 255, 255), 235 * dim))
        g.setColorAt(0.45, _q(cyan, 190 * dim))
        g.setColorAt(1.0, _q(_mix(cyan, (0, 20, 40), 0.6), 140 * dim))
        p.setPen(QPen(_q(cyan, 200 * dim), 1.2))
        p.setBrush(QBrush(g))
        p.drawEllipse(c, rr * 0.62, rr * 0.62)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if state == "THINKING":
            # Arcs chasing round the orb.
            for k in range(3):
                ang = (t * (90 + 40 * k)) % 360
                p.setPen(QPen(_q((255, 200, 110), 200 * dim), 2.0))
                rect = QRectF(c.x() - rr * (0.85 + 0.12 * k), c.y() - rr * (0.85 + 0.12 * k),
                              rr * 2 * (0.85 + 0.12 * k), rr * 2 * (0.85 + 0.12 * k))
                p.drawArc(rect, int(ang * 16), int((70 - 15 * k) * 16))
        elif state == "LISTENING":
            # Rings closing in: it is taking something in.
            for k in range(3):
                f = 1.0 - ((t * 0.8 + k / 3) % 1.0)
                p.setPen(QPen(_q((140, 255, 190), 170 * (1 - f) * dim), 1.5))
                p.drawEllipse(c, rr * (0.7 + 0.8 * f), rr * (0.7 + 0.8 * f))
        elif state == "SPEAKING":
            # Ripples going out with the voice.
            for k in range(3):
                f = (t * (0.9 + lv) + k / 3) % 1.0
                p.setPen(QPen(_q(cyan, 190 * (1 - f) * (0.4 + 0.6 * lv)), 1.6))
                p.drawEllipse(c, rr * (0.7 + 0.9 * f), rr * (0.7 + 0.9 * f))
        else:
            p.setPen(QPen(_q(cyan, 90 * dim), 1.0))
            p.drawEllipse(c, rr * 0.92, rr * 0.92)
