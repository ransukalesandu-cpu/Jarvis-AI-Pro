"""Extract the dense 3D face geometry that drives the hologram wireframe.

The hologram contains **no photographs**. It is a wireframe head built from the
478 Face Mesh landmarks measured on a portrait, including MediaPipe's depth
estimate for every point — which is what lets the head rotate as a solid object
rather than a flat mask sliding sideways.

Because 1322 edges only sketch a face, the tessellation is **subdivided**: every
mesh triangle is split into four (recursively, until its area is small enough),
with each new point's depth interpolated from the triangle it belongs to. The
result is a uniform lattice that fills her whole face instead of a cage across
it, and the outer boundary never moves — it is still her measured jawline.

Output (``face_data.js``)::

    window.HOLO_FACE = {
      aspect:   image width / height, so x and y stay in proportion,
      points:   [[x, y, z], ...]   dense lattice; the first 478 entries are the
                                   raw Face Mesh landmarks, x/y normalised 0..1,
                                   z in image-width units (negative = closer),
      edges:    [[a, b], ...]      subdivided tessellation,
      faceOval, leftEye, rightEye, lips, innerLips, brows, iris, anchors,
      stats:    counts + depth range, for the HUD
    }

Usage::

    python JarvisAI/tools/build_holo_face.py \\
        --source JarvisAI/assets/holo/face/source/portrait_ref.jpg \\
        --out    JarvisAI/assets/holo/face/face_data.js

``--subdiv`` sets the minimum split count per triangle-ish area target (default
keeps roughly 6-8k edges, which is what the renderer can stroke every frame).

Requires ``mediapipe==0.10.14`` (the last release exposing ``mp.solutions``, and
the one that ships the face-mesh model inside the wheel, so this runs offline).
Build-time only: the app never imports it.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.python.solutions import face_mesh_connections as FMC

IRIS_RIGHT, IRIS_LEFT = 468, 473

# Canonical lip loops. FACEMESH_LIPS carries both, plus the corner splitters, so
# walking its full adjacency zigzags between the two loops.
OUTER_LIP = (61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146)
INNER_LIP = (78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95)

# Brow chains, outer → inner, as they sit on the mesh.
BROWS = (
    (46, 53, 52, 65, 55, 107, 66, 105, 63, 70),
    (276, 283, 282, 295, 285, 336, 296, 334, 293, 300),
)


def _ordered_ring(edges, subset=None) -> list[int]:
    """Walk a set of mesh edges into contour order.

    ``sorted({...})`` on the flat index set is *not* a contour: drawing it
    connects landmark 33 to 246 and back, which painted a chord straight across
    her face instead of an eye. Walking the adjacency produces the real loop.
    """
    allowed = set(subset) if subset is not None else None
    neighbours: dict[int, list[int]] = {}
    for a, b in edges:
        if allowed is not None and (int(a) not in allowed or int(b) not in allowed):
            continue
        neighbours.setdefault(int(a), []).append(int(b))
        neighbours.setdefault(int(b), []).append(int(a))
    if not neighbours:
        return []

    start = min(neighbours)
    ring = [start]
    prev, current = None, start
    while True:
        options = [n for n in neighbours[current] if n != prev]
        if not options:
            break
        nxt = options[0]
        if nxt == start:
            break
        ring.append(nxt)
        prev, current = current, nxt
        if len(ring) > len(neighbours) + 1:
            break
    return ring


def _triangles(edges: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """Recover the mesh faces from its edge set.

    The tessellation is a proper triangulation, so a face is a 3-clique in the
    edge graph. Collecting them is what lets the lattice be subdivided into
    real triangles instead of just dots in the middle of wires.
    """
    adj: dict[int, set[int]] = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    tris: list[tuple[int, int, int]] = []
    for a, b in edges:
        for c in adj[a] & adj[b]:
            if c > b > a:
                tris.append((a, b, c))
    return tris


def _subdivide(points: list[list[float]], tris: list[tuple[int, int, int]], target: float, max_depth: int):
    """Split triangles until they are small enough, interpolating depth.

    Midpoints are memoised per edge, so neighbouring triangles share them and
    the lattice stays welded instead of cracking open along the seams.
    """
    aspect = 1.0  # points are already in normalised image space; compare areas there

    def area(t):
        ax, ay = points[t[0]][0], points[t[0]][1]
        bx, by = points[t[1]][0], points[t[1]][1]
        cx, cy = points[t[2]][0], points[t[2]][1]
        return abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) * 0.5 * aspect

    mids: dict[tuple[int, int], int] = {}

    def midpoint(i: int, j: int) -> int:
        key = (i, j) if i < j else (j, i)
        if key in mids:
            return mids[key]
        pi, pj = points[i], points[j]
        points.append([
            round((pi[0] + pj[0]) * 0.5, 5),
            round((pi[1] + pj[1]) * 0.5, 5),
            round((pi[2] + pj[2]) * 0.5, 5),
        ])
        mids[key] = len(points) - 1
        return mids[key]

    out: list[tuple[int, int, int]] = []

    def split(t: tuple[int, int, int], depth: int) -> None:
        if depth >= max_depth or area(t) <= target:
            out.append(t)
            return
        a, b, c = t
        ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
        split((a, ab, ca), depth + 1)
        split((b, bc, ab), depth + 1)
        split((c, ca, bc), depth + 1)
        split((ab, bc, ca), depth + 1)

    for t in tris:
        split(t, 0)
    return out


def extract(source: Path, max_depth: int = 3, density: float = 0.16) -> dict:
    bgr = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit(f"cannot read {source}")
    h, w = bgr.shape[:2]

    mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.3,
    )
    result = mesh.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    mesh.close()
    if not result.multi_face_landmarks:
        raise SystemExit("no face found — use a frontal, evenly lit portrait")

    landmarks = result.multi_face_landmarks[0].landmark
    points = [[round(float(p.x), 5), round(float(p.y), 5), round(float(p.z), 5)] for p in landmarks]
    landmark_count = len(points)

    edges = sorted({tuple(sorted((int(a), int(b)))) for a, b in FMC.FACEMESH_TESSELATION})
    tris = _triangles(edges)

    # Split until the median face is a fraction of its original triangle area.
    areas = []
    for t in tris:
        ax, ay = points[t[0]][0], points[t[0]][1]
        bx, by = points[t[1]][0], points[t[1]][1]
        cx, cy = points[t[2]][0], points[t[2]][1]
        areas.append(abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) * 0.5)
    target = statistics.median(areas) * density

    dense_tris = _subdivide(points, tris, target, max_depth)
    dense_edges = sorted({tuple(sorted((t[i], t[(i + 1) % 3]))) for t in dense_tris for i in range(3)})

    zs = [p[2] for p in points]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    return {
        "aspect": round(w / h, 5),
        "landmarks": landmark_count,
        "points": points,
        "edges": dense_edges,
        "faceOval": _ordered_ring(FMC.FACEMESH_FACE_OVAL),
        "leftEye": _ordered_ring(FMC.FACEMESH_LEFT_EYE),
        "rightEye": _ordered_ring(FMC.FACEMESH_RIGHT_EYE),
        "lips": _ordered_ring(FMC.FACEMESH_LIPS, OUTER_LIP),
        "innerLips": _ordered_ring(FMC.FACEMESH_LIPS, INNER_LIP),
        "brows": [list(b) for b in BROWS],
        "iris": {"left": IRIS_LEFT, "right": IRIS_RIGHT},
        "anchors": {
            "forehead": 10,
            "chin": 152,
            "nose": 1,
            "mouth": 13,
            "eyeL": IRIS_LEFT,
            "eyeR": IRIS_RIGHT,
        },
        # faces are for the 3-D exporter only; main() strips them before writing
        # face_data.js so the page never ships them
        "faces": [list(t) for t in dense_tris],
        "stats": {
            "landmarks": landmark_count,
            "points": len(points),
            "edges": len(dense_edges),
            "triangles": len(dense_tris),
            "depth": round(max(zs) - min(zs), 4),
            "width": round(max(xs) - min(xs), 4),
            "height": round(max(ys) - min(ys), 4),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--depth", type=int, default=3, help="max subdivision recursion")
    ap.add_argument("--density", type=float, default=0.16, help="target area as a fraction of the median triangle")
    args = ap.parse_args()

    data = extract(args.source, max_depth=args.depth, density=args.density)
    data.pop("faces", None)   # triangles are for the mesh exporter, not the page
    header = (
        "// Generated by JarvisAI/tools/build_holo_face.py — do not edit by hand.\n"
        "// Subdivided Face Mesh lattice; no image data in here, only geometry.\n"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        header + "window.HOLO_FACE = " + json.dumps(data, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    st = data["stats"]
    print(f"{args.out}  ({args.out.stat().st_size / 1024:.0f} KB)")
    print(
        f"  landmarks {st['landmarks']}  lattice {st['points']} pts / {st['edges']} edges"
        f" / {st['triangles']} faces  depth range {st['depth']}"
    )


if __name__ == "__main__":
    main()
