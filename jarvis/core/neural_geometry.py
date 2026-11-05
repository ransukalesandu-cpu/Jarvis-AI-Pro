"""Constants and pure geometry helpers for the neural HUD scenes (no state)."""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath

TAU = math.tau
PLUS = QPainter.CompositionMode.CompositionMode_Plus
OVER = QPainter.CompositionMode.CompositionMode_SourceOver
SOLID = Qt.PenStyle.SolidLine
ROUND = Qt.PenCapStyle.RoundCap
ROUNDJ = Qt.PenJoinStyle.RoundJoin
NOPEN = Qt.PenStyle.NoPen
NOBRUSH = Qt.BrushStyle.NoBrush
WHITE = (255, 255, 255)

# Region titles. The number is the palette slot, so a tag always matches the
# colour of the zone it labels.
REGIONS = (
    ("PRE-FRONTAL", 0), ("MOTOR CORTEX", 1), ("ASSOCIATION", 6),
    ("CONCEPT LAYER", 2), ("SENSORY CORTEX", 3), ("LANGUAGE", 4),
    ("HIPPOCAMPUS", 5),
)
BANDS = 12          # spectral bands used to batch the globe mesh
RAMP_N = 48         # resolution of the smooth spectral ramp


def _clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else (hi if v > hi else v)


def _rgba(rgb, alpha):
    a = 0 if alpha < 0 else (255 if alpha > 255 else int(alpha))
    return QColor(rgb[0], rgb[1], rgb[2], a)


def _mix(rgb, other, t):
    return (int(rgb[0] + (other[0] - rgb[0]) * t),
            int(rgb[1] + (other[1] - rgb[1]) * t),
            int(rgb[2] + (other[2] - rgb[2]) * t))


def _dots() -> QPainterPath:
    """A path for many small filled circles. Winding fill keeps overlapping
    dots solid instead of punching even-odd holes where they touch."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    return path


def _bucket(store: dict, key, factory=QPainterPath):
    path = store.get(key)
    if path is None:
        path = store[key] = factory()
    return path


# --------------------------------------------------------------------------
# Layout generators (run once)
# --------------------------------------------------------------------------
def _grow(nodes, root, trunks, max_depth, spread, decay, rng, lim=(1.12, 1.08)):
    """Grow a fractal arbor from ``nodes[root]``.

    ``nodes`` rows are [x, y, parent, depth, colour, seed, path_distance].
    ``trunks`` is a list of (heading, length, colour). A parent is always
    appended before its children, which the painter relies on.
    """
    rx, ry, rdist = nodes[root][0], nodes[root][1], nodes[root][6]
    stack = [(root, rx, ry, h, ln, 0, col, rdist) for h, ln, col in trunks]
    while stack:
        parent, x, y, heading, length, depth, col, dist = stack.pop()
        ex = _clamp(x + math.cos(heading) * length, -lim[0], lim[0])
        ey = _clamp(y + math.sin(heading) * length, -lim[1], lim[1])
        run = math.hypot(ex - x, ey - y)
        nodes.append([ex, ey, parent, depth, col, rng.random() * TAU, dist + run])
        idx = len(nodes) - 1
        if depth >= max_depth:
            continue
        kids = 2 if rng.random() < 0.78 else 3
        if depth == max_depth - 1 and rng.random() < 0.30:
            kids = 1
        for k in range(kids):
            turn = (k - (kids - 1) / 2.0) * spread + rng.uniform(-0.26, 0.26)
            stack.append((idx, ex, ey, heading + turn,
                          length * rng.uniform(decay - 0.08, decay + 0.08),
                          depth + 1, col, dist + run))


def _pack_tree(nodes):
    """Flatten tree rows into parallel lists (fast to index in the paint loop)
    and normalise path distance to 0..1 so a travelling wave can sweep it."""
    top = max(n[6] for n in nodes) or 1.0
    parents = {n[2] for n in nodes if n[2] >= 0}
    return {
        "x": [n[0] for n in nodes], "y": [n[1] for n in nodes],
        "par": [n[2] for n in nodes], "dep": [n[3] for n in nodes],
        "col": [n[4] for n in nodes], "seed": [n[5] for n in nodes],
        "dist": [n[6] / top for n in nodes],
        "leaf": [(i not in parents and nodes[i][2] >= 0) for i in range(len(nodes))],
    }


def _scatter(rng, clusters, lim):
    """Gaussian clouds of neurons. Returns particles, members and centres."""
    particles, members, centers = [], [], []
    for ci, (cx, cy, sx, sy, col, count) in enumerate(clusters):
        mem = []
        for _ in range(count):
            x = _clamp(rng.gauss(cx, sx), -lim[0], lim[0])
            y = _clamp(rng.gauss(cy, sy), -lim[1], lim[1])
            radius = rng.choices((0.55, 0.8, 1.1, 1.6, 2.4), (18, 43, 30, 6, 3))[0]
            mem.append(len(particles))
            particles.append((x, y, radius, col, rng.random() * TAU,
                              rng.uniform(0.004, 0.020), ci))
        members.append(mem)
        centers.append((cx, cy, col))
    return particles, members, centers


def _link(rng, particles, members, local, reach2, cross):
    """Edge rows: (a, b, src_cluster, phase_offset, direction, dst_cluster).
    Rows whose dst differs from src are long inter-region axons."""
    edges = []
    for ci, mem in enumerate(members):
        for _ in range(local):
            a = mem[rng.randrange(len(mem))]
            ax, ay = particles[a][0], particles[a][1]
            near = [b for b in mem if b != a
                    and (particles[b][0] - ax) ** 2 + (particles[b][1] - ay) ** 2 < reach2]
            if near:
                edges.append((a, rng.choice(near), ci, rng.random() * TAU,
                              rng.choice((-1.0, 1.0)), ci))
    for ci, mem in enumerate(members):
        for hop, count in cross:
            tj = (ci + hop) % len(members)
            for _ in range(count):
                edges.append((rng.choice(mem), rng.choice(members[tj]), ci,
                              rng.random() * TAU, rng.choice((-1.0, 1.0)), tj))
    return edges


def _stars(rng, count):
    out = []
    for _ in range(count):
        layer = rng.choice((0, 1, 1, 2))
        out.append((rng.uniform(-1.04, 1.04), rng.uniform(-1.04, 1.04),
                    rng.uniform(0.35, 1.05) * (0.8 + 0.25 * layer),
                    rng.random() * TAU, layer,
                    rng.choice((7, 7, 7, 0, 1, 2, 3, 4, 5, 6))))
    return out
