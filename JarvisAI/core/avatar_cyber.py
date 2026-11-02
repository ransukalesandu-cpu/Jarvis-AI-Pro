"""The "cyber" look of the holographic head: half-transparent blue glass,
sharp edge-lit features, circuit traces with travelling pulses, hair strands
and a shoulder bust. All code-rendered (QPainter + numpy), no images.

Built once from the head mesh (core/avatar_mesh.py) by ``CyberParts.build``;
``paint`` draws a frame using the posed vertices that HoloAvatar already
computes, so the traces and hair move, blink and talk with the face.

Look targets (owner's reference): about 50% opacity overall and a little more
see-through across the middle of the face; bright contours, brows, eyes and
lips; electric-blue circuit lines over face, neck and shoulders; glowing eyes.
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient

FILL_ALPHA = 0.50          # overall glass opacity (owner: "about 50 percent")
CENTRE_ALPHA = 0.34        # the middle of the face reads a little more see-through
_LUT_N = 64


def _c(col: QColor, a: float) -> QColor:
    q = QColor(col)
    q.setAlpha(int(max(0.0, min(255.0, a))))
    return q


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


def _adjacency(faces: np.ndarray, n: int) -> list[set[int]]:
    adj: list[set[int]] = [set() for _ in range(n)]
    for a, b, c in faces.tolist():
        adj[a].update((b, c))
        adj[b].update((a, c))
        adj[c].update((a, b))
    return adj


def _walk_traces(verts: np.ndarray, adj: list[set[int]], seeds: list[int], rng,
                 exclude: set[int], min_len=4, max_len=11) -> list[np.ndarray]:
    """Circuit-like paths along mesh edges: mostly straight, sharp 90° turns."""
    used: set[int] = set()
    traces = []
    dirs = [np.array(d, dtype=np.float32) for d in ((0, 1), (0, -1), (1, 0), (-1, 0))]
    for seed in seeds:
        if seed in used or seed in exclude:
            continue
        path = [seed]
        d = dirs[rng.integers(4)]
        length = int(rng.integers(min_len, max_len + 1))
        for _ in range(length):
            cur = path[-1]
            best, best_score = None, -2.0
            for nb in adj[cur]:
                if nb in used or nb in exclude or nb in path:
                    continue
                step = verts[nb, :2] - verts[cur, :2]
                norm = float(np.linalg.norm(step)) or 1.0
                score = float(np.dot(step / norm, d))
                if score > best_score:
                    best, best_score = nb, score
            if best is None or best_score < 0.35:
                break
            path.append(best)
            if rng.random() < 0.22:          # a right-angle turn, like a PCB trace
                d = np.array([-d[1], d[0]], dtype=np.float32) * (1 if rng.random() < 0.5 else -1)
        if len(path) >= min_len:
            traces.append(np.array(path, dtype=np.int32))
            used.update(path)
    return traces


def _hair_cap(v: np.ndarray, faces: np.ndarray, n_head: int):
    """Scalp faces lifted off the skull: the mass of the hair.

    Returns (cap vertices, cap faces, head centre). Cap vertices share the head
    indexing; only the ones the cap faces use matter.
    """
    head = v[:n_head]
    centre = np.array([0.0, float(head[:, 1].mean()) * 0.5, -0.05], dtype=np.float32)
    x, y, z = head[:, 0], head[:, 1], head[:, 2]
    # Hairline: high at the front, lower at the temples, down to the ears behind.
    line = np.where(z > 0.0, 0.50 + 0.10 * np.clip(z, 0, 1) - 0.25 * np.clip(np.abs(x) - 0.25, 0, 1),
                    0.40 - 0.55 * np.clip(-z, 0, 1))
    scalp = y > line
    hf = faces[(faces < n_head).all(axis=1)]
    cap_f = hf[scalp[hf].all(axis=1)]
    off = head - centre
    r = np.linalg.norm(off, axis=1, keepdims=True)
    top = np.clip((y - 0.25) / 0.75, 0, 1)[:, None]
    lift = 0.03 + 0.07 * top                          # fuller on top than at the sides
    cap_v = (centre + off * (1.0 + lift / np.maximum(r, 1e-6))).astype(np.float32)
    return cap_v, cap_f.astype(np.int32), centre


def _grow_hair(cap_v: np.ndarray, cap_f: np.ndarray, centre: np.ndarray, rng,
               count: int = 320) -> np.ndarray:
    """Short wavy strands lying on the cap, combed off a side part.

    Front strands sweep across the forehead, the crown combs back from the
    part, the sides fall down and back. Gravity bends them all a little.
    """
    if len(cap_f) == 0:
        return np.zeros((0, 8, 3), dtype=np.float32)
    tri = cap_v[cap_f]
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    # Seen from the front: weight the roots towards the hairline and the top.
    mid = tri.mean(axis=1)
    weight = area * (0.15 + np.clip(mid[:, 2] + 0.4, 0, 1.4))
    pick = rng.choice(len(cap_f), size=count, p=weight / weight.sum())
    part_x = -0.26                                   # a side part, viewer's left
    strands = []
    for f in pick:
        w = rng.dirichlet((1.0, 1.0, 1.0)).astype(np.float32)
        p = (tri[f] * w[:, None]).sum(0)
        r0 = float(np.linalg.norm(p - centre)) + 0.01
        x, y, z = (float(c) for c in p)
        if abs(x) > 0.55 and y < 0.55:                       # sides: down and back
            comb = np.array([np.sign(x) * 0.15, -0.8, -0.6])
            steps = 3
        elif z > 0.15:                                       # front: across, a fringe
            comb = np.array([0.85 if x >= part_x else -0.7, -0.25, 0.45])
            steps = 7
        else:                                                # crown: back from the part
            comb = np.array([0.4 * (1 if x >= part_x else -1), -0.3, -0.85])
            steps = 5
        comb = comb.astype(np.float32) + rng.normal(0, 0.15, 3).astype(np.float32)
        ph = float(rng.random() * 6.283)
        amp = 0.010 + 0.012 * rng.random()
        pts = []
        for k in range(8):
            n = (p - centre) / (np.linalg.norm(p - centre) or 1.0)
            p = centre + n * r0
            tang = comb - n * float(np.dot(comb, n))
            tang /= np.linalg.norm(tang) or 1.0
            pts.append(p + np.cross(n, tang) * amp * math.sin(ph + k * 1.4))
            if k < steps:
                p = p + tang * 0.055
            comb = comb + np.array([0.0, -0.10, 0.0], dtype=np.float32)
        strands.append(pts)
    return np.array(strands, dtype=np.float32)


def _ears(v: np.ndarray, n_head: int) -> np.ndarray:
    """Two ears as 3D outlines: rim (helix) plus inner fold (antihelix).

    Returns (2, 2, N, 3): side, curve, point. Placed on the side of the skull
    between eye level and the base of the nose, leaning back slightly.
    """
    head = v[:n_head]
    band = np.abs(head[:, 1] - 0.0) < 0.08
    half_w = float(np.abs(head[band, 0]).max())
    t = np.linspace(0.0, 2.0 * math.pi, 22)
    out = []
    for side in (-1.0, 1.0):
        curves = []
        for scale, depth in ((1.0, 0.035), (0.58, 0.015)):
            # A "C" that is wider at the top than at the lobe.
            yy = 0.035 + scale * (0.17 * np.sin(t) * np.where(np.sin(t) > 0, 1.0, 1.15))
            zz = -0.36 + scale * 0.085 * np.cos(t) * (1.0 + 0.25 * np.sin(t))
            zz -= 0.10 * (yy - 0.035)                    # lean back
            # The rim stands off the skull, most at the back and the top.
            xx = side * (half_w * 0.95 + depth + 0.055 * (1 - np.cos(t)) + 0.03 * np.clip(np.sin(t), 0, 1))
            curves.append(np.stack([xx, yy, zz], axis=1))
        out.append(curves)
    return np.array(out, dtype=np.float32)


class CyberParts:
    """Everything precomputed for the cyber look (built once per avatar)."""

    def __init__(self):
        self.traces: list[np.ndarray] = []
        self.trace_phase: np.ndarray = np.zeros(0)
        self.hair: np.ndarray = np.zeros((0, 0, 3))
        self.bust_v = np.zeros((0, 3))
        self.bust_faces = np.zeros((0, 3), dtype=np.int32)
        self.bust_edges = np.zeros((0, 2), dtype=np.int32)
        self.bust_fade = np.zeros(0)
        self.bust_traces: list[np.ndarray] = []
        self.centre_w = np.zeros(0)
        self.edges = np.zeros((0, 2), dtype=np.int32)
        self.cap_v = np.zeros((0, 3), dtype=np.float32)
        self.ears = np.zeros((0, 2, 0, 3), dtype=np.float32)
        self.cap_f = np.zeros((0, 3), dtype=np.int32)
        self.face_keep = np.zeros(0, dtype=np.int64)
        self.bust_n = np.zeros((0, 3))
        self._lut_key = None
        self._lut: list = []
        self._brushes: dict = {}

    @classmethod
    def build(cls, mesh: dict, seed: int = 7) -> "CyberParts":
        rng = np.random.default_rng(seed)
        self = cls()
        v = mesh["verts"]
        n = len(v)
        faces = mesh["faces"]
        n_head = mesh["n_head"]
        lm = mesh["landmarks"]
        adj = _adjacency(faces, n)
        # Every edge, not the strided wireframe: the sharp look needs them all.
        e = np.sort(np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
        edges = np.unique(e, axis=0).astype(np.int32)
        # The neck tube runs up inside the jaw. Opaque looks hide that; at 50%
        # glass it shows through the chin as a box, so drop the hidden part.
        hidden = np.zeros(n, dtype=bool)
        hidden[n_head:] = v[n_head:, 1] > -0.90
        neck_face = mesh["face_group"] == 0
        tucked = neck_face & (v[faces][:, :, 1].mean(axis=1) > -0.93)
        self.face_keep = np.flatnonzero(~hidden[faces].all(axis=1) & ~tucked)
        self.edges = edges[~(hidden[edges[:, 0]] | hidden[edges[:, 1]])]

        # Keep traces off the eyes and lips so the features stay clean.
        feature = np.concatenate([lm[k] for k in ("eye_l", "eye_r", "lips_in", "lips_out")])
        exclude = set(int(i) for i in feature) | set(np.flatnonzero(hidden).tolist())
        for i in list(exclude):
            exclude.update(adj[i])
        front = np.flatnonzero((v[:, 2] > -0.25))
        seeds = rng.permutation(front).tolist()
        self.traces = _walk_traces(v, adj, seeds, rng, exclude)
        self.trace_phase = rng.random(len(self.traces)).astype(np.float32)

        # Translucency weight per triangle: lower across the middle of the face.
        cx = np.abs(v[:, 0])
        centre = np.exp(-(cx / 0.30) ** 2) * np.exp(-((v[:, 1] + 0.05) / 0.42) ** 2)
        centre *= np.clip((v[:, 2] - 0.05) / 0.3, 0.0, 1.0)
        self.centre_w = centre[faces].mean(axis=1).astype(np.float32)

        self.ears = _ears(v, n_head)
        self.cap_v, self.cap_f, centre = _hair_cap(v, faces, n_head)
        self.hair = _grow_hair(self.cap_v, self.cap_f, centre, rng)

        # Bust: neck base flaring into shoulders (front half), fixed in space.
        neck = v[n_head:]
        y0 = float(neck[:, 1].min()) + 0.06
        z0 = float((neck[:, 2].min() + neck[:, 2].max()) / 2)
        nr = float(neck[:, 0].max()) * 0.95
        cols, rows = 25, 8
        bv = []
        for j in range(rows):
            t = j / (rows - 1)
            for i in range(cols):
                u = -1.0 + 2.0 * i / (cols - 1)
                half_w = nr * (1.0 + t * 2.6)
                x = u * half_w
                y = y0 - t * 0.40 - (abs(u) ** 1.5) * t * 0.80
                z = z0 + math.sqrt(max(0.0, 1.0 - u * u)) * (nr * 0.9 + t * 0.55) - (abs(u) ** 2) * t * 0.2
                bv.append((x, y, z))
        self.bust_v = np.array(bv, dtype=np.float32)
        bf, be = [], set()
        for j in range(rows - 1):
            for i in range(cols - 1):
                a, b = j * cols + i, j * cols + i + 1
                c, d = a + cols, b + cols
                bf += [(a, b, c), (b, d, c)]
                be.update({(a, b), (a, c), (b, d)})
        self.bust_faces = np.array(bf, dtype=np.int32)
        self.bust_edges = np.array(sorted(be), dtype=np.int32)
        rowt = np.repeat(np.linspace(0, 1, rows), cols)
        colu = np.tile(np.linspace(-1, 1, cols), rows)
        # Dissolve into the dark towards the bottom and the arms, never a hard cut.
        self.bust_fade = (np.clip(1.0 - rowt ** 1.3, 0, 1) ** 1.6
                          * np.clip(1.2 - np.abs(colu) ** 2.5, 0, 1)).astype(np.float32)
        bn = np.zeros_like(self.bust_v)
        fa, fb, fc = (self.bust_faces[:, i] for i in range(3))
        fnorm = np.cross(self.bust_v[fb] - self.bust_v[fa], self.bust_v[fc] - self.bust_v[fa])
        fnorm *= np.sign(fnorm[:, 2:3] + 1e-9)            # the front of the chest faces the camera
        for col in (fa, fb, fc):
            np.add.at(bn, col, fnorm)
        bn /= np.maximum(np.linalg.norm(bn, axis=1, keepdims=True), 1e-9)
        self.bust_n = bn.astype(np.float32)
        badj = _adjacency(self.bust_faces, len(bv))
        bseeds = rng.permutation(np.flatnonzero(rowt < 0.6)).tolist()
        self.bust_traces = _walk_traces(self.bust_v, badj, bseeds, rng,
                                        set(np.flatnonzero(rowt > 0.75).tolist()), 3, 7)
        return self

    # ── painting ────────────────────────────────────────────────────────────
    def _lut_for(self, primary: QColor):
        key = primary.rgb()
        if self._lut_key != key:
            deep = QColor(4, 20, 60)
            self._lut = [_mix(deep, primary, (i + 0.5) / _LUT_N) for i in range(_LUT_N)]
            self._lut_key = key
        return self._lut

    def _brush(self, li: int, alpha: int) -> QBrush:
        key = (li, alpha)
        b = self._brushes.get(key)
        if b is None:
            col = QColor(self._lut[li])
            col.setAlpha(alpha)
            b = self._brushes[key] = QBrush(col)
        return b

    def paint_fill(self, p: QPainter, xs, ys, verts, faces, fgroup, primary: QColor, amp: float,
                   centre=None, fade=None, cull: bool = True, gain: float = 1.0) -> None:
        """Half-transparent glass: lit facets, about 50% opaque, see-through middle.

        Only camera-facing facets are filled. Drawing the far side too would
        double the opacity wherever the head overlaps itself, and the 50% look
        would turn solid.
        """
        a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
        # Screen-space winding decides facing; the mesh is wound consistently.
        cross = (xs[b] - xs[a]) * (ys[c] - ys[a]) - (xs[c] - xs[a]) * (ys[b] - ys[a])
        area = np.abs(cross)
        keep = area > 2.0
        if cull:
            sign = np.sign(np.median(cross[keep])) if keep.any() else 1.0
            keep &= (cross * sign) > 0
        vis = np.flatnonzero(keep)
        if vis.size == 0:
            return
        fn = np.cross(verts[b[vis]] - verts[a[vis]], verts[c[vis]] - verts[a[vis]])
        fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-9)
        fn *= np.sign(fn[:, 2:3] + 1e-9)
        nz = fn[:, 2]
        lam = np.clip(fn[:, 0] * -0.45 + fn[:, 1] * 0.55 + nz * 0.55, 0, 1)
        rim = np.clip(1.0 - nz, 0, 1) ** 1.5
        bright = np.clip(0.18 + 0.55 * lam + 0.45 * rim + 0.15 * amp, 0, 1)
        cw = (self.centre_w if centre is None else centre)[vis]
        alpha = 255 * (FILL_ALPHA - (FILL_ALPHA - CENTRE_ALPHA) * np.clip(cw * 1.6, 0, 1)) \
            * (0.55 + 0.45 * np.clip(bright + rim, 0, 1))
        alpha *= gain
        if fade is not None:
            f = np.minimum(np.minimum(fade[a[vis]], fade[b[vis]]), fade[c[vis]])
            alpha *= f ** 1.2       # the min: the edge dissolves without a sawtooth
        fz = (verts[a[vis], 2] + verts[b[vis], 2] + verts[c[vis], 2]) / 3.0
        order = np.argsort(fgroup[vis] * 1000.0 + fz, kind="stable")
        self._lut_for(primary)
        li = np.clip((bright * _LUT_N).astype(np.int32), 0, _LUT_N - 1)[order].tolist()
        al = ((np.minimum(alpha[order], 255) / 16).astype(np.int32) * 16).tolist()
        av, bv, cv = a[vis][order], b[vis][order], c[vis][order]
        tri = np.stack([xs[av], ys[av], xs[bv], ys[bv], xs[cv], ys[cv]], axis=1).tolist()
        p.setPen(Qt.PenStyle.NoPen)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        brush = self._brush
        for q, i, aa in zip(tri, li, al):
            if aa < 24:
                continue
            p.setBrush(brush(i, aa))
            p.drawPolygon(QPolygonF((QPointF(q[0], q[1]), QPointF(q[2], q[3]), QPointF(q[4], q[5]))))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def paint_edges(self, p: QPainter, xs, ys, norms, e0, e1, fade, primary: QColor, amp: float,
                    buckets: int = 4) -> None:
        """Thin interior lines, bright silhouette: a crisp, edge-lit hologram."""
        nz = norms[:, 2]
        rim = np.clip(1.0 - np.abs(nz), 0, 1) ** 2.2
        va = np.where(nz > 0, 0.10 + 0.95 * rim, 0.025) * fade * (0.85 + 0.35 * amp)
        ea = 0.5 * (va[e0] + va[e1])
        keep = np.flatnonzero(ea > 0.04)
        if keep.size == 0:
            return
        bucket = np.clip((np.clip(ea[keep], 0, 1) * buckets).astype(np.int32), 0, buckets - 1)
        order = np.argsort(bucket, kind="stable")
        keep = keep[order]
        bounds = np.searchsorted(bucket[order], np.arange(buckets + 1))
        quad = np.stack([xs[e0[keep]], ys[e0[keep]], xs[e1[keep]], ys[e1[keep]]], axis=1).tolist()
        lines = [QLineF(*q) for q in quad]
        light = primary.lighter(150)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k in range(buckets):
            lo, hi = int(bounds[k]), int(bounds[k + 1])
            if hi <= lo:
                continue
            f = (k + 0.5) / buckets
            p.setPen(QPen(_c(light, 60 + 195 * f), 0.7 + 0.6 * f))
            p.drawLines(lines[lo:hi])

    def paint_traces(self, p: QPainter, xs, ys, norms, traces, phases, accent: QColor,
                     t: float, amp: float, face_k: float = 1.0) -> None:
        """Circuit traces with a node at each end and a pulse travelling along."""
        if not traces:
            return
        nz = norms[:, 2] if norms is not None else None
        speed = 0.12 + 0.75 * amp
        line_pen = QPen(_c(accent, 150 * face_k), 1.0)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        ends = []
        pulses = []
        for k, tr in enumerate(traces):
            if nz is not None and float(nz[tr].mean()) < 0.05:
                continue                      # on the far side of the head
            px, py = xs[tr], ys[tr]
            path.moveTo(float(px[0]), float(py[0]))
            for x, y in zip(px[1:].tolist(), py[1:].tolist()):
                path.lineTo(x, y)
            ends.append((float(px[-1]), float(py[-1])))
            f = (t * speed + float(phases[k % len(phases)])) % 1.0
            pos = f * (len(tr) - 1)
            i = int(pos)
            fr = pos - i
            j = min(i + 1, len(tr) - 1)
            pulses.append((float(px[i] + (px[j] - px[i]) * fr), float(py[i] + (py[j] - py[i]) * fr)))
        p.setPen(line_pen)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(accent, 210 * face_k))
        for x, y in ends:
            p.drawEllipse(QPointF(x, y), 1.7, 1.7)
        p.setBrush(_c(QColor(220, 250, 255), (160 + 90 * amp) * face_k))
        for x, y in pulses:
            p.drawEllipse(QPointF(x, y), 1.6 + 1.2 * amp, 1.6 + 1.2 * amp)

    def paint_hair(self, p: QPainter, hair_xy: np.ndarray, hair_z: np.ndarray, primary: QColor,
                   scale: float = 1.0) -> None:
        """Thin bright strands; the cap underneath gives the hair its body."""
        path = QPainterPath()
        for strand, zs in zip(hair_xy.tolist(), hair_z.tolist()):
            if sum(zs) / len(zs) < -0.30:
                continue
            path.moveTo(strand[0][0], strand[0][1])
            for k in range(1, len(strand) - 1, 2):
                path.quadTo(strand[k][0], strand[k][1], strand[k + 1][0], strand[k + 1][1])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(primary.lighter(170), 175), max(0.8, 0.95 * scale)))
        p.drawPath(path)

    def paint_ears(self, p: QPainter, ear_xy: np.ndarray, primary: QColor) -> None:
        """Translucent ear shells with a bright rim and a fainter inner fold."""
        for curves in ear_xy.tolist():
            rim = QPolygonF([QPointF(x, y) for x, y in curves[0]])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(primary, 70))
            p.drawPolygon(rim)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_c(primary.lighter(160), 200), 1.1))
            p.drawPolygon(rim)
            p.setPen(QPen(_c(primary.lighter(140), 120), 0.8))
            p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in curves[1][3:-6]]))

    def paint_eye_glow(self, p: QPainter, centre: QPointF, rad: float, accent: QColor, k: float) -> None:
        g = QRadialGradient(centre, rad * 3.2)
        g.setColorAt(0.0, _c(QColor(235, 252, 255), 240 * k))
        g.setColorAt(0.25, _c(accent, 200 * k))
        g.setColorAt(1.0, _c(accent, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QRectF(centre.x() - rad * 3.2, centre.y() - rad * 3.2, rad * 6.4, rad * 6.4))
