"""Export the standard JARVIS head (core/avatar_mesh.py) for the web hologram.

The mesh is derived from MediaPipe's canonical face model (Apache-2.0, see core/face_model.obj).
Run from the repository root:  python scripts/export_head_mesh.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.core.avatar_mesh import JAW_MAX, JAW_PIVOT, get_head_mesh  # noqa: E402


def r(a, n=4):
    return np.round(np.asarray(a, dtype=float), n).tolist()


def main() -> None:
    m = get_head_mesh(sculpt=False)
    lm = m["landmarks"]
    v = m["verts"]
    out = {
        "source": "MediaPipe canonical_face_model.obj (Apache-2.0) via jarvis/core/avatar_mesh.py",
        "verts": r(v.reshape(-1)),
        "faces": m["faces"].reshape(-1).tolist(),
        "edges": m["edges"].reshape(-1).tolist(),
        "jaw": r(m["jaw"]),
        "lips": r(m["lips"]),
        "brow": r(m["brow"]),
        "fade": r(m["fade"]),
        "jawMax": float(JAW_MAX),
        "jawPivot": list(map(float, JAW_PIVOT)),
        "lipCentre": r(m["lip_centre"]),
        "eyeL": r(v[lm["eye_l"]].mean(0)),
        "eyeR": r(v[lm["eye_r"]].mean(0)),
        "eyeLRing": lm["eye_l"].tolist(),
        "eyeRRing": lm["eye_r"].tolist(),
        "lipsIn": lm["lips_in"].tolist(),
        "span": list(map(float, m["span"])),
    }
    dest = ROOT / "frontend" / "src" / "hologram" / "headMesh.json"
    dest.write_text(json.dumps(out, separators=(",", ":")))
    print("wrote", dest.relative_to(ROOT), dest.stat().st_size, "bytes;", len(v), "verts,", len(m["faces"]), "faces")
    print("eyeL", out["eyeL"], "eyeR", out["eyeR"], "jawPivot", out["jawPivot"])


if __name__ == "__main__":
    main()
