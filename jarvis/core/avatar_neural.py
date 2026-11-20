"""The "neural" look of the picture hologram: a photo-real blue head with glowing veins.

It is the image look (core/avatar_image.py: the owner's picture turned into a 3D,
lip-synced, expressive head) with a different skin:

* the picture keeps its photographic shading, re-lit in electric blue (deep navy
  shadows, pale cyan highlights) instead of being reduced to line-art;
* a network of glowing veins is grown over the neck, jaw, cheeks and temples,
  baked into the picture so it turns and talks with the head, and light pulses
  run up along it (faster when JARVIS speaks);
* under the neck sits a glowing disc, where the energy strands of the stage
  (ui/hologram/neural_stage.py) leave for the orb.

Everything is generated once from the picture (numpy + QPainter, no new
dependency); per frame only a few dozen pulse points are projected.
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

NEURAL_PRIMARY = QColor(40, 125, 255)       # electric blue
NEURAL_ACCENT = QColor(170, 225, 255)
_SHADOW = np.array([6.0, 24.0, 90.0], dtype=np.float32)       # deep navy
_MID = np.array([55.0, 140.0, 255.0], dtype=np.float32)
_HIGH = np.array([215.0, 242.0, 255.0], dtype=np.float32)     # pale cyan-white
_VEIN = np.array([150.0, 225.0, 255.0], dtype=np.float32)


def border_is_dark(rgba: np.ndarray) -> bool:
    """True when the picture sits on a dark background (most border pixels dark)."""
    rgb = rgba[..., :3].astype(np.float32)
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    return float(np.median(edge.max(axis=1))) < 90.0


def cut_dark_background(rgba: np.ndarray) -> np.ndarray:
    """Foreground mask for a picture on a dark backdrop: flood in from the border
    across pixels that are dark (or close to the border's own colour)."""
    rgb = rgba[..., :3].astype(np.float32)
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    edge = np.concatenate([lum[0], lum[-1], lum[:, 0], lum[:, -1]])
    floor = float(np.percentile(edge, 90))
    open_ = (lum < max(38.0, floor + 18.0)) | (rgba[..., 3] < 20)
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
    fg = largest_region(~bg).astype(np.float32)
    # Fill pin-holes (dark pupils, nostrils) that are not connected to the border:
    # they are already foreground because the flood never reached them.
    soft = fg.copy()
    soft[1:-1, 1:-1] = (fg[1:-1, 1:-1] * 4 + fg[:-2, 1:-1] + fg[2:, 1:-1] + fg[1:-1, :-2] + fg[1:-1, 2:]) / 8.0
    return soft


def largest_region(fg: np.ndarray) -> np.ndarray:
    """Keep only the connected region that holds the most foreground (drops stray specks)."""
    if not fg.any():
        return fg
    rows, cols = np.nonzero(fg)
    # Seed: the foreground pixel nearest the foreground's centre of mass.
    cy, cx = rows.mean(), cols.mean()
    k = int(np.argmin((rows - cy) ** 2 + (cols - cx) ** 2))
    region = np.zeros_like(fg)
    region[rows[k], cols[k]] = True
    while True:
        grown = region.copy()
        grown[1:, :] |= region[:-1, :]
        grown[:-1, :] |= region[1:, :]
        grown[:, 1:] |= region[:, :-1]
        grown[:, :-1] |= region[:, 1:]
        grown &= fg
        if (grown == region).all():
            return region
        region = grown


def already_hologram(rgb: np.ndarray, mask: np.ndarray) -> bool:
    """True when the picture is itself a blue/cyan hologram (not an ordinary photo)."""
    fg = mask > 0.5
    if fg.sum() < 50:
        return False
    px = rgb[fg]
    lit = px[px.max(axis=1) > 40]
    if len(lit) < 50:
        return False
    blue_lead = float(np.mean((lit[:, 2] - lit[:, 0]) / 255.0))
    return blue_lead > 0.18


def as_drawn(rgb: np.ndarray, mask: np.ndarray, veins: np.ndarray) -> QImage:
    """The picture exactly as drawn, made additive: dark parts become see-through,
    bright parts emit (premultiplied ARGB). Optional generated veins on top."""
    rgb = np.clip(rgb + _VEIN * (veins * mask)[..., None], 0, 255)
    a = np.clip(rgb.max(axis=2) / 255.0 * 1.15, 0, 1) * mask
    a[::3, :] *= 0.80                                               # projector scanlines
    rgb[::3, :] *= 0.80
    rgb = np.minimum(rgb, a[..., None] * 255.0)
    out = np.empty(a.shape + (4,), dtype=np.uint8)
    out[..., :3] = np.clip(rgb, 0, 255)
    out[..., 3] = np.clip(a * 255, 0, 255)
    h, w = a.shape
    data = np.ascontiguousarray(out)
    img = QImage(data.data, w, h, w * 4, QImage.Format.Format_RGBA8888_Premultiplied).copy()
    return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def sparkle_points(rgb: np.ndarray, mask: np.ndarray, count: int = 110, seed: int = 11) -> np.ndarray:
    """(u, v) of bright spots in the picture (mesh nodes, highlights) that twinkle."""
    lum = rgb.max(axis=2) * (mask > 0.8)
    H, W = lum.shape
    thr = np.percentile(lum[mask > 0.8], 96) if (mask > 0.8).any() else 255
    ys, xs = np.nonzero(lum >= thr)
    if len(xs) == 0:
        return np.zeros((0, 2), dtype=np.float32)
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(xs), size=min(count, len(xs)), replace=False)
    return np.stack([xs[pick] / (W - 1), ys[pick] / (H - 1)], axis=1).astype(np.float32)


def paint_twinkles(p: QPainter, holo, pts: np.ndarray, f: dict, rect: QRectF, bx: float, by: float,
                   t: float, amp: float) -> None:
    """Mesh nodes flaring up one after another; they move with the head and the face."""
    if len(pts) == 0:
        return
    xs, ys = holo.to_buffer_many(pts[:, 0], pts[:, 1], f)
    for i, (x, y) in enumerate(zip(xs.tolist(), ys.tolist())):
        w = math.sin(t * (1.3 + (i % 7) * 0.31) + i * 2.17)
        if w < 0.55:
            continue
        k = (w - 0.55) / 0.45 * (0.7 + 0.3 * amp)
        r = max(2, int(2 + 4 * k))
        p.setOpacity(min(1.0, k))
        p.drawImage(QPointF(rect.left() + x * bx - r, rect.top() + y * by - r), _dot(r))
    p.setOpacity(1.0)


def paint_eyes(p: QPainter, holo, f: dict, rect: QRectF, bx: float, by: float, w: float,
               accent: QColor) -> None:
    """A soft glow in each iris that follows the gaze, dims in a blink and flares in surprise."""
    k = max(0.0, 1.0 - f["blink"] * 1.15) * (0.28 + 0.2 * f.get("happy", 0) + 0.4 * f.get("surprised", 0))
    if k <= 0.02:
        return
    rad = w * 0.022 * (1.0 + 0.3 * f.get("surprised", 0) - 0.15 * f.get("serious", 0))
    for ex, ey in holo.layout["eyes"]:
        ux, uy = holo.to_buffer(ex + 0.007 * f["gaze_x"], ey + 0.004 * f["gaze_y"], f)
        c = QPointF(rect.left() + ux * bx, rect.top() + uy * by)
        g = QRadialGradient(c, rad * 2.4)
        g.setColorAt(0.0, QColor(235, 252, 255, int(min(255, 170 * k))))
        g.setColorAt(0.3, QColor(accent.red(), accent.green(), accent.blue(), int(min(255, 90 * k))))
        g.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(c, rad * 2.4, rad * 2.4)


def paint_scan_band(p: QPainter, left: float, top: float, w: float, h: float, primary: QColor, t: float) -> None:
    """A band of light sweeping down the hologram."""
    sy = top + ((t * 0.14) % 1.0) * h
    g = QLinearGradient(0, sy - h * 0.025, 0, sy + h * 0.025)
    g.setColorAt(0.0, QColor(primary.red(), primary.green(), primary.blue(), 0))
    g.setColorAt(0.5, QColor(170, 230, 255, 55))
    g.setColorAt(1.0, QColor(primary.red(), primary.green(), primary.blue(), 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawRect(QRectF(left + w * 0.12, sy - h * 0.025, w * 0.76, h * 0.05))


# ── veins ───────────────────────────────────────────────────────────────────
def grow_veins(mask: np.ndarray, layout: dict, seed: int = 7) -> list[np.ndarray]:
    """Branching vein polylines in picture fractions (u, v), grown upwards.

    Roots sit along the bottom of the neck and on the jaw line; each vein wanders
    up and out, forks now and then, and stops at the silhouette. Veins avoid the
    eyes and the lips, so the face stays readable, and thin out over the forehead.
    """
    rng = np.random.default_rng(seed)
    H, W = mask.shape
    mx, my, mw = layout["mouth"]
    eyes = layout["eyes"]
    ey = sum(e[1] for e in eyes) / len(eyes)

    def inside(u: float, v: float) -> bool:
        x, y = int(u * (W - 1)), int(v * (H - 1))
        return 0 <= x < W and 0 <= y < H and mask[y, x] > 0.6

    left_eye, right_eye = min(e[0] for e in eyes), max(e[0] for e in eyes)

    def blocked(u: float, v: float) -> bool:
        # The middle of the face (between the outer eye corners, brow to lips) stays clear.
        if left_eye - 0.03 < u < right_eye + 0.03 and ey - 0.10 < v < my + 0.03:
            return True
        for ex, e_y in eyes:
            if ((u - ex) / 0.075) ** 2 + ((v - e_y) / 0.045) ** 2 < 1.0:
                return True
        if ((u - mx) / (mw * 0.75)) ** 2 + ((v - my) / 0.045) ** 2 < 1.0:
            return True
        return v < ey - 0.20                           # leave the hair and crown alone

    # Neck: rows of the mask near the bottom give its width.
    rows = np.nonzero(mask.max(axis=1) > 0.6)[0]
    bottom = rows.max() / (H - 1) if len(rows) else 0.95
    seeds: list[tuple[float, float, float, float]] = []
    v0 = bottom - 0.015
    xs = np.nonzero(mask[int(v0 * (H - 1))] > 0.6)[0]
    if len(xs):
        left, right = xs.min() / (W - 1), xs.max() / (W - 1)
        for k in range(16):
            u = left + (right - left) * (0.06 + 0.88 * (k + rng.random() * 0.6) / 16)
            seeds.append((u, v0, -math.pi / 2 + (u - mx) * 1.4, 0.0028))
    # Jaw line and temples: shorter veins that climb the cheeks.
    for side in (-1, 1):
        for k in range(4):
            u = mx + side * (mw * 0.9 + 0.05 * k)
            v = my + 0.11 - 0.02 * k
            seeds.append((u, v, -math.pi / 2 + side * 0.5, 0.0022))
        ex = eyes[0][0] if side < 0 else eyes[-1][0]
        seeds.append((ex + side * 0.11, ey - 0.02, -math.pi / 2 - side * 0.3, 0.0018))

    veins: list[np.ndarray] = []
    stack = [(u, v, a, w, 0) for u, v, a, w in seeds]
    while stack and len(veins) < 140:
        u, v, a, width, depth = stack.pop()
        if not inside(u, v):
            continue
        pts = [(u, v, width)]
        length = 0.0
        limit = (0.45 if depth == 0 else 0.22) * (0.6 + 0.6 * rng.random())
        while length < limit:
            a += rng.normal(0.0, 0.32)
            a += (-math.pi / 2 - a) * 0.08                 # keep heading up
            step = 0.010 + 0.006 * rng.random()
            u2, v2 = u + math.cos(a) * step * H / W, v + math.sin(a) * step
            if not inside(u2, v2) or blocked(u2, v2):
                break
            u, v = u2, v2
            length += step
            width *= 0.985
            pts.append((u, v, width))
            if depth < 3 and rng.random() < 0.07:
                stack.append((u, v, a + rng.choice((-1, 1)) * (0.5 + 0.4 * rng.random()), width * 0.7, depth + 1))
        if len(pts) >= 4:
            veins.append(np.array(pts, dtype=np.float32))
    return veins


def rasterize_veins(veins: list[np.ndarray], shape: tuple[int, int]) -> np.ndarray:
    """Veins as a soft 0..1 coverage map (antialiased, tapering)."""
    H, W = shape
    img = QImage(W, H, QImage.Format.Format_Grayscale8)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for vein in veins:
        for (u0, v0, w0), (u1, v1, _w1) in zip(vein[:-1], vein[1:]):
            p.setPen(QPen(QColor(255, 255, 255), max(0.6, float(w0) * H), Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(u0 * (W - 1), v0 * (H - 1)), QPointF(u1 * (W - 1), v1 * (H - 1)))
    p.end()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(H, img.bytesPerLine())[:, :W].astype(np.float32) / 255.0
    return arr


def neural_tint(lum: np.ndarray, mask: np.ndarray, ink: np.ndarray, rim: np.ndarray,
                veins: np.ndarray, primary: QColor) -> QImage:
    """The photo re-lit in blue, with veins and a rim of light (premultiplied, for additive drawing)."""
    col = np.array([primary.red(), primary.green(), primary.blue()], dtype=np.float32)
    mid = _MID * 0.5 + col * 0.5
    l = np.clip(lum * 1.25, 0.0, 1.0)[..., None] ** 0.8
    # Three-stop ramp: navy -> blue -> pale cyan, following the photo's own light.
    lo = np.clip(l * 2.0, 0.0, 1.0)
    hi = np.clip(l * 2.0 - 1.0, 0.0, 1.0)
    rgb = _SHADOW + (mid - _SHADOW) * lo + (_HIGH - mid) * hi
    body_a = mask * (0.48 + 0.52 * l[..., 0])
    line_a = ink * 0.35
    rim_a = rim * 0.85
    vein_a = veins * mask
    rgb = rgb * body_a[..., None]
    rgb += _HIGH * line_a[..., None]
    rgb += (col * 0.5 + _HIGH * 0.5) * rim_a[..., None]
    rgb += _VEIN * (vein_a * 0.95)[..., None]
    a = np.clip(body_a + line_a + rim_a + vein_a * 0.8, 0, 1)
    rgb = np.minimum(rgb, a[..., None] * 255.0)
    a[::3, :] *= 0.78                                               # faint scanlines
    rgb[::3, :] *= 0.78
    out = np.empty(a.shape + (4,), dtype=np.uint8)
    out[..., :3] = np.clip(rgb, 0, 255)
    out[..., 3] = np.clip(a * 255, 0, 255)
    h, w = a.shape
    data = np.ascontiguousarray(out)
    img = QImage(data.data, w, h, w * 4, QImage.Format.Format_RGBA8888_Premultiplied).copy()
    return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def paint_neck_disc(p: QPainter, cx: float, y: float, w: float, primary: QColor, amp: float, t: float) -> None:
    """The glowing disc the neck stands on (drawn additively)."""
    P = (primary.red(), primary.green(), primary.blue())
    rx, ry = w / 2, w * 0.085
    g = QRadialGradient(QPointF(cx, y), rx)
    g.setColorAt(0.0, QColor(210, 240, 255, int(150 + 80 * amp)))
    g.setColorAt(0.45, QColor(*P, int(110 + 60 * amp)))
    g.setColorAt(1.0, QColor(*P, 0))
    p.save()
    p.translate(cx, y)
    p.scale(1.0, ry / rx)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawEllipse(QPointF(0, 0), rx * 1.15, rx * 1.15)
    p.restore()
    p.setBrush(Qt.BrushStyle.NoBrush)
    pulse = 0.5 + 0.5 * math.sin(t * 2.2)
    for k, a in ((1.0, 200), (0.82, 120), (1.12, int(40 + 50 * pulse))):
        p.setPen(QPen(QColor(190, 235, 255, a), 1.4))
        p.drawEllipse(QPointF(cx, y), rx * k, ry * k)


_DOT: dict = {}


def _dot(radius: int) -> QImage:
    """A cached soft light dot (premultiplied) for the vein pulses."""
    img = _DOT.get(radius)
    if img is None:
        img = QImage(radius * 2, radius * 2, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        g = QRadialGradient(QPointF(radius, radius), radius)
        g.setColorAt(0.0, QColor(235, 250, 255, 235))
        g.setColorAt(0.35, QColor(120, 210, 255, 120))
        g.setColorAt(1.0, QColor(60, 150, 255, 0))
        dp = QPainter(img)
        dp.setPen(Qt.PenStyle.NoPen)
        dp.setBrush(QBrush(g))
        dp.drawEllipse(QPointF(radius, radius), radius, radius)
        dp.end()
        _DOT[radius] = img
    return img


def paint_vein_pulses(p: QPainter, holo, veins: list[np.ndarray], f: dict, rect: QRectF, bx: float, by: float,
                      t: float, amp: float, count: int = 26) -> None:
    """Points of light running up the veins; they follow the turned, talking head.

    All pulse positions go through the head's warp and projection in one numpy call."""
    if not veins:
        return
    speed = 0.22 + 0.55 * amp
    us, vs, fades = [], [], []
    for i in range(count):
        vein = veins[(i * 7919) % len(veins)]
        phase = (t * speed + i * 0.37) % 1.0
        k = phase * (len(vein) - 1)
        j = min(int(k), len(vein) - 2)
        frac = k - j
        us.append(vein[j, 0] + (vein[j + 1, 0] - vein[j, 0]) * frac)
        vs.append(vein[j, 1] + (vein[j + 1, 1] - vein[j, 1]) * frac)
        fades.append(math.sin(phase * math.pi))
    xs, ys = holo.to_buffer_many(np.array(us, dtype=np.float32), np.array(vs, dtype=np.float32), f)
    scale = 0.6 + 0.4 * amp
    for x, y, fade in zip(xs.tolist(), ys.tolist(), fades):
        r = max(2, int(round((1.2 + 2.2 * fade * scale) * 3.0)))
        p.setOpacity(max(0.0, min(1.0, fade)))
        p.drawImage(QPointF(rect.left() + x * bx - r, rect.top() + y * by - r), _dot(r))
    p.setOpacity(1.0)


def strand_path(top: QPointF, bottom: QPointF, k: float, t: float, sway: float) -> QPainterPath:
    """One energy strand from the neck disc down into the orb (k in -1..1 spreads it)."""
    path = QPainterPath(top)
    dy = bottom.y() - top.y()
    bend = math.sin(t * 0.7 + k * 3.1) * sway
    path.cubicTo(QPointF(top.x() + k * dy * 0.10 + bend, top.y() + dy * 0.35),
                 QPointF(bottom.x() + k * dy * 0.35 - bend, bottom.y() - dy * 0.45),
                 bottom)
    return path
