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
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QRadialGradient

FACE_DIR = Path(__file__).resolve().parent.parent / "config"
FACE_NAMES = ("hologram_face.png", "hologram_face.webp", "hologram_face.jpg",
              "hologram_face.jpeg")
_MAX_H = 760                       # processed picture height in pixels
_DEFAULT_LAYOUT = {"eyes": [[0.38, 0.475], [0.61, 0.475]], "mouth": [0.50, 0.70, 0.19]}


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

    def paint(self, p: QPainter, cx: float, top: float, height: float, primary: QColor,
              accent: QColor, t: float, mouth: float, amp: float, blink: float) -> None:
        img = self._image_for(primary)
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
        mx, my, mw = self.layout["mouth"]
        drop = h * 0.028 * max(0.0, min(1.0, mouth))
        iw, ih = img.width(), img.height()
        split = my * ih
        # Above the lips: as drawn. Below: stretched down by the jaw drop, so the
        # chin and neck follow without a seam.
        p.drawImage(QRectF(left, top, w, h * my), img, QRectF(0, 0, iw, split))
        p.drawImage(QRectF(left, top + h * my, w, h * (1 - my) + drop), img,
                    QRectF(0, split, iw, ih - split))
        if drop > 0.6:
            mouth_rect = QRectF(left + w * (mx - mw / 2) + w * mw * 0.12, top + h * my - drop * 0.2,
                                w * mw * 0.76, drop * 1.3)
            p.setBrush(QColor(0, 12, 26, 210))
            p.drawEllipse(mouth_rect)
            p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), int(60 + 90 * amp)))
            p.drawEllipse(mouth_rect.adjusted(mouth_rect.width() * 0.25, mouth_rect.height() * 0.35,
                                              -mouth_rect.width() * 0.25, -mouth_rect.height() * 0.1))
        p.restore()

        # Glowing eyes; a blink dims them.
        k = max(0.0, 1.0 - blink)
        rad = w * 0.035
        for ex, ey in self.layout["eyes"]:
            c = QPointF(left + ex * w, top + ey * h)
            g = QRadialGradient(c, rad * 2.6)
            g.setColorAt(0.0, QColor(235, 252, 255, int(200 * k)))
            g.setColorAt(0.3, QColor(accent.red(), accent.green(), accent.blue(), int(150 * k)))
            g.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            p.setBrush(QBrush(g))
            p.drawEllipse(c, rad * 2.6, rad * 2.6)

        # One sweep of light down the face.
        sy = top + ((t * 0.16) % 1.0) * h
        p.setPen(QPen(QColor(primary.red(), primary.green(), primary.blue(), 55), 2.0))
        p.drawLine(QPointF(left + w * 0.15, sy), QPointF(left + w * 0.85, sy))
