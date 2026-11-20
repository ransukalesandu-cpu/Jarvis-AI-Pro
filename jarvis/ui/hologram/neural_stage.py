"""The stage of the neural hologram: energy strands from the neck down into a glowing orb.

Replaces the heart / orb / five-wire stage (ui/hologram/stage.py) when the HUD's
hologram look is "neural". Under the head's neck disc, a bundle of thin strands
falls and converges into an orb; points of light run down them (towards the orb
while JARVIS speaks or works, slowly when idle). The orb is a bright core inside
concentric shells, wrapped in tilted orbit rings that spin faster while JARVIS
thinks, with sparks around it. Its colour follows the assistant state, always in
the blue family, and its size follows the real audio level. Faint rings behind the
head frame the whole figure.

QPainter only; sprites are cached, so a frame is a few dozen paths and blits.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QRadialGradient

from jarvis.core.avatar_neural import strand_path

STRANDS = 26
_STATE_RGB = {
    "SPEAKING": (90, 190, 255), "LISTENING": (70, 220, 255), "THINKING": (120, 150, 255),
    "PROCESSING": (120, 150, 255), "SEARCHING": (80, 230, 230), "EXECUTING": (150, 200, 255),
    "ERROR": (255, 90, 110), "MUTED": (90, 110, 140),
}
_IDLE = (60, 170, 255)


def _q(rgb, a: float = 255) -> QColor:
    return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(max(0, min(255, a))))


class NeuralStage:
    """Paints the frame rings, the strands and the orb. One per HUD canvas."""

    def __init__(self):
        self._sprites: dict = {}
        self._rgb = _IDLE
        self._level = 0.0
        self.strands = STRANDS        # the performance tier lowers these
        self.pulses = True

    @property
    def wires(self) -> int:
        """The performance tier speaks in the classic stage's wire count (5 = full)."""
        return max(1, round(self.strands / 5))

    @wires.setter
    def wires(self, value: int) -> None:
        self.strands = max(6, int(value) * 5 + 1)

    @staticmethod
    def geometry(W: float, H: float, band_t: float, band_h: float, cx: float):
        """(face_h, orb_centre, orb_r): the head takes the top, the orb sits below its neck."""
        face_h = band_h * 0.66
        orb_r = max(18.0, min(W * 0.075, band_h * 0.11))
        orb = QPointF(cx, band_t + face_h + (band_h - face_h) * 0.58)
        return face_h, orb, orb_r

    def _glow(self, radius: int, rgb, core: int) -> QPixmap:
        radius = max(4, int(radius))
        key = (radius, tuple(int(c) for c in rgb), core)
        pm = self._sprites.get(key)
        if pm is None:
            pm = QPixmap(radius * 2, radius * 2)
            pm.fill(Qt.GlobalColor.transparent)
            g = QRadialGradient(radius, radius, radius)
            g.setColorAt(0.0, _q(rgb, core))
            g.setColorAt(0.35, _q(rgb, core * 0.45))
            g.setColorAt(1.0, _q(rgb, 0))
            gp = QPainter(pm)
            gp.setPen(Qt.PenStyle.NoPen)
            gp.setBrush(QBrush(g))
            gp.drawEllipse(0, 0, radius * 2, radius * 2)
            gp.end()
            if len(self._sprites) > 48:
                self._sprites.clear()
            self._sprites[key] = pm
        return pm

    def paint_back(self, p: QPainter, cx: float, cy: float, r: float, t: float) -> None:
        """Faint concentric rings behind the head (drawn before it)."""
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k, a in ((1.0, 26), (0.78, 18), (1.22, 12)):
            p.setPen(QPen(_q((70, 150, 255), a + 6 * math.sin(t * 0.6 + k * 4)), 1.0))
            p.drawEllipse(QPointF(cx, cy), r * k, r * k)
        p.restore()

    def paint(self, p: QPainter, *, base: tuple[float, float, float], orb: QPointF, orb_r: float,
              t: float, level: float, state: str) -> None:
        """`base` is the neck disc (x, y, width) from the head; strands run from it to the orb."""
        level = max(0.0, min(1.0, float(level or 0.0)))
        self._level += (level - self._level) * 0.25
        tgt = _STATE_RGB.get(str(state or "").upper(), _IDLE)
        self._rgb = tuple(a + (b - a) * 0.08 for a, b in zip(self._rgb, tgt))
        rgb, lv = self._rgb, self._level
        busy = str(state or "").upper() in ("SPEAKING", "THINKING", "PROCESSING", "SEARCHING", "EXECUTING")

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        self._paint_strands(p, base, orb, orb_r, t, lv, busy)
        self._paint_orb(p, orb, orb_r, t, lv, rgb, busy)
        p.restore()

    def _paint_strands(self, p, base, orb, orb_r, t, lv, busy) -> None:
        bx, by, bw = base
        n = max(4, int(self.strands))
        bottom = QPointF(orb.x(), orb.y() - orb_r * 0.55)
        paths = []
        for i in range(n):
            k = (i - (n - 1) / 2) / ((n - 1) / 2)
            top = QPointF(bx + k * bw * 0.36, by + 2.0)
            end = QPointF(bottom.x() + k * orb_r * 0.55, bottom.y())
            paths.append(strand_path(top, end, k, t, orb_r * 0.25))
        a = 70 + 90 * lv + (30 if busy else 0)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, path in enumerate(paths):
            shade = 0.6 + 0.4 * math.sin(i * 1.7 + t * 0.9)
            p.setPen(QPen(_q((90, 180, 255), a * shade * 0.45), 3.0))
            p.drawPath(path)
            p.setPen(QPen(_q((185, 235, 255), a * shade), 0.9))
            p.drawPath(path)
        if not self.pulses:
            return
        speed = 0.55 if busy else 0.18
        dot = self._glow(5, (200, 240, 255), 230)
        for i, path in enumerate(paths):
            for j in range(2):
                ph = (t * speed + i * 0.137 + j * 0.5) % 1.0
                pt = path.pointAtPercent(ph)
                p.setOpacity(math.sin(ph * math.pi) * (0.55 + 0.45 * lv))
                p.drawPixmap(QPointF(pt.x() - 5, pt.y() - 5), dot)
        p.setOpacity(1.0)

    def _paint_orb(self, p, orb, r, t, lv, rgb, busy) -> None:
        breathe = 1.0 + 0.04 * math.sin(t * 1.4) + 0.30 * lv
        R = r * breathe
        halo = self._glow(int(R * 2.6), rgb, 120)
        p.drawPixmap(QPointF(orb.x() - halo.width() / 2, orb.y() - halo.height() / 2), halo)
        # Concentric shells.
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k, a in ((1.0, 200), (0.78, 150), (0.56, 120), (0.36, 160)):
            p.setPen(QPen(_q(rgb, a), 1.6 if k == 1.0 else 1.1))
            p.drawEllipse(orb, R * k, R * k)
        core = self._glow(int(R * 0.75), (235, 250, 255), 255)
        p.drawPixmap(QPointF(orb.x() - core.width() / 2, orb.y() - core.height() / 2), core)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_q((245, 252, 255), 230))
        p.drawEllipse(orb, R * 0.13, R * 0.13)
        # Tilted orbit rings.
        spin = 1.6 if busy else 0.35
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, (tilt, squash, size, a) in enumerate(((-12, 0.30, 1.55, 170), (14, 0.24, 1.78, 120),
                                                     (-4, 0.42, 1.32, 90), (28, 0.20, 1.95, 60))):
            p.save()
            p.translate(orb)
            p.rotate(tilt + 7.0 * math.sin(t * spin * (0.5 + 0.2 * i) + i))   # rock, never flip
            p.setPen(QPen(_q(rgb, a), 1.2))
            p.drawEllipse(QPointF(0, 0), R * size, R * size * squash)
            # A bead of light riding the ring.
            ang = t * spin * (1.0 + 0.3 * i) + i * 1.9
            bead = QPointF(math.cos(ang) * R * size, math.sin(ang) * R * size * squash)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_q((220, 245, 255), 210))
            p.drawEllipse(bead, 1.8, 1.8)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.restore()
        # Sparks.
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(24):
            a = (i * 0.61803 + t * 0.03 * (1 + i % 3)) * math.tau
            d = R * (1.3 + 0.9 * ((i * 0.38197) % 1.0))
            tw = 0.5 + 0.5 * math.sin(t * 3.0 + i * 2.3)
            p.setBrush(_q((200, 238, 255), 170 * tw))
            p.drawEllipse(QPointF(orb.x() + math.cos(a) * d, orb.y() + math.sin(a) * d * 0.75), 1.1, 1.1)
