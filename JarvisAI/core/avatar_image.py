"""The "image" look: the owner's own face picture shown as a cyan hologram.

A mesh can only approximate a drawing; this shows the picture itself, so the
face is exactly the one supplied. The picture lives on the owner's machine,
not in the repository:

    JarvisAI/config/hologram_face.png   (or .webp / .jpg)

Optional ``hologram_face.json`` beside it gives the eye and mouth positions as
fractions of the picture (defaults suit a centred head-and-neck portrait):

    {"eyes": [[0.38, 0.475], [0.61, 0.475]], "mouth": [0.50, 0.70, 0.19]}

Processing (once, at load): the background is cut away by flooding in from
the border over light, grey pixels (a baked-in "transparent" checkerboard
included; the drawing's outline stops the flood), the picture is reduced to
light, re-coloured along a cyan ramp and given ~50% opacity and faint
scanlines. Per frame: a gentle float, a jaw that opens with speech, glowing
eyes and a sweeping scan line. Everything else stays QPainter.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF,
                         QRadialGradient, QTransform)

FACE_DIR = Path(__file__).resolve().parent.parent / "config"
FACE_NAMES = ("hologram_face.png", "hologram_face.webp", "hologram_face.jpg",
              "hologram_face.jpeg")
_MAX_H = 760                       # processed picture height in pixels
_DEFAULT_LAYOUT = {"eyes": [[0.38, 0.475], [0.61, 0.475]], "mouth": [0.50, 0.70, 0.19]}
EMOTIONS = ("happy", "sad", "serious", "surprised", "curious")
_GRID = (16, 22)                   # warp cells across, down
_REGION = (0.08, 0.26, 0.92, 0.985)  # warped part of the picture (u0, v0, u1, v1)


def find_face(directory: Path = FACE_DIR) -> Path | None:
    for name in FACE_NAMES:
        path = directory / name
        if path.is_file():
            return path
    return None


def _to_array(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(img.height(), img.bytesPerLine())
    return arr[:, :img.width() * 4].reshape(img.height(), img.width(), 4).copy()


def _from_array(arr: np.ndarray) -> QImage:
    h, w = arr.shape[:2]
    data = np.ascontiguousarray(arr, dtype=np.uint8)
    img = QImage(data.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return img.copy()                       # own the memory


def cut_background(rgba: np.ndarray) -> np.ndarray:
    """Foreground mask: flood from the border across light, unsaturated pixels."""
    rgb = rgba[..., :3].astype(np.int16)
    light = rgb.min(axis=2) > 170
    flat = (rgb.max(axis=2) - rgb.min(axis=2)) < 22
    open_ = (light & flat) | (rgba[..., 3] < 20)
    bg = np.zeros_like(open_)
    bg[0, :], bg[-1, :], bg[:, 0], bg[:, -1] = open_[0, :], open_[-1, :], open_[:, 0], open_[:, -1]
    while True:
        grown = bg.copy()
        grown[1:, :] |= bg[:-1, :]
        grown[:-1, :] |= bg[1:, :]
        grown[:, 1:] |= bg[:, :-1]
        grown[:, :-1] |= bg[:, 1:]
        grown &= open_
        if (grown == bg).all():
            break
        bg = grown
    fg = ~bg
    # Soften the cut edge by one pixel.
    soft = fg.astype(np.float32)
    soft[1:-1, 1:-1] = (soft[1:-1, 1:-1] * 4 + soft[:-2, 1:-1] + soft[2:, 1:-1]
                        + soft[1:-1, :-2] + soft[1:-1, 2:]) / 8.0
    return soft


class ImageHologram:
    def __init__(self, path: Path):
        img = QImage(str(path))
        if img.isNull():
            raise ValueError(f"cannot read {path}")
        if img.height() > _MAX_H:
            img = img.scaledToHeight(_MAX_H, Qt.TransformationMode.SmoothTransformation)
        rgba = _to_array(img)
        mask = cut_background(rgba)
        ys, xs = np.nonzero(mask > 0.5)
        if len(xs) < 100:
            raise ValueError("no foreground found in the face picture")
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        self._crop = (x0 / rgba.shape[1], y0 / rgba.shape[0],
                      x1 / rgba.shape[1], y1 / rgba.shape[0])
        rgba, mask = rgba[y0:y1, x0:x1], mask[y0:y1, x0:x1]
        lum = (rgba[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114],
                                                           dtype=np.float32)) / 255.0
        # Lift the mid-tones so shading reads on a dark HUD, keep the ink dark.
        self._lum = np.clip(lum, 0, 1) ** 0.8
        alpha = mask * (0.30 + 0.55 * self._lum)
        alpha[::3, :] *= 0.72                                  # faint scanlines
        self._alpha = alpha
        self._tint_key = None
        self._tinted: QImage | None = None
        self.aspect = rgba.shape[1] / rgba.shape[0]
        self.layout = self._load_layout(path)

    def _load_layout(self, path: Path) -> dict:
        layout = dict(_DEFAULT_LAYOUT)
        side = path.with_suffix(".json")
        if side.is_file():
            try:
                layout.update(json.loads(side.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        # Positions are fractions of the original picture; map them into the crop.
        cx0, cy0, cx1, cy1 = self._crop

        def fx(x):
            return (x - cx0) / (cx1 - cx0)

        def fy(y):
            return (y - cy0) / (cy1 - cy0)
        eyes = [(fx(x), fy(y)) for x, y in layout["eyes"]]
        mx, my, mw = layout["mouth"]
        return {"eyes": eyes, "mouth": (fx(mx), fy(my), mw / (cx1 - cx0))}

    def _image_for(self, primary: QColor) -> QImage:
        # Quantise so slow mood fades re-tint a handful of times, not every frame.
        key = (primary.red() // 12, primary.green() // 12, primary.blue() // 12)
        if key != self._tint_key or self._tinted is None:
            base = np.array([primary.red(), primary.green(), primary.blue()], dtype=np.float32)
            deep = np.array([0.0, 22.0, 48.0], dtype=np.float32)
            hi = np.array([230.0, 255.0, 255.0], dtype=np.float32)
            t = self._lum[..., None]
            rgb = np.where(t < 0.7, deep + (base - deep) * (t / 0.7),
                           base + (hi - base) * ((t - 0.7) / 0.3))
            out = np.empty(self._alpha.shape + (4,), dtype=np.uint8)
            out[..., :3] = np.clip(rgb, 0, 255)
            out[..., 3] = np.clip(self._alpha * 255, 0, 255)
            img = _from_array(out)
            self._tinted = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            self._tint_key = key
        return self._tinted

    # ── expression ──────────────────────────────────────────────────────────
    def _g(self, u, v, cu, cv, su, sv):
        return np.exp(-((u - cu) / su) ** 2 - ((v - cv) / sv) ** 2)

    def _field(self, u, v, f: dict):
        """Displacement (du, dv) of picture points for the current expression.

        Each move is a gaussian around a facial landmark: the jaw and lower lip
        drop, lip corners spread/round, lift (smile) or fall (sad), brows rise
        and knit, lids close, and the iris area slides with the gaze.
        """
        ly = self.layout
        mx, my, mw = ly["mouth"]
        du = np.zeros_like(u)
        dv = np.zeros_like(v)
        jaw = min(1.0, f["jaw"] + 0.55 * f["surprised"])
        g = self._g
        # Jaw and lips.
        dv += 0.042 * jaw * g(u, v, mx, my + 0.12, 0.24, 0.13)
        dv += 0.020 * jaw * g(u, v, mx, my + 0.018, 0.08, 0.022)
        dv -= 0.006 * jaw * g(u, v, mx, my - 0.012, 0.08, 0.018)
        for side in (-1.0, 1.0):
            cu = mx + side * mw / 2
            corner = g(u, v, cu, my, 0.040, 0.030)
            du += side * corner * (0.012 * f["wide"] + 0.014 * f["happy"] - 0.004 * f["sad"]
                                   - 0.006 * jaw)
            dv += corner * (-0.026 * f["happy"] + 0.018 * f["sad"] + 0.004 * f["serious"]
                            + 0.008 * jaw)
        # Eyes, lids, brows, cheeks.
        for i, (ex, ey) in enumerate(ly["eyes"]):
            side = -1.0 if ex < mx else 1.0
            lift = -0.012 * f["brow"] - 0.022 * f["surprised"]
            if i == 1:
                lift -= 0.026 * f["curious"]
            else:
                lift += 0.004 * f["curious"]
            brow_all = g(u, v, ex, ey - 0.065, 0.075, 0.030)
            inner = g(u, v, ex - side * 0.045, ey - 0.062, 0.035, 0.025)
            outer = g(u, v, ex + side * 0.055, ey - 0.058, 0.035, 0.025)
            dv += brow_all * lift
            dv += inner * (-0.014 * f["sad"] + 0.013 * f["serious"])
            du += inner * (-side) * 0.007 * f["serious"]
            dv += outer * (0.005 * f["sad"])
            lid_up = g(u, v, ex, ey - 0.014, 0.040, 0.016)
            lid_lo = g(u, v, ex, ey + 0.016, 0.035, 0.012)
            dv += lid_up * (0.026 * f["blink"] - 0.006 * f["surprised"])
            dv += lid_lo * (-0.004 * f["blink"] - 0.006 * f["happy"])
            dv += g(u, v, ex + side * 0.01, ey + 0.10, 0.06, 0.05) * (-0.014 * f["happy"])
            iris = g(u, v, ex, ey, 0.022, 0.010)
            du += iris * 0.007 * f["gaze_x"]
            dv += iris * 0.004 * f["gaze_y"]
        # Fade to nothing at the edge of the warped region, so it joins the rest.
        u0, v0, u1, v1 = _REGION
        edge = np.minimum(np.minimum(u - u0, u1 - u), np.minimum(v - v0, v1 - v))
        w = np.clip(edge / 0.06, 0.0, 1.0)
        w = w * w * (3 - 2 * w)
        return du * w, dv * w

    def expression(self, target: dict, t: float) -> dict:
        """Smooth the expression towards `target` (each 0..1, wide -1..1)."""
        last = getattr(self, "_last_t", t)
        self._last_t = t
        dt = max(0.0, min(0.1, t - last))
        cur = getattr(self, "_expr", None)
        if cur is None:
            cur = self._expr = {k: 0.0 for k in target}
        for k, v in target.items():
            # Faces move fast (jaw, lids) but moods settle slowly.
            tau = 0.05 if k in ("jaw", "blink", "wide", "gaze_x", "gaze_y") else 0.35
            a = 1.0 - math.exp(-dt / tau) if dt > 0 else 1.0
            cur[k] = cur.get(k, 0.0) + (v - cur.get(k, 0.0)) * a
        return cur

    def _warped(self, img: QImage, f: dict) -> QImage:
        """The picture with the expression applied (in picture pixels)."""
        if max(abs(f[k]) for k in f) < 0.01:
            return img
        iw, ih = img.width(), img.height()
        nx, ny = _GRID
        u0, v0, u1, v1 = _REGION
        gu, gv = np.meshgrid(np.linspace(u0, u1, nx + 1), np.linspace(v0, v1, ny + 1))
        du, dv = self._field(gu, gv, f)
        sx, sy = gu * iw, gv * ih
        dx, dy = (gu + du) * iw, (gv + dv) * ih
        buf = getattr(self, "_buf", None)
        if buf is None or buf.size() != img.size():
            buf = self._buf = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
        buf.fill(0)
        bp = QPainter(buf)
        try:
            bp.drawImage(0, 0, img)
            # Replace (not blend) inside the region: each cell lands exactly once.
            bp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            bp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            sxl, syl, dxl, dyl = sx.tolist(), sy.tolist(), dx.tolist(), dy.tolist()
            tr = QTransform()
            for j in range(ny):
                for i in range(nx):
                    src = QPolygonF([QPointF(sxl[j][i], syl[j][i]), QPointF(sxl[j][i + 1], syl[j][i + 1]),
                                     QPointF(sxl[j + 1][i + 1], syl[j + 1][i + 1]),
                                     QPointF(sxl[j + 1][i], syl[j + 1][i])])
                    dst = QPolygonF([QPointF(dxl[j][i], dyl[j][i]), QPointF(dxl[j][i + 1], dyl[j][i + 1]),
                                     QPointF(dxl[j + 1][i + 1], dyl[j + 1][i + 1]),
                                     QPointF(dxl[j + 1][i], dyl[j + 1][i])])
                    if not QTransform.quadToQuad(src, dst, tr):
                        continue
                    bp.setTransform(tr)
                    bp.setClipRect(src.boundingRect().adjusted(-0.5, -0.5, 0.5, 0.5))
                    bp.drawImage(QPointF(0, 0), img)
                    bp.setClipping(False)
            bp.resetTransform()
            bp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            self._paint_mouth(bp, iw, ih, f)
        finally:
            bp.end()
        return buf

    def _paint_mouth(self, p: QPainter, iw: int, ih: int, f: dict) -> None:
        """The opening between the lips, shaped by the displaced lip corners."""
        mx, my, mw = self.layout["mouth"]
        pts = {}
        for name, (u, v) in {"l": (mx - mw / 2, my), "r": (mx + mw / 2, my),
                             "up": (mx, my - 0.012), "lo": (mx, my + 0.018)}.items():
            uu, vv = np.array([u]), np.array([v])
            du, dv = self._field(uu, vv, f)
            pts[name] = QPointF((u + du[0]) * iw, (v + dv[0]) * ih)
        gap = pts["lo"].y() - pts["up"].y() - (0.030 * ih)
        if gap < 1.0:
            return
        l, r = pts["l"], pts["r"]
        top_y = (l.y() + r.y()) / 2 - gap * 0.15
        path = QPainterPath(l)
        path.quadTo(QPointF((l.x() + r.x()) / 2, top_y - gap * 0.25), r)
        path.quadTo(QPointF((l.x() + r.x()) / 2, top_y + gap * 1.6), l)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 10, 24, 225))
        p.drawPath(path)
        teeth = QRectF((l.x() * 0.7 + r.x() * 0.3), top_y - gap * 0.05,
                       (r.x() - l.x()) * 0.4, gap * 0.28)
        p.setBrush(QColor(210, 245, 255, 120))
        p.drawRoundedRect(teeth, 2, 2)

    # ── frame ───────────────────────────────────────────────────────────────
    def paint(self, p: QPainter, cx: float, top: float, height: float, primary: QColor,
              accent: QColor, t: float, mouth: float, amp: float, blink: float,
              face: dict | None = None) -> None:
        """`face` carries the expression targets (see EMOTIONS plus jaw, wide,
        brow, blink, gaze_x, gaze_y); without it only the jaw and blink move."""
        target = {"jaw": max(0.0, min(1.0, mouth)), "wide": 0.0, "brow": 0.0,
                  "blink": max(0.0, min(1.0, blink)), "gaze_x": 0.0, "gaze_y": 0.0}
        target.update({k: 0.0 for k in EMOTIONS})
        if face:
            target.update({k: float(v) for k, v in face.items() if k in target})
        f = self.expression(target, t)
        img = self._warped(self._image_for(primary), f)
        h = height * (1.0 + 0.006 * math.sin(t * 1.3))          # breathing
        w = h * self.aspect
        top += 2.0 * math.sin(t * 0.9)                         # float
        left = cx - w / 2

        ar = h * 0.75
        grad = QRadialGradient(cx, top + h * 0.45, ar)
        grad.setColorAt(0.0, QColor(primary.red(), primary.green(), primary.blue(), int(45 + 55 * amp)))
        grad.setColorAt(1.0, QColor(primary.red(), primary.green(), primary.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QRectF(cx - ar, top + h * 0.45 - ar, ar * 2, ar * 2))

        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QRectF(left, top, w, h), img)
        p.restore()

        # Glowing eyes that follow the gaze; a blink dims them, joy brightens.
        k = max(0.0, 1.0 - f["blink"] * 1.1) * (1.0 + 0.25 * f["happy"] + 0.3 * f["surprised"])
        rad = w * 0.035 * (1.0 + 0.25 * f["surprised"] - 0.15 * f["serious"])
        for ex, ey in self.layout["eyes"]:
            c = QPointF(left + (ex + 0.007 * f["gaze_x"]) * w, top + (ey + 0.004 * f["gaze_y"]) * h)
            # Soft enough that the drawn iris still shows through the glow.
            g = QRadialGradient(c, rad * 2.0)
            g.setColorAt(0.0, QColor(235, 252, 255, int(min(255, 125 * k))))
            g.setColorAt(0.35, QColor(accent.red(), accent.green(), accent.blue(), int(min(255, 80 * k))))
            g.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            p.setBrush(QBrush(g))
            p.drawEllipse(c, rad * 2.0, rad * 2.0)

        # One sweep of light down the face.
        sy = top + ((t * 0.16) % 1.0) * h
        p.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 55), 2.0))
        p.drawLine(QPointF(left + w * 0.15, sy), QPointF(left + w * 0.85, sy))
