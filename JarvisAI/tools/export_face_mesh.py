"""Export her measured face as a real 3-D mesh — GLB (binary glTF) and OBJ.

Why this exists
---------------
The hologram is already a triangulated 3-D surface: 478 Face Mesh landmarks with
MediaPipe's depth, subdivided into ~4.5k triangles. Nothing about that is
screen-only — it can be a model like any other. This script writes it out so it
opens in Blender, Windows 3D Viewer, macOS Preview, Sketchfab, Unity, Unreal,
Godot, VRChat… without paying a generation service for an export.

    python JarvisAI/tools/export_face_mesh.py \\
        --source JarvisAI/assets/holo/face/source/portrait_ref.jpg \\
        --outdir JarvisAI/assets/holo/face/model

Writes ``face.glb`` (single file, geometry + normals + a matte material) and
``face.obj`` + ``face.mtl`` (plain text, maximum compatibility).

Coordinate change: the page works in image space (x right, y **down**, z
negative towards the camera). glTF is Y-up with +Z towards the viewer, so the
export flips y and z, then scales the face to a real-world size (~22 cm from
chin to hairline) and centres it on the origin.

The result is an **open shell** — the front surface of her face, not a closed
head — because that is exactly what a 478-point face mesh measures. It is the
right shape for a face overlay, a mask, a game avatar's head or a 3-D print
with your own backing.

Build-time only: the app never imports this.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_holo_face import extract  # noqa: E402  (same tools folder, not a package)

FACE_HEIGHT_M = 0.22          # chin → hairline, a little under life size


def build_surface(data: dict):
    """Triangulate her face using the real face-mesh topology.

    The canonical tessellation is the edge set in ``data['edges']``; its faces
    are the 3-cliques of that graph, which is how the face mesh is defined. That
    keeps the triangle shapes the model was designed with — a Delaunay over the
    same points invents long triangles that interpolate depth across nothing and
    turn her nose into melted wax.

    The eye apertures are holes in the canonical mesh, so they are capped with a
    fan from the iris; a hole in a shaded surface renders as a black pit.
    """
    pts = np.asarray(data["points"], dtype=np.float64)
    verts = np.stack([pts[:, 0], pts[:, 1] / data["aspect"], pts[:, 2]], axis=1)

    faces = [list(t) for t in data["faces"]]
    for ring_name, iris_key in (("leftEye", "left"), ("rightEye", "right")):
        ring = data.get(ring_name) or []
        iris = (data.get("iris") or {}).get(iris_key)
        if not ring or iris is None:
            continue
        for k in range(len(ring)):
            faces.append([iris, ring[k], ring[(k + 1) % len(ring)]])

    return verts, np.asarray(faces, dtype=np.int64)


def surface_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Per-vertex normals from a local plane fit around each point.

    Cross products need every triangle to wind the same way, and the faces
    recovered from an edge set do not: a few 3-cliques are cycles rather than
    real faces and the orientation cannot propagate across them. Fitting a
    plane to each vertex's neighbourhood is winding-independent, so the nose
    and cheekbones shade correctly no matter how the triangles are ordered.
    """
    neighbours: dict[int, set[int]] = {i: set() for i in range(len(verts))}
    for a, b, c in faces:
        for u, v in ((a, b), (b, c), (c, a)):
            neighbours[u].add(v)
            neighbours[v].add(u)

    normals = np.zeros_like(verts)
    for i in range(len(verts)):
        ring = list(neighbours[i])
        if len(ring) < 3:
            normals[i] = (0.0, 0.0, 1.0)
            continue
        pts = verts[ring] - verts[ring].mean(axis=0)
        # smallest-variance direction of the neighbourhood = the surface normal
        _, _, vt = np.linalg.svd(pts, full_matrices=False)
        n = vt[2]
        if n[2] < 0:                     # always face the viewer (+Z)
            n = -n
        normals[i] = n
    return normals


def _boundary_loops(faces: np.ndarray) -> list[list[int]]:
    """Walk the open edges of a surface into closed loops.

    Every edge used by exactly one triangle is on a hole boundary. Sorting those
    points by angle around the centroid — the obvious shortcut — mixes the face
    oval with the two eye apertures and throws spikes across the model, so the
    loops are chained edge by edge instead.
    """
    from collections import Counter

    counts: Counter = Counter()
    for a, b, c in faces:
        for u, v in ((a, b), (b, c), (c, a)):
            counts[(min(u, v), max(u, v))] += 1

    adjacency: dict[int, list[int]] = {}
    for (u, v), n in counts.items():
        if n == 1:
            adjacency.setdefault(u, []).append(v)
            adjacency.setdefault(v, []).append(u)

    loops: list[list[int]] = []
    seen: set[int] = set()
    for start_v in list(adjacency):
        if start_v in seen:
            continue
        loop = [start_v]
        seen.add(start_v)
        prev, current = None, start_v
        while True:
            options = [n for n in adjacency[current] if n != prev]
            if not options:
                break
            nxt = options[0] if options[0] not in seen else None
            if nxt is None or nxt == start_v:
                break
            loop.append(nxt)
            seen.add(nxt)
            prev, current = current, nxt
        if len(loop) >= 8:
            loops.append(loop)
    loops.sort(key=len, reverse=True)
    return loops


def close_shell(points: np.ndarray, faces: np.ndarray, depth: float):
    """Grow a back onto the open face shell so it becomes a closed head.

    The longest boundary loop is the jaw / hairline outline; the smaller loops
    are the eye apertures, which are already capped by the eye fans. The outline
    is bridged to a copy pushed backwards along -Z and then fanned shut — which
    also fills the back of the skull in a viewer that culls back faces.
    """
    loops = _boundary_loops(faces)
    if not loops:
        return points, faces
    ring = loops[0]

    centre = points[ring].mean(axis=0)

    # three shrinking rings, so the new volume tapers like a skull instead of
    # ending in one flat slab behind her ears
    steps = ((1.00, 0.30), (0.86, 0.62), (0.55, 0.86))
    n = len(points)
    ring_count = len(ring)
    verts = np.vstack([points, np.zeros((ring_count * len(steps) + 1, 3))])

    for level, (shrink, z_frac) in enumerate(steps):
        for k, idx in enumerate(ring):
            base = points[idx]
            verts[n + level * ring_count + k] = np.array([
                centre[0] + (base[0] - centre[0]) * shrink,
                centre[1] + (base[1] - centre[1]) * shrink,
                base[2] - depth * z_frac,
            ])

    back_centre = n + ring_count * len(steps)
    verts[back_centre] = centre - np.array([0.0, 0.0, depth * 1.05])

    new_faces = []
    # bridge the face boundary to the first ring
    for k in range(ring_count):
        f = ring[k]
        g = ring[(k + 1) % ring_count]
        bf = n + k
        bg = n + (k + 1) % ring_count
        new_faces.append([f, bf, bg])
        new_faces.append([f, bg, g])
    # bridge ring to ring
    for level in range(len(steps) - 1):
        off_a = n + level * ring_count
        off_b = n + (level + 1) * ring_count
        for k in range(ring_count):
            a0 = off_a + k
            a1 = off_a + (k + 1) % ring_count
            b0 = off_b + k
            b1 = off_b + (k + 1) % ring_count
            new_faces.append([a0, b0, b1])
            new_faces.append([a0, b1, a1])
    # fan the last ring shut
    last = n + (len(steps) - 1) * ring_count
    for k in range(ring_count):
        new_faces.append([last + k, back_centre, last + (k + 1) % ring_count])

    all_faces = np.vstack([faces, np.asarray(new_faces, dtype=np.int64)])
    return verts, all_faces


def build_mesh(data: dict, target_height: float = FACE_HEIGHT_M, closed: bool = False):
    """Turn the measured face into Y-up, metre-scale vertices + normals."""
    pts, faces = build_surface(data)

    # undo the photo aspect on y so the face is not stretched, then flip into
    # glTF space: X right, Y up, Z towards the viewer
    verts = np.stack([pts[:, 0], -pts[:, 1], pts[:, 2]], axis=1)

    # centre on the origin and scale to a real size
    verts -= (verts.min(axis=0) + verts.max(axis=0)) * 0.5
    height = verts[:, 1].max() - verts[:, 1].min()
    verts *= target_height / height
    # a face mesh is a shallow shell; lift the relief a little so the nose,
    # brow ridge and lips actually read once it is shaded
    verts[:, 2] *= 1.35

    if closed:
        verts, faces = close_shell(verts, faces, depth=target_height * 0.30)

    # normals from a local plane fit: winding-free, and it follows the nose
    # instead of exploding where a triangle stands on edge
    vnorm = surface_normals(verts, faces)

    return verts, vnorm, faces


def _pad4(blob: bytes, fill: bytes = b"\x00") -> bytes:
    return blob + fill * (-len(blob) % 4)


def write_glb(path: Path, verts: np.ndarray, normals: np.ndarray, faces: np.ndarray) -> None:
    v = np.asarray(verts, dtype=np.float32)
    n = np.asarray(normals, dtype=np.float32)
    idx = np.asarray(faces, dtype=np.uint32).reshape(-1)

    bin_parts, views, accessors = [], [], []
    offset = 0

    def add_view(arr: np.ndarray, target: int) -> None:
        nonlocal offset
        raw = _pad4(arr.tobytes())
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": target})
        bin_parts.append(raw)
        offset += len(raw)

    add_view(v, 34962)          # ARRAY_BUFFER
    add_view(n, 34962)
    add_view(idx, 34963)        # ELEMENT_ARRAY_BUFFER

    accessors.append({
        "bufferView": 0, "componentType": 5126, "count": len(v), "type": "VEC3",
        "min": v.min(axis=0).tolist(), "max": v.max(axis=0).tolist(),
    })
    accessors.append({"bufferView": 1, "componentType": 5126, "count": len(n), "type": "VEC3"})
    accessors.append({
        "bufferView": 2, "componentType": 5125, "count": len(idx), "type": "SCALAR",
    })

    gltf = {
        "asset": {"version": "2.0", "generator": "JarvisAI/tools/export_face_mesh.py"},
        "scene": 0,
        "scenes": [{"name": "BihansaFace", "nodes": [0]}],
        "nodes": [{"name": "Face", "mesh": 0}],
        "meshes": [{
            "name": "Face",
            "primitives": [{
                "attributes": {"POSITION": 0, "NORMAL": 1},
                "indices": 2,
                "material": 0,
            }],
        }],
        "materials": [{
            "name": "HologramSkin",
            "doubleSided": True,
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.92, 0.72, 0.70, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.62,
            },
        }],
        "buffers": [{"byteLength": offset}],
        "bufferViews": views,
        "accessors": accessors,
    }

    json_chunk = _pad4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    bin_chunk = b"".join(bin_parts)
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(json_chunk), 0x4E4F534A))
        fh.write(json_chunk)
        fh.write(struct.pack("<II", len(bin_chunk), 0x004E4942))
        fh.write(bin_chunk)


def write_obj(obj_path: Path, mtl_path: Path, verts: np.ndarray, normals: np.ndarray, faces: np.ndarray) -> None:
    obj_path.parent.mkdir(parents=True, exist_ok=True)
    mtl_path.write_text(
        "newmtl HologramSkin\n"
        "Kd 0.92 0.72 0.70\n"
        "Ka 0.10 0.05 0.06\n"
        "Ks 0.15 0.15 0.15\n"
        "Ns 24\n"
        "illum 2\n",
        encoding="utf-8",
    )
    lines = [
        "# Bihansa face — measured with MediaPipe Face Mesh, subdivided.",
        "# Generated by JarvisAI/tools/export_face_mesh.py — do not edit by hand.",
        f"mtllib {mtl_path.name}",
        "o Face",
        "usemtl HologramSkin",
    ]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in verts]
    lines += [f"vn {x:.6f} {y:.6f} {z:.6f}" for x, y, z in normals]
    lines += [f"f {a + 1}//{a + 1} {b + 1}//{b + 1} {c + 1}//{c + 1}" for a, b, c in faces]
    obj_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_preview(path: Path, verts: np.ndarray, normals: np.ndarray, faces: np.ndarray,
                  size: int = 760) -> None:
    """Tiny software render (z-buffer + Lambert) so the model can be eyeballed
    on GitHub without opening a 3-D app. Needs pillow."""
    from PIL import Image

    def shot(yaw_deg: float, pitch_deg: float) -> np.ndarray:
        yaw, pitch = np.radians(yaw_deg), np.radians(pitch_deg)
        ry = np.array([[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0], [-np.sin(yaw), 0, np.cos(yaw)]])
        rx = np.array([[1, 0, 0], [0, np.cos(pitch), -np.sin(pitch)], [0, np.sin(pitch), np.cos(pitch)]])
        rot = rx @ ry
        v = verts @ rot.T
        n = normals @ rot.T
        s = size / (np.ptp(v[:, 1]) * 1.22)
        px = (v[:, 0] * s + size / 2).astype(int)
        py = (-v[:, 1] * s + size / 2).astype(int)
        pz = v[:, 2]
        img = np.zeros((size, size, 3), np.float32)
        zbuf = np.full((size, size), -1e9, np.float32)
        light = np.array([0.35, 0.45, 0.82])
        light /= np.linalg.norm(light)
        for tri in faces:
            xs, ys, zs = px[tri], py[tri], pz[tri]
            x0, x1 = max(0, int(xs.min())), min(size - 1, int(xs.max()))
            y0, y1 = max(0, int(ys.min())), min(size - 1, int(ys.max()))
            if x1 <= x0 or y1 <= y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
            ax, ay, bx, by, cx, cy = xs[0], ys[0], xs[1], ys[1], xs[2], ys[2]
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-9:
                continue
            w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
            w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
            w2 = 1 - w0 - w1
            mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not mask.any():
                continue
            zz = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
            sub = zbuf[y0:y1 + 1, x0:x1 + 1]
            upd = mask & (zz > sub)
            if not upd.any():
                continue
            sub[upd] = zz[upd]
            nrm = n[tri].mean(axis=0)
            length = np.linalg.norm(nrm)
            if not length:
                continue
            lam = max(0.10, float(np.dot(nrm / length, light)))
            img[y0:y1 + 1, x0:x1 + 1][upd] = np.clip(
                np.array([1.0, 0.66, 0.88]) * (0.26 + 0.9 * lam), 0, 1)
        return (np.clip(img, 0, 1) ** (1 / 1.05) * 255).astype(np.uint8)

    sheet = np.concatenate([shot(0, 0), shot(28, 3), shot(-32, -3)], axis=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(sheet).save(path)
    print(f"png  {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--height", type=float, default=FACE_HEIGHT_M, help="face height in metres")
    ap.add_argument("--density", type=float, default=0.60, help="subdivision target (matches the page)")
    ap.add_argument("--depth", type=int, default=2, help="max subdivision recursion")
    ap.add_argument("--preview", type=Path, default=None, help="also write a PNG render of the model")
    args = ap.parse_args()

    data = extract(args.source, max_depth=args.depth, density=args.density)
    verts, normals, faces = build_mesh(data, args.height)

    glb = args.outdir / "face.glb"
    obj = args.outdir / "face.obj"
    mtl = args.outdir / "face.mtl"
    write_glb(glb, verts, normals, faces)
    write_obj(obj, mtl, verts, normals, faces)

    size_cm = (verts.max(axis=0) - verts.min(axis=0)) * 100
    print(f"glb  {glb}  ({glb.stat().st_size / 1024:.0f} KB)")
    print(f"obj  {obj}  ({obj.stat().st_size / 1024:.0f} KB)")
    print(f"  {len(verts)} vertices / {len(faces)} triangles")
    print(f"  bounds  {size_cm[0]:.1f} x {size_cm[1]:.1f} x {size_cm[2]:.1f} cm")
    print("  axes: y-up, +Z towards the viewer, metre scale, centred on the origin")

    # the same geometry with a back grown on it, so it is a closed solid
    cverts, cnormals, cfaces = build_mesh(data, args.height, closed=True)
    cglb = args.outdir / "head.glb"
    write_glb(cglb, cverts, cnormals, cfaces)
    print(f"glb  {cglb}  ({cglb.stat().st_size / 1024:.0f} KB)  closed solid")

    if args.preview:
        # the open face is the artefact people usually want; preview that
        write_preview(args.preview, verts, normals, faces)


if __name__ == "__main__":
    main()
