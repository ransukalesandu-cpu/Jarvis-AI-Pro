"""The "image" look: the owner's own face picture shown as a cyan hologram.

A mesh can only approximate a drawing; this shows the picture itself, so the
face is exactly the one supplied. The picture lives on the owner's machine,
not in the repository:

    JarvisAI/config/hologram_face.png   (or .webp / .jpg)

Optional ``hologram_face.json`` beside it gives the eye and mouth positions as
fractions of the picture (defaults suit a centred head-and-neck portrait):

    {"eyes": [[0.38, 0.475], [0.61, 0.475]], "mouth": [0.50, 0.70, 0.19]}

Processing (once, at load) turns the picture into a hologram rather than
tinting it: the background is cut away (flooding in from the border over
light, grey pixels, so a baked-in checkerboard goes too and the drawing's
outline stops it); the drawing's ink becomes glowing line-art (pixels darker
than their surroundings), the shading becomes a dim translucent volume, the
silhouette gets a rim of light, and a relief (a dome that starts flat at the
outline, plus nose, brow, lips and chin forward and eye sockets back) makes
the picture a 3D head: it turns, nods and tilts with the avatar's head
motion and is projected with mild perspective, far parts drawn first. Per frame it is composed
additively, so it emits light instead of covering the HUD: bloom, scanlines,
a sweeping scan band, flicker, the odd glitch slice, rising motes and a
projector base with its beam. A warp grid over the whole picture carries the
lip sync and the emotions; the mouth opens into a real hole.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPolygonF, QRadialGradient, QTransform)

FACE_DIR = Path(__file__).resolve().parent.parent / "config"
FACE_NAMES = ("hologram_face.png", "hologram_face.webp", "hologram_face.jpg",
              "hologram_face.jpeg")
_MAX_H = 760                       # processed picture height in pixels
_DEFAULT_LAYOUT = {"eyes": [[0.38, 0.475], [0.61, 0.475]], "mouth": [0.50, 0.70, 0.19]}
EMOTIONS = ("happy", "sad", "serious", "surprised", "curious")
_DIRECT = frozenset({"jaw", "wide", "blink", "gaze_x", "gaze_y", "yaw", "pitch", "roll"})
_MARGIN = 0.12                     # room round the picture for the turned head
_COLS = 18                         # warp cells across; rows are denser over the face
_PAD = 0.05                        # empty margin round the cut-out, for glow and sway
_LINE = np.array([225.0, 255.0, 255.0], dtype=np.float32)    # the glowing line-art


def _box(a: np.ndarray, r: int) -> np.ndarray:
    """Mean over a (2r+1)^2 box, edges clamped. Cheap, separable, numpy only."""
    if r <= 0:
        return a
    k = 2 * r + 1
    p = np.pad(a, r, mode="edge").astype(np.float32)
    c = np.cumsum(p, axis=0)
    c = np.vstack([c[k - 1:k], c[k:] - c[:-k]])
    c = np.cumsum(c, axis=1)
    c = np.hstack([c[:, k - 1:k], c[:, k:] - c[:, :-k]])
    return c / (k * k)


def _convex(q) -> bool:
    """True when quad q (four (x, y) corners in order) is convex, wound
    clockwise on screen and not degenerate."""
    sign = 0.0
    for k in range(4):
        ax, ay = q[k]
        bx, by = q[(k + 1) % 4]
        cx, cy = q[(k + 2) % 4]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) < 0.05:
            return False
        if sign == 0.0:
            sign = cross
        elif (cross > 0) != (sign > 0):
            return False
    return sign > 0


def _draw_triangle(p: QPainter, img: QImage, src, dst) -> None:
    """Map one triangle of `img` onto `dst` with an affine transform."""
    area = ((dst[1][0] - dst[0][0]) * (dst[2][1] - dst[0][1])
            - (dst[2][0] - dst[0][0]) * (dst[1][1] - dst[0][1]))
    if area <= 0.3:                       # facing away or edge-on
        return
    a = np.array([[x, y, 1.0] for x, y in src])
    try:
        mx = np.linalg.solve(a, np.array([d[0] for d in dst]))
        my = np.linalg.solve(a, np.array([d[1] for d in dst]))
    except np.linalg.LinAlgError:
        return
    p.setTransform(QTransform(mx[0], my[0], mx[1], my[1], mx[2], my[2]))
    path = QPainterPath(QPointF(*src[0]))
    path.lineTo(QPointF(*src[1]))
    path.lineTo(QPointF(*src[2]))
    path.closeSubpath()
    p.setClipPath(path)
    p.drawImage(QPointF(0, 0), img)
    p.setClipping(False)


def _rows() -> np.ndarray:
    """Warp grid rows: coarse over the hair and neck, fine from brows to chin."""
    return np.unique(np.concatenate([np.linspace(0.0, 0.40, 5), np.linspace(0.40, 0.86, 22),
                                     np.linspace(0.86, 1.0, 3)]))


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
    bloom = True          # glow pass and effects; the lite performance tier turns them off

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
        # Crop to the face with a margin, so glow and sway have room.
        pad = int(_PAD * (y1 - y0))
        rgba = np.pad(rgba[y0:y1, x0:x1], ((pad, pad), (pad, pad), (0, 0)), mode="edge")
        mask = np.pad(mask[y0:y1, x0:x1], pad)
        H, W = mask.shape
        self._crop = ((x0 - pad) / img.width(), (y0 - pad) / img.height(),
                      (x1 + pad) / img.width(), (y1 + pad) / img.height())
        lum = (rgba[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114],
                                                           dtype=np.float32)) / 255.0
        lum = np.clip(lum, 0, 1)
        s = max(1, H // 380)                    # feature sizes scale with the picture
        # Ink: darker than its neighbourhood. That is every drawn line and
        # hatch, but not a flat dark area, which would glow as a blob.
        self._ink = np.clip((_box(lum, 3 * s) - lum) * 5.5, 0, 1) * mask
        self._rim = np.clip((mask - _box(mask, 5 * s)) * 3.0, 0, 1)
        self._lum = lum ** 0.8 * mask
        self._mask = mask
        depth = _box(_box(mask, 22 * s), 22 * s)
        self._depth = (depth / max(1e-6, float(depth.max()))).astype(np.float32)
        self._alpha = mask
        self._tint_key = None
        self._tinted: QImage | None = None
        self.aspect = W / H
        self.layout = self._load_layout(path)
        self._rows = _rows()
        self._relief = self._build_relief()
        self._view = (0.0, 0.0, 0.0)
        self._out_size = (int(W * (1 + 2 * _MARGIN)), int(H * (1 + 2 * _MARGIN)))

    def _build_relief(self) -> np.ndarray:
        """Depth of the face, in picture pixels towards the viewer.

        A rounded dome from the silhouette (so the hair, ears and jaw curve
        away) plus the anatomy that sticks out or sinks in: the nose and its
        bridge, the brow ridge, the lips and chin forward, the eye sockets
        back. Turning this surface is what makes the picture a 3D head.
        """
        H, W = self._depth.shape
        u, v = np.meshgrid(np.linspace(0, 1, W, dtype=np.float32),
                           np.linspace(0, 1, H, dtype=np.float32))
        g = self._g
        mx, my, _ = self.layout["mouth"]
        eyes = self.layout["eyes"]
        ey = sum(e[1] for e in eyes) / len(eyes)
        tip_v = ey + 0.62 * (my - ey)
        # The smoothed silhouette is ~0.5 right on the outline: start the dome
        # there, so the edge of the head lies flat on the picture plane and
        # only the inside bulges (no cliff at the outline to tear when turned).
        rel = 0.85 * np.clip((self._depth - 0.5) / 0.5, 0, 1) ** 0.6
        rel += 0.20 * g(u, v, mx, tip_v, 0.045, 0.055)
        bridge = np.exp(-((u - mx) / 0.030) ** 2) * np.clip((v - ey + 0.03) / (tip_v - ey + 0.03), 0, 1)
        rel += 0.10 * bridge * (v < tip_v + 0.02)
        for ex, e_y in eyes:
            rel += 0.06 * g(u, v, ex, e_y - 0.060, 0.065, 0.025)
            rel -= 0.07 * g(u, v, ex, e_y, 0.045, 0.026)
        rel += 0.05 * g(u, v, mx, my, 0.080, 0.030)
        rel += 0.06 * g(u, v, mx, my + 0.12, 0.090, 0.050)
        rel *= np.clip((self._depth - 0.5) / 0.15, 0, 1)
        return (rel * 0.42 * W).astype(np.float32)

    def _project(self, u2, v2, u0, v0):
        """Picture points (displaced u2, v2; depth taken at u0, v0) to the
        output buffer, through the current head turn."""
        H, W = self._depth.shape
        yaw, pitch, roll = self._view
        X = (np.asarray(u2) - 0.5) * W
        Y = (np.asarray(v2) - 0.5) * H
        Z = self._relief[np.clip((np.asarray(v0) * (H - 1)).astype(int), 0, H - 1),
                         np.clip((np.asarray(u0) * (W - 1)).astype(int), 0, W - 1)]
        cy_, sy_ = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cr, sr = math.cos(roll), math.sin(roll)
        x1 = X * cy_ + Z * sy_
        z1 = -X * sy_ + Z * cy_
        y2 = Y * cp - z1 * sp
        z2 = Y * sp + z1 * cp
        x3 = x1 * cr - y2 * sr
        y3 = x1 * sr + y2 * cr
        # Mild perspective on the change in depth only, so the face at rest is
        # exactly the picture.
        d = 2.4 * H
        k = d / np.maximum(d - (z2 - Z), d * 0.5)
        ow, oh = self._out_size
        return ow / 2 + x3 * k, oh / 2 + y3 * k, z2

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
        """The hologram itself (premultiplied, meant to be drawn additively)."""
        # Quantise so slow mood fades re-tint a handful of times, not every frame.
        key = (primary.red() // 12, primary.green() // 12, primary.blue() // 12)
        if key != self._tint_key or self._tinted is None:
            col = np.array([primary.red(), primary.green(), primary.blue()], dtype=np.float32)
            lum = self._lum[..., None]
            body_a = self._mask * (0.08 + 0.30 * self._lum)        # dim volume
            line_a = self._ink * 0.85                               # glowing line-art
            line_rgb = _LINE * 0.5 + col * 0.5                      # cyan, not white
            rim_a = self._rim * 0.80                                # silhouette light
            rgb = (col * (0.35 + 0.65 * lum)) * body_a[..., None]
            rgb += line_rgb * line_a[..., None]
            rgb += (col * 0.6 + _LINE * 0.4) * rim_a[..., None]
            a = np.clip(body_a + line_a + rim_a, 0, 1)
            rgb = np.minimum(rgb, a[..., None] * 255.0)
            a[::3, :] *= 0.45                                       # scanlines
            rgb[::3, :] *= 0.45
            out = np.empty(a.shape + (4,), dtype=np.uint8)
            out[..., :3] = np.clip(rgb, 0, 255)
            out[..., 3] = np.clip(a * 255, 0, 255)
            h, w = a.shape
            data = np.ascontiguousarray(out)
            img = QImage(data.data, w, h, w * 4, QImage.Format.Format_RGBA8888_Premultiplied).copy()
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
        spread = max(0.0, f["wide"])            # /i/ /e/: lips stretched wide and flat
        round_ = max(0.0, -f["wide"])           # /o/ /u/: lips drawn in, opening taller
        g = self._g
        # Jaw and lips. The lower lip rides the jaw; the upper lip lifts a
        # little on open vowels and more when the lips round.
        dv += 0.050 * jaw * g(u, v, mx, my + 0.12, 0.24, 0.13)
        dv += (0.028 + 0.010 * round_) * jaw * g(u, v, mx, my + 0.018, 0.08, 0.022)
        dv -= (0.006 + 0.006 * round_) * jaw * g(u, v, mx, my - 0.012, 0.08, 0.018)
        for side in (-1.0, 1.0):
            cu = mx + side * mw / 2
            corner = g(u, v, cu, my, 0.040, 0.030)
            du += side * corner * (0.012 * f["wide"] + 0.014 * f["happy"] - 0.004 * f["sad"]
                                   - 0.006 * jaw)
            dv += corner * (-0.026 * f["happy"] + 0.018 * f["sad"] + 0.004 * f["serious"]
                            + 0.008 * jaw - 0.003 * spread)
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
            lid_up = g(u, v, ex, ey - 0.014, 0.040, 0.020)
            lid_lo = g(u, v, ex, ey + 0.016, 0.035, 0.012)
            dv += lid_up * (0.026 * f["blink"] - 0.006 * f["surprised"])
            dv += lid_lo * (-0.004 * f["blink"] - 0.006 * f["happy"])
            dv += g(u, v, ex + side * 0.01, ey + 0.10, 0.06, 0.05) * (-0.014 * f["happy"])
            iris = g(u, v, ex, ey, 0.022, 0.010)
            du += iris * 0.007 * f["gaze_x"]
            dv += iris * 0.004 * f["gaze_y"]
        # Pin the picture's border, so the cut-out never tears at the edge.
        edge = np.minimum(np.minimum(u, 1.0 - u), np.minimum(v, 1.0 - v))
        w = np.clip(edge / 0.04, 0.0, 1.0)
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
            if k in _DIRECT:
                # Already timed and smoothed by the avatar against the audio
                # being played; any more smoothing here would make the lips lag.
                cur[k] = v
                continue
            a = 1.0 - math.exp(-dt / 0.35) if dt > 0 else 1.0   # moods settle slowly
            cur[k] = cur.get(k, 0.0) + (v - cur.get(k, 0.0)) * a
        return cur

    def _warped(self, img: QImage, f: dict) -> QImage:
        """The picture as a turned 3D head with the expression applied.

        A grid over the picture: each vertex is displaced by the expression,
        lifted off the page by the relief, turned with the head and projected.
        Each cell is then re-drawn with a quad-to-quad transform, far cells
        first so the nose covers the cheek behind it.
        """
        self._view = (max(-0.6, min(0.6, f.get("yaw", 0.0))),
                      max(-0.4, min(0.4, f.get("pitch", 0.0))),
                      max(-0.3, min(0.3, f.get("roll", 0.0))))
        iw, ih = img.width(), img.height()
        nx, ny = _COLS, len(self._rows) - 1
        gu, gv = np.meshgrid(np.linspace(0.0, 1.0, nx + 1), self._rows)
        du, dv = self._field(gu, gv, f)
        sx, sy = gu * iw, gv * ih
        ex_, ey_ = (gu + du) * iw, (gv + dv) * ih
        # The expression never folds a cell over: each row stays below the one
        # above and each column right of the one before.
        for j in range(1, ey_.shape[0]):
            ey_[j] = np.maximum(ey_[j], ey_[j - 1] + 0.2 * (sy[j] - sy[j - 1]))
        for i in range(1, ex_.shape[1]):
            ex_[:, i] = np.maximum(ex_[:, i], ex_[:, i - 1] + 0.2 * (sx[:, i] - sx[:, i - 1]))
        dx, dy, dz = self._project(ex_ / iw, ey_ / ih, gu, gv)
        ow, oh = self._out_size
        buf = getattr(self, "_buf", None)
        if buf is None or (buf.width(), buf.height()) != (ow, oh):
            buf = self._buf = QImage(ow, oh, QImage.Format.Format_ARGB32_Premultiplied)
        buf.fill(0)
        cz = (dz[:-1, :-1] + dz[1:, :-1] + dz[:-1, 1:] + dz[1:, 1:]).ravel()
        order = np.argsort(cz, kind="stable").tolist()           # far cells first
        bp = QPainter(buf)
        try:
            bp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            bp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            sxl, syl, dxl, dyl = sx.tolist(), sy.tolist(), dx.tolist(), dy.tolist()
            tr = QTransform()
            for c in order:
                j, i = divmod(c, nx)
                q = ((dxl[j][i], dyl[j][i]), (dxl[j][i + 1], dyl[j][i + 1]),
                     (dxl[j + 1][i + 1], dyl[j + 1][i + 1]), (dxl[j + 1][i], dyl[j + 1][i]))
                # A cell turned past edge-on faces away, and a twisted one would
                # project to infinity: skip both (they sit on the silhouette).
                sq = ((sxl[j][i], syl[j][i]), (sxl[j][i + 1], syl[j][i + 1]),
                      (sxl[j + 1][i + 1], syl[j + 1][i + 1]), (sxl[j + 1][i], syl[j + 1][i]))
                if not _convex(q):
                    # Strong relief inside the cell (the nose, the outline):
                    # draw it as two flat triangles instead of one bent quad.
                    for a, b, c in ((0, 1, 2), (0, 2, 3)):
                        _draw_triangle(bp, img, (sq[a], sq[b], sq[c]), (q[a], q[b], q[c]))
                    continue
                src = QPolygonF([QPointF(sxl[j][i], syl[j][i]), QPointF(sxl[j][i + 1], syl[j][i + 1]),
                                 QPointF(sxl[j + 1][i + 1], syl[j + 1][i + 1]),
                                 QPointF(sxl[j + 1][i], syl[j + 1][i])])
                dst = QPolygonF([QPointF(x, y) for x, y in q])
                if not QTransform.quadToQuad(src, dst, tr):
                    continue
                if not tr.isAffine():
                    ws = [tr.m13() * x + tr.m23() * y + tr.m33()
                          for x, y in ((sxl[j][i], syl[j][i]), (sxl[j + 1][i + 1], syl[j + 1][i + 1]),
                                       (sxl[j][i + 1], syl[j][i + 1]), (sxl[j + 1][i], syl[j + 1][i]))]
                    if min(ws) <= 0.0 or max(ws) > 4.0 * min(ws):
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

    def to_buffer(self, u: float, v: float, f: dict) -> tuple[float, float]:
        """Where picture point (u, v) lands in the output buffer this frame."""
        du, dv = self._field(np.array([u]), np.array([v]), f)
        x, y, _ = self._project(np.array([u + du[0]]), np.array([v + dv[0]]),
                                np.array([u]), np.array([v]))
        return float(x[0]), float(y[0])

    def _paint_mouth(self, p: QPainter, iw: int, ih: int, f: dict) -> None:
        """The opening between the lips, shaped by the displaced lip corners."""
        mx, my, mw = self.layout["mouth"]
        pts = {}
        for name, (u, v) in {"l": (mx - mw / 2, my), "r": (mx + mw / 2, my),
                             "up": (mx, my - 0.012), "lo": (mx, my + 0.018)}.items():
            pts[name] = QPointF(*self.to_buffer(u, v, f))
        rest = self._project(np.array([mx, mx]), np.array([my - 0.012, my + 0.018]),
                             np.array([mx, mx]), np.array([my - 0.012, my + 0.018]))[1]
        gap = pts["lo"].y() - pts["up"].y() - float(rest[1] - rest[0])
        if gap < 1.0:
            return
        l, r = pts["l"], pts["r"]
        top_y = (l.y() + r.y()) / 2 - gap * 0.15
        path = QPainterPath()
        spread = max(0.0, f["wide"])
        round_ = max(0.0, -f["wide"])
        # Rounded lips leave a taller, narrower hole; spread lips a flat slot.
        depth = gap * (1.6 + 0.6 * round_ - 0.4 * spread)
        inset = (r.x() - l.x()) * 0.14 * round_
        l, r = QPointF(l.x() + inset, l.y()), QPointF(r.x() - inset, r.y())
        path.moveTo(l)
        path.quadTo(QPointF((l.x() + r.x()) / 2, top_y - gap * 0.25), r)
        path.quadTo(QPointF((l.x() + r.x()) / 2, top_y + depth), l)
        # A hologram's mouth is an absence of light: cut a hole, then outline
        # the lips and the upper teeth in light.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 255))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        p.drawPath(path)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(200, 250, 255, 170), max(1.0, ih / 500)))
        p.drawPath(path)
        tw = (r.x() - l.x()) * (0.36 + 0.24 * spread - 0.16 * round_)
        teeth = QRectF((l.x() + r.x()) / 2 - tw / 2, top_y - gap * 0.05, tw, gap * 0.26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(170, 230, 245, int(70 + 60 * spread)))
        p.drawRoundedRect(teeth, 2, 2)

    # ── frame ───────────────────────────────────────────────────────────────
    def paint(self, p: QPainter, cx: float, top: float, height: float, primary: QColor,
              accent: QColor, t: float, mouth: float, amp: float, blink: float,
              face: dict | None = None) -> None:
        """`face` carries the expression targets (see EMOTIONS plus jaw, wide,
        brow, blink, gaze_x, gaze_y); without it only the jaw and blink move."""
        target = {"jaw": max(0.0, min(1.0, mouth)), "wide": 0.0, "brow": 0.0,
                  "blink": max(0.0, min(1.0, blink)), "gaze_x": 0.0, "gaze_y": 0.0,
                  # Without the avatar's head motion, a slow turn of its own.
                  "yaw": 0.26 * math.sin(t * 0.31) + 0.09 * math.sin(t * 0.73 + 1.3),
                  "pitch": 0.05 * math.sin(t * 0.23 + 0.7), "roll": 0.0}
        target.update({k: 0.0 for k in EMOTIONS})
        if face:
            target.update({k: float(v) for k, v in face.items() if k in target})
        f = self.expression(target, t)
        img = self._warped(self._image_for(primary), f)
        h = height * (1.0 + 0.006 * math.sin(t * 1.3))          # breathing
        w = h * self.aspect
        top += 2.0 * math.sin(t * 0.9)                         # float
        left = cx - w / 2
        P = (primary.red(), primary.green(), primary.blue())

        # Projector: a base ring under the neck and a faint beam up through it.
        base_y = top + h * (1.0 - _PAD * 0.6)
        bw, bh = w * 0.62, w * 0.09
        beam = QLinearGradient(0, base_y, 0, top + h * 0.05)
        beam.setColorAt(0.0, QColor(*P, int(70 + 50 * amp)))
        beam.setColorAt(1.0, QColor(*P, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(beam))
        p.drawPolygon(QPolygonF([QPointF(cx - bw * 0.42, base_y), QPointF(cx + bw * 0.42, base_y),
                                 QPointF(cx + w * 0.55, top + h * 0.05),
                                 QPointF(cx - w * 0.55, top + h * 0.05)]))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k, a in ((1.0, 170), (0.78, 110), (0.55, 70)):
            p.setPen(QPen(QColor(*P, a), 1.6))
            p.drawEllipse(QPointF(cx, base_y), bw * k / 2, bh * k / 2)

        ar = h * 0.72
        grad = QRadialGradient(cx, top + h * 0.45, ar)
        grad.setColorAt(0.0, QColor(*P, int(30 + 45 * amp)))
        grad.setColorAt(1.0, QColor(*P, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QRectF(cx - ar, top + h * 0.45 - ar, ar * 2, ar * 2))

        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        # Flicker: a hologram is never perfectly steady.
        flicker = 0.90 + 0.06 * math.sin(t * 13.0) * math.sin(t * 7.3) + 0.04 * amp
        p.setOpacity(max(0.0, min(1.0, flicker)))
        # The buffer holds the turned head with a margin all round.
        target_rect = QRectF(left - w * _MARGIN, top - h * _MARGIN,
                             w * (1 + 2 * _MARGIN), h * (1 + 2 * _MARGIN))
        bx = target_rect.width() / img.width()
        by = target_rect.height() / img.height()
        p.drawImage(target_rect, img)
        if not self.bloom:                      # the lite performance tier
            p.restore()
            return
        bloom = img.scaled(max(2, img.width() // 6), max(2, img.height() // 6),
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        p.setOpacity(0.55 + 0.25 * amp)
        p.drawImage(target_rect, bloom)
        # Now and then a slice of the picture jumps sideways for a moment.
        slot = int(t / 3.7)
        if (t / 3.7) - slot < 0.035:
            rnd = (slot * 2654435761) % 1000 / 1000.0
            band = 0.15 + 0.7 * rnd
            bh_ = 0.03 + 0.04 * ((slot * 40503) % 100 / 100.0)
            src = QRectF(0, band * img.height(), img.width(), bh_ * img.height())
            off = (rnd - 0.5) * w * 0.06
            p.setOpacity(0.8)
            tr_ = target_rect
            p.drawImage(QRectF(tr_.left() + off, tr_.top() + band * tr_.height(), tr_.width(),
                               bh_ * tr_.height()), img, src)
        p.setOpacity(1.0)

        # Glowing eyes that follow the gaze; a blink dims them, joy brightens.
        k = max(0.0, 1.0 - f["blink"] * 1.1) * (1.0 + 0.25 * f["happy"] + 0.3 * f["surprised"])
        rad = w * 0.030 * (1.0 + 0.25 * f["surprised"] - 0.15 * f["serious"])
        for ex, ey in self.layout["eyes"]:
            ux, uy = self.to_buffer(ex + 0.007 * f["gaze_x"], ey + 0.004 * f["gaze_y"], f)
            c = QPointF(target_rect.left() + ux * bx, target_rect.top() + uy * by)
            g = QRadialGradient(c, rad * 2.2)
            g.setColorAt(0.0, QColor(235, 252, 255, int(min(255, 150 * k))))
            g.setColorAt(0.35, QColor(accent.red(), accent.green(), accent.blue(), int(min(255, 90 * k))))
            g.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            p.setBrush(QBrush(g))
            p.drawEllipse(c, rad * 2.2, rad * 2.2)

        # A band of light sweeping down the face.
        sy = top + ((t * 0.16) % 1.0) * h
        sweep = QLinearGradient(0, sy - h * 0.03, 0, sy + h * 0.03)
        sweep.setColorAt(0.0, QColor(*P, 0))
        sweep.setColorAt(0.5, QColor(*P, 60))
        sweep.setColorAt(1.0, QColor(*P, 0))
        p.setBrush(QBrush(sweep))
        p.drawRect(QRectF(left + w * 0.1, sy - h * 0.03, w * 0.8, h * 0.06))

        # Motes of light drifting up through the beam.
        p.setBrush(QColor(*P, 150))
        for i in range(36):
            a = (i * 0.61803) % 1.0
            b = (i * 0.38197 + 0.13) % 1.0
            rise = (t * (0.05 + 0.06 * b) + a) % 1.0
            x = cx + (a - 0.5) * w * (0.5 + 0.5 * rise) + math.sin(t * 0.8 + i) * w * 0.01
            y = base_y - rise * h * 0.95
            r_ = 1.0 + 1.4 * b
            p.setOpacity(max(0.0, 1.0 - rise) * 0.8)
            p.drawEllipse(QPointF(x, y), r_, r_)
        p.restore()
