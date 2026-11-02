"""The "volume" look of the holographic head: a smooth cyan hologram, no wires.

Where the cyber look (core/avatar_cyber.py) shows its construction, this one
hides it: the same sculpted head is filled with soft, translucent cyan light,
rim-lit at the silhouette, and rendered at half resolution then scaled up, so
the facets melt into a continuous volume. A small bloom pass adds the glow.
Only the features stay crisp: thick brows, glowing eyes, the lip line.

Hair is messy and spiky: filled tapered tufts that stand off the scalp and
fall across the forehead, over a denser hair cap. Everything is code-rendered
(QPainter + numpy); the geometry comes from CyberParts.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

VOLUME_PRIMARY = QColor(40, 215, 255)       # cyan
VOLUME_ACCENT = QColor(200, 252, 255)
FILL_ALPHA = 0.55                           # a solid-looking volume, still see-through
_LUT_N = 48
_DOWN = 0.5                                 # body rendered at half resolution
_BLOOM = 0.25


def _c(col: QColor, a: float) -> QColor:
    q = QColor(col)
    q.setAlpha(int(max(0.0, min(255.0, a))))
    return q


def grow_tufts(cap_v: np.ndarray, cap_f: np.ndarray, centre: np.ndarray, rng,
               count: int = 140) -> np.ndarray:
    """Spiky hair tufts as (T, 5, 3): base-left, base-right, tip, and two
    control points that bow the sides. Roots favour the front and the top."""
    if len(cap_f) == 0:
        return np.zeros((0, 5, 3), dtype=np.float32)
    tri = cap_v[cap_f]
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    mid = tri.mean(axis=1)
    weight = area * (0.2 + np.clip(mid[:, 2] + 0.5, 0, 1.5)) * (0.5 + np.clip(mid[:, 1], 0, 1))
    pick = rng.choice(len(cap_f), size=count, p=weight / weight.sum())
    up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    tufts = []
    for f in pick[:count]:
        w = rng.dirichlet((1.0, 1.0, 1.0)).astype(np.float32)
        root = (tri[f] * w[:, None]).sum(0)
        n = root - centre
        n /= np.linalg.norm(n) or 1.0
        x, y, z = (float(c) for c in root)
        across = np.array([1.0 if x > -0.15 else -1.0, 0.0, 0.0], dtype=np.float32)
        if z > 0.12 and y < 0.85 and rng.random() < 0.6:
            # A lock falling across the forehead.
            d = across * 0.7 - up * 0.55 + n * 0.25
            length = 0.16 + 0.10 * rng.random()
        elif abs(x) > 0.55 and y < 0.55:
            # Short at the sides, swept back.
            d = n * 0.45 - up * 0.5 + np.array([0, 0, -0.6], dtype=np.float32)
            length = 0.06 + 0.04 * rng.random()
        else:
            # Messy spikes standing up and out, leaning across.
            d = n * 0.75 + up * 0.35 + across * 0.35
            length = 0.10 + 0.12 * rng.random()
        d = d.astype(np.float32) + rng.normal(0, 0.22, 3).astype(np.float32)
        d -= n * min(0.0, float(np.dot(d, n)))            # never into the skull
        d /= np.linalg.norm(d) or 1.0
        side = np.cross(n, d)
        side /= np.linalg.norm(side) or 1.0
        half = (0.022 + 0.018 * rng.random())
        tip = root + d * length
        bow = n * (0.018 + 0.02 * rng.random())
        tufts.append([root - side * half, root + side * half, tip,
                      root - side * half * 0.5 + d * length * 0.55 + bow,
                      root + side * half * 0.5 + d * length * 0.55 + bow])
    return np.array(tufts, dtype=np.float32)


class VolumePainter:
    """Renders the smooth body into a half-size buffer, then composes it."""

    def __init__(self):
        self._buf: QImage | None = None
        self._lut_key = None
        self._lut: list[QColor] = []
        self._brushes: dict = {}

    # ── colour ──────────────────────────────────────────────────────────────
    def _brush(self, primary: QColor, li: int, alpha: int) -> QBrush:
        if self._lut_key != primary.rgb():
            deep = QColor(0, 30, 60)
            hi = QColor(225, 255, 255)
            self._lut = []
            for i in range(_LUT_N):
                t = (i + 0.5) / _LUT_N
                a, b, k = (deep, primary, t / 0.7) if t < 0.7 else (primary, hi, (t - 0.7) / 0.3)
                self._lut.append(QColor(int(a.red() + (b.red() - a.red()) * k),
                                        int(a.green() + (b.green() - a.green()) * k),
                                        int(a.blue() + (b.blue() - a.blue()) * k)))
            self._lut_key = primary.rgb()
            self._brushes.clear()
        key = (li, alpha)
        b = self._brushes.get(key)
        if b is None:
            col = QColor(self._lut[li])
            col.setAlpha(alpha)
            b = self._brushes[key] = QBrush(col)
        return b

    # ── body ────────────────────────────────────────────────────────────────
    def fill(self, p: QPainter, xs, ys, verts, vnorm, faces, order_key, primary: QColor,
             amp: float, fade=None, gain: float = 1.0, cull: bool = True) -> None:
        """Smooth-shaded translucent facets.

        Lighting uses the *vertex* normals averaged per facet rather than the
        facet's own normal, so neighbouring facets shade alike and the surface
        reads as continuous; the half-resolution buffer blurs what is left.
        """
        a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
        cross = (xs[b] - xs[a]) * (ys[c] - ys[a]) - (xs[c] - xs[a]) * (ys[b] - ys[a])
        keep = np.abs(cross) > 0.4
        if cull and keep.any():
            sign = np.sign(np.median(cross[keep]))
            keep &= (cross * sign) > 0
        vis = np.flatnonzero(keep)
        if vis.size == 0:
            return
        n = vnorm[a[vis]] + vnorm[b[vis]] + vnorm[c[vis]]
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        nz = np.abs(n[:, 2])
        key = np.clip(n[:, 0] * -0.40 + n[:, 1] * 0.50 + nz * 0.62, 0, 1)
        rim = np.clip(1.0 - nz, 0, 1) ** 2.0
        bright = np.clip(0.22 + 0.50 * key + 0.55 * rim + 0.12 * amp, 0, 1)
        alpha = 255 * FILL_ALPHA * gain * (0.45 + 0.55 * np.clip(bright + rim * 0.5, 0, 1))
        if fade is not None:
            f = np.minimum(np.minimum(fade[a[vis]], fade[b[vis]]), fade[c[vis]])
            alpha *= f ** 1.2
        fz = (verts[a[vis], 2] + verts[b[vis], 2] + verts[c[vis], 2]) / 3.0
        order = np.argsort(order_key[vis] * 1000.0 + fz, kind="stable")
        li = np.clip((bright * _LUT_N).astype(np.int32), 0, _LUT_N - 1)[order].tolist()
        al = ((np.minimum(alpha[order], 255) / 12).astype(np.int32) * 12).tolist()
        av, bv, cv = a[vis][order], b[vis][order], c[vis][order]
        tri = np.stack([xs[av], ys[av], xs[bv], ys[bv], xs[cv], ys[cv]], axis=1).tolist()
        p.setPen(Qt.PenStyle.NoPen)
        for q, i, aa in zip(tri, li, al):
            if aa < 12:
                continue
            p.setBrush(self._brush(primary, i, aa))
            p.drawPolygon(QPolygonF((QPointF(q[0], q[1]), QPointF(q[2], q[3]), QPointF(q[4], q[5]))))

    def tufts(self, p: QPainter, pts: np.ndarray, depth: np.ndarray, normal_z: np.ndarray,
              hair: QColor, light: QColor, grey=None) -> None:
        """Filled, tapered hair spikes, far ones first. `grey` marks the
        temple tufts, drawn paler (the grey at the sides)."""
        order = np.argsort(depth)
        body = _c(hair, 150)
        pale = _c(QColor(205, 235, 245), 150)
        edge = QPen(_c(light, 120), 0.8)
        for k in order.tolist():
            if normal_z[k] < -0.15:
                continue
            p.setBrush(pale if grey is not None and grey[k] else body)
            (lx, ly), (rx, ry), (tx, ty), (clx, cly), (crx, cry) = pts[k].tolist()
            path = QPainterPath(QPointF(lx, ly))
            path.quadTo(clx, cly, tx, ty)
            path.quadTo(crx, cry, rx, ry)
            path.closeSubpath()
            p.setPen(edge)
            p.drawPath(path)

    def compose(self, target: QPainter, rect: QRectF, draw) -> None:
        """Run `draw(painter)` into a half-size buffer and lay it over `rect`
        smoothly scaled, plus a soft bloom."""
        w = max(8, int(rect.width() * _DOWN))
        h = max(8, int(rect.height() * _DOWN))
        if self._buf is None or self._buf.width() != w or self._buf.height() != h:
            self._buf = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        self._buf.fill(0)
        bp = QPainter(self._buf)
        try:
            bp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            bp.scale(_DOWN, _DOWN)
            bp.translate(-rect.left(), -rect.top())
            draw(bp)
        finally:
            bp.end()
        target.save()
        target.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        target.drawImage(rect, self._buf)
        bloom = self._buf.scaled(max(2, int(w * _BLOOM)), max(2, int(h * _BLOOM)),
                                 Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        target.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        target.setOpacity(0.55)
        target.drawImage(rect, bloom)
        target.restore()

    # ── crisp features ──────────────────────────────────────────────────────
    @staticmethod
    def brow(p: QPainter, xs, ys, idx, thick: float, col: QColor) -> None:
        """A thick, tapered brow: a band around the landmark line, heavier
        towards the nose."""
        bx, by = xs[idx], ys[idx]
        if bx[0] > bx[-1]:
            bx, by = bx[::-1], by[::-1]
        inner_left = abs(bx[0] - np.mean(xs)) < abs(bx[-1] - np.mean(xs))
        n = len(bx)
        top, bot = [], []
        for i in range(n):
            t = i / (n - 1)
            w = thick * (1.0 - 0.55 * t if inner_left else 0.45 + 0.55 * t)
            top.append(QPointF(float(bx[i]), float(by[i]) - w * 0.65))
            bot.append(QPointF(float(bx[i]), float(by[i]) + w * 0.35))
        poly = QPolygonF(top + bot[::-1])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawPolygon(poly)

    @staticmethod
    def character(p: QPainter, xs, ys, lm: dict, r: float, col: QColor, stubble_xy) -> None:
        """The lines that give the face its age and weight: bags under the eyes,
        folds from the nose to the mouth, and stubble over the jaw."""
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(col, 110), max(1.0, r * 0.006)))
        for key in ("eye_l", "eye_r"):
            idx = lm[key]
            lower = idx[1:8]                         # the lower-lid half of the ring
            pts = [QPointF(float(xs[i]), float(ys[i]) + r * 0.045) for i in lower]
            p.drawPolyline(QPolygonF(pts))
        for alar, corner, side in ((129, 61, -1.0), (358, 291, 1.0)):
            a = QPointF(float(xs[alar]) + side * r * 0.02, float(ys[alar]))
            c = QPointF(float(xs[corner]) + side * r * 0.06, float(ys[corner]) + r * 0.02)
            ctrl = QPointF(a.x() + side * r * 0.07, (a.y() + c.y()) / 2)
            path = QPainterPath(a)
            path.quadTo(ctrl, c)
            p.drawPath(path)
        if stubble_xy is not None and len(stubble_xy):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(col, 70))
            d = max(0.6, r * 0.0045)
            for x, y in stubble_xy.tolist():
                p.drawEllipse(QPointF(x, y), d, d)

    @staticmethod
    def scanline(p: QPainter, rect: QRectF, t: float, col: QColor) -> None:
        """One faint sweep of light moving down the volume: it reads as a
        hologram without drawing any structure."""
        y = rect.top() + (t * 0.18 % 1.0) * rect.height()
        p.setPen(QPen(_c(col, 40), 2.0))
        p.drawLine(QPointF(rect.left() + rect.width() * 0.2, y),
                   QPointF(rect.right() - rect.width() * 0.2, y))

    @staticmethod
    def nose_shadow(p: QPainter, xs, ys, nose_idx, col: QColor) -> None:
        if len(nose_idx) < 2:
            return
        pts = [QPointF(float(xs[i]), float(ys[i])) for i in nose_idx]
        p.setPen(QPen(col, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF(pts))
