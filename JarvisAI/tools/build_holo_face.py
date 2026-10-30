"""Build the holographic face assets used by ``assets/holo/face/``.

The web hologram must show *her actual face*, so the 3D-looking result is baked
from a real portrait rather than generated procedurally:

* ``portrait.png``      – alpha cut-out of the photo, graded as a pink
                          hologram projection (skin kept natural, hair lit with
                          neon strands, thin rim light on the silhouette).
* ``hair_left.png`` /
  ``hair_right.png``    – hair-only layers, split at the parting so the page can
                          sway each side independently ("floating hair").
* ``face_data.js``      – the 478 MediaPipe Face Mesh landmarks measured on the
                          photo, the tessellation edges, iris anchors and the
                          hair-strand seeds consumed by ``hologram.js``.

Everything runs offline: MediaPipe ships the face-mesh and selfie-segmentation
models inside the wheel, and OpenCV refines the matte with GrabCut.

Usage::

    python JarvisAI/tools/build_holo_face.py \
        --source JarvisAI/assets/holo/face/source/portrait_ref.jpg \
        --outdir JarvisAI/assets/holo/face

Requires ``mediapipe==0.10.14`` (the last release exposing ``mp.solutions``)
plus ``opencv-python-headless`` and ``numpy``. It is a build-time tool: the app
itself never imports it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.python.solutions import face_mesh_connections as FMC

# ── tuning ───────────────────────────────────────────────────────────────────
UPSCALE = 2.0          # 649x1077 -> ~1300x2154, keeps the HUD crisp on HiDPI
EXPOSURE = 1.18        # >1 deepens the blacks so it reads as projected light
BRIGHTNESS = 0.94
TINT = (0.99, 0.95, 1.10)   # cool violet projection bias (R, G, B)
HAIR_GAIN = 3.0        # high-pass gain for the fibre-optic hair strands
RIM_GAIN = 1.30
RIM_SIGMA = 4.5
MAX_HAIR_SEEDS = 210
MIN_HAIR_SEED_GAP = 11  # px in source space

# Face Mesh landmark indices we expose to the page.
IRIS_RIGHT, IRIS_LEFT = 468, 473
FACE_OVAL = sorted({i for edge in FMC.FACEMESH_FACE_OVAL for i in edge})
LEFT_EYE_RING = sorted({i for edge in FMC.FACEMESH_LEFT_EYE for i in edge})
RIGHT_EYE_RING = sorted({i for edge in FMC.FACEMESH_RIGHT_EYE for i in edge})
LIPS = sorted({i for edge in FMC.FACEMESH_LIPS for i in edge})


def _largest_component(mask: np.ndarray) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return mask
    keep = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (labels == keep).astype(np.uint8) * 255


def person_matte(bgr: np.ndarray, luma: np.ndarray) -> np.ndarray:
    """Soft alpha for the person: GrabCut, then grow into the dark hair."""
    h, w = bgr.shape[:2]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    seg = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=0)
    prob = seg.process(rgb).segmentation_mask
    seg.close()

    seed = np.zeros((h, w), np.uint8)
    seed[prob > 0.6] = cv2.GC_PR_FGD
    seed[prob < 0.15] = cv2.GC_BGD
    seed[prob > 0.9] = cv2.GC_FGD
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, seed, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    hard = ((seed == cv2.GC_FGD) | (seed == cv2.GC_PR_FGD)).astype(np.uint8) * 255
    hard = cv2.morphologyEx(hard, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    hard = _largest_component(hard)

    # GrabCut under-cuts very dark hair. Grow only into dark pixels that stay
    # close to the confirmed matte, and never in the top band of the frame where
    # a shadowed wall could be absorbed.
    dark = (luma < 0.32).astype(np.uint8) * 255
    dark[: int(h * 0.16), :] = 0
    reach = cv2.dilate(hard, np.ones((61, 61), np.uint8))
    for _ in range(12):
        grow = cv2.dilate(hard, np.ones((5, 5), np.uint8))
        hard = cv2.bitwise_or(hard, cv2.bitwise_and(cv2.bitwise_and(grow, dark), reach))
        reach = cv2.dilate(hard, np.ones((41, 41), np.uint8))

    filled = hard.copy()
    cv2.floodFill(filled, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 255)
    hard = cv2.bitwise_or(hard, cv2.bitwise_not(filled))
    hard = cv2.morphologyEx(hard, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    hard = cv2.medianBlur(hard, 5)

    soft = cv2.GaussianBlur(hard, (5, 5), 1.2).astype(np.float32) / 255.0
    return np.clip((soft - 0.18) / 0.82, 0, 1)


def face_mesh(bgr: np.ndarray):
    h, w = bgr.shape[:2]
    mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=True,
        min_detection_confidence=0.3,
    )
    result = mesh.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    mesh.close()
    if not result.multi_face_landmarks:
        raise SystemExit("No face found — pick a more frontal portrait.")
    pts = np.array([(p.x * w, p.y * h) for p in result.multi_face_landmarks[0].landmark])
    return pts


def grade(rgb: np.ndarray, mask: np.ndarray, face_hull: np.ndarray, hair: np.ndarray) -> np.ndarray:
    luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    out = np.clip((rgb - 0.5) * 1.06 + 0.47, 0, 1)
    out = (out ** EXPOSURE) * BRIGHTNESS
    out = out * np.array(TINT, np.float32)

    # Take a little pigment out of the skin so it reads as light on a face.
    skin = face_hull[..., None]
    out = out * (1 - skin * 0.18) + (out * 0.82 + luma[..., None] * 0.18) * skin * 0.18

    # Fibre-optic hair: local bright ridges become magenta filaments.
    ridges = np.clip(luma - cv2.GaussianBlur(luma, (0, 0), 9), 0, 1) * HAIR_GAIN
    ridges = cv2.GaussianBlur(ridges, (0, 0), 1.1)
    strand = np.clip(ridges, 0, 1)[..., None]
    neon = np.array([1.0, 0.22, 0.78], np.float32)
    mix = hair[..., None] * 0.40
    out = np.clip(out * (1 - mix) + (out * 0.30 + neon * strand * 1.45) * mix, 0, 1)

    # Thin rim light along the silhouette.
    rim = np.clip(mask - cv2.erode(mask, np.ones((5, 5), np.uint8)), 0, 1)
    rim = cv2.GaussianBlur(rim, (0, 0), RIM_SIGMA)
    out = np.clip(out + np.clip(rim * RIM_GAIN, 0, 1)[..., None] * np.array([0.80, 0.05, 0.55]), 0, 1)

    # Bloom only from genuinely bright pixels (face highlight, earring).
    bright = np.clip(((0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2]) - 0.62) * 1.5, 0, 1)
    out = np.clip(out + cv2.GaussianBlur(out * (bright * mask)[..., None], (0, 0), 9) * 0.55, 0, 1)
    return out


def _poisson(points: np.ndarray, gap: float, limit: int, seed: int = 7) -> list[tuple[int, int]]:
    """Cheap Poisson-disk sampling: shuffle the candidates, keep well-spaced ones."""
    if len(points) == 0 or limit <= 0:
        return []
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(points))
    picked: list[tuple[int, int]] = []
    taken = np.empty((0, 2), np.float32)
    for idx in order:
        p = points[idx].astype(np.float32)
        if len(taken) and np.min(np.sum((taken - p) ** 2, axis=1)) < gap * gap:
            continue
        picked.append((int(p[0]), int(p[1])))
        taken = np.vstack([taken, p])
        if len(picked) >= limit:
            break
    return picked


def hair_seeds(hair: np.ndarray, mask: np.ndarray, crown: tuple[float, float]) -> list[dict]:
    """Strand origins along the hair silhouette, each with a true outward normal.

    Seeding the *interior* of the hair mass made filaments shoot across her face;
    the boundary is where hair actually lifts off, so that is what we sample. A
    handful of crown strands are added so the top of the head breathes upward.
    """
    h, w = hair.shape
    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 6)
    gx = cv2.Sobel(soft, cv2.CV_32F, 1, 0, ksize=5)
    gy = cv2.Sobel(soft, cv2.CV_32F, 0, 1, ksize=5)
    mag = np.hypot(gx, gy) + 1e-6
    nx, ny = -gx / mag, -gy / mag          # the matte falls off outward, so flip

    edge = mag > 0.02
    ys, xs = np.nonzero(edge & (hair > 0.45) & (np.arange(h)[:, None] < h * 0.72))
    rim_pts = np.stack([xs, ys], axis=1) if len(xs) else np.empty((0, 2))
    chosen = _poisson(rim_pts, MIN_HAIR_SEED_GAP * 0.8, MAX_HAIR_SEEDS)

    rng = np.random.default_rng(3)
    seeds = []
    cx, cy = crown
    for x, y in chosen:
        dx, dy = float(nx[y, x]), float(ny[y, x])
        # filaments leave the silhouette, then the projection field lifts them
        ox, oy = dx * 0.78, dy * 0.78 - 0.5
        n = (ox * ox + oy * oy) ** 0.5 or 1.0
        seeds.append({
            "x": round(x / w, 5),
            "y": round(y / h, 5),
            "dx": round(ox / n, 3),
            "dy": round(oy / n, 3),
            "l": round(0.018 + 0.055 * float(rng.random()), 4),
        })

    # crown lift: a few strands rising straight off the top of the head
    top = [(x, y) for x, y in zip(xs.tolist(), ys.tolist())
           if y < cy + 0.06 * h and abs(x - cx) < 0.22 * w]
    for x, y in _poisson(np.array(top) if top else np.empty((0, 2)), 9, 26, seed=23):
        seeds.append({
            "x": round(x / w, 5),
            "y": round(y / h, 5),
            "dx": round(float(rng.normal(0, 0.25)), 3),
            "dy": -1.0,
            "l": round(0.02 + 0.05 * float(rng.random()), 4),
        })
    return seeds


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--outdir", required=True, type=Path)
    ap.add_argument("--keep-png", action="store_true",
                    help="also write the intermediate PNGs (large, for inspection)")
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    bgr = cv2.imread(str(args.source), cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit(f"Cannot read {args.source}")
    h, w = bgr.shape[:2]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]

    pts = face_mesh(bgr)
    mask = person_matte(bgr, luma)

    hull = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(hull, cv2.convexHull(pts.astype(np.int32)), 255)
    face_hull = cv2.GaussianBlur(hull, (31, 31), 9).astype(np.float32) / 255.0

    hair = ((luma < 0.36) & (mask > 0.4) & (face_hull < 0.5)).astype(np.float32)
    hair = cv2.GaussianBlur(hair, (11, 11), 4.0) * mask

    out = grade(rgb, mask, face_hull, hair)

    scale = UPSCALE
    big_nn = lambda arr: cv2.resize(arr, (int(round(w * scale)), int(round(h * scale))),
                                    interpolation=cv2.INTER_NEAREST)

    colour8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    colour_big = cv2.resize(colour8, (int(w * scale), int(h * scale)),
                            interpolation=cv2.INTER_LANCZOS4)
    # One gentle unsharp pass, otherwise LacZos on a 649 px source looks mushy.
    blur = cv2.GaussianBlur(colour_big, (0, 0), 1.2)
    colour_big = np.clip(colour_big.astype(np.float32) * 1.35 - blur.astype(np.float32) * 0.35, 0, 255)

    alpha_big = big_nn(mask)
    rgba = np.dstack([colour_big.astype(np.uint8), (np.clip(alpha_big, 0, 1) * 255).astype(np.uint8)])
    layers: dict[str, np.ndarray] = {"portrait": rgba}
    if args.keep_png:
        cv2.imwrite(str(args.outdir / "portrait.png"), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))

    # ── hair split at the parting, with a soft seam so the sway never gaps ────
    part_x = float(np.median(pts[LIPS][:, 0])) if len(LIPS) else w / 2
    left_w = np.zeros((h, w), np.float32)
    right_w = np.zeros((h, w), np.float32)
    band = max(18.0, w * 0.035)
    for y in range(h):
        # the parting drifts slightly with the head; keep it a simple vertical seam
        xs = np.arange(w, dtype=np.float32)
        t = np.clip((xs - (part_x - band)) / (2 * band), 0, 1)
        left_w[y, :] = 1 - t
        right_w[y, :] = t

    for name, weight in (("hair_left", left_w), ("hair_right", right_w)):
        hm = np.clip(hair * weight, 0, 1)
        hm_big = cv2.resize(hm, (colour_big.shape[1], colour_big.shape[0]), interpolation=cv2.INTER_LINEAR)
        a = (np.clip(hm_big, 0, 1) * np.clip(alpha_big, 0, 1) * 255).astype(np.uint8)
        layers[name] = np.dstack([colour_big.astype(np.uint8), a])
        if args.keep_png:
            cv2.imwrite(str(args.outdir / f"{name}.png"),
                        cv2.cvtColor(layers[name], cv2.COLOR_RGBA2BGRA))

    # ── face mesh data ───────────────────────────────────────────────────────
    crown = (float(pts[:, 0].mean()), float(pts[:, 1].min()) - 0.04 * h)
    norm = [[round(float(x) / w, 5), round(float(y) / h, 5)] for x, y in pts]
    data = {
        "width": int(colour_big.shape[1]),
        "height": int(colour_big.shape[0]),
        "crown": [round(crown[0] / w, 4), round(crown[1] / h, 4)],
        "points": norm,
        "edges": sorted({tuple(sorted((int(a), int(b)))) for a, b in FMC.FACEMESH_TESSELATION}),
        "faceOval": FACE_OVAL,
        "leftEye": LEFT_EYE_RING,
        "rightEye": RIGHT_EYE_RING,
        "lips": LIPS,
        "iris": {"left": IRIS_LEFT, "right": IRIS_RIGHT},
        "anchors": {
            "forehead": 10, "chin": 152, "nose": 1, "mouth": 13,
            "eyeL": IRIS_LEFT, "eyeR": IRIS_RIGHT,
        },
        "hairSeeds": hair_seeds(hair, mask, crown),
    }

    js = "// Generated by JarvisAI/tools/build_holo_face.py — do not edit by hand.\n"
    js += "window.HOLO_FACE = " + json.dumps(data, separators=(",", ":")) + ";\n"
    (args.outdir / "face_data.js").write_text(js, encoding="utf-8")

    # WebP keeps the alpha and is ~25x smaller than PNG here (104 KB vs 2.6 MB),
    # so only WebP is written. `exact=True` preserves colour under transparent
    # pixels, which the hair overlays need when they sway out of alignment.
    from PIL import Image

    for name, arr in layers.items():
        # `layers` are already RGBA (colour came from an RGB array via dstack) —
        # converting BGRA->RGBA here swapped red and blue and shipped a blue face.
        img = Image.fromarray(np.ascontiguousarray(arr), mode="RGBA")
        img.save(args.outdir / f"{name}.webp", "WEBP", quality=92, method=6, exact=True)

    print(f"portrait  : {colour_big.shape[1]}x{colour_big.shape[0]}")
    print(f"mesh      : {len(data['points'])} landmarks, {len(data['edges'])} edges")
    print(f"hair seeds: {len(data['hairSeeds'])}")
    print(f"written to: {args.outdir}")


if __name__ == "__main__":
    main()
