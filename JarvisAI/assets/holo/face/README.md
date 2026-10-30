# Bihansa — neural wireframe hologram face

An interactive hologram face built **entirely from geometry**. There is no
photograph, no cut-out, no texture and no image file anywhere in this build: the
face on screen *is* her measured face — 478 Face-Mesh landmarks with their real
depth, subdivided into a dense lattice of ~2,500 points and ~7,300 synapses that
fills the whole face and turns in three dimensions.

Plain HTML + CSS + JS. No framework, no build step, no network calls.

```
face/
├── index.html                 the page
├── style.css                  projection, projector base, HUD chrome, scan layers
├── hologram.js                the 3D wireframe renderer + interaction + HUD
├── face_data.js               generated: subdivided landmark lattice, feature loops, depth
├── hologram-standalone.html   generated: everything in one 200 KB file
├── model/                     the Tripo3D PBR face + a viewer for it (see below)
└── source/                    the photographs the landmarks were measured from (build input only)
```

Nothing in `face/` is displayed as a picture. `source/` exists so the mesh can be
re-measured; it is not loaded by the page.

## Look at it

```bash
# from the repository root — anything that serves files will do
python -m http.server 8000 --bind 0.0.0.0 --directory JarvisAI/assets/holo/face
# open http://localhost:8000
```

Or just double-click `hologram-standalone.html`. Both work offline:
`hologram.js` is a classic script and the geometry is a `window.HOLO_FACE`
global, so `file://` CORS rules never bite.

## What it does

| Interaction | Effect |
| --- | --- |
| Move the cursor | Her head turns — yaw and pitch on the actual mesh, perspective included. The far cheek dims, the near cheek brightens |
| Click anywhere | A resonance wave rolls out through the lattice, then decays |
| `VOICE LINK` (or `V`) | Microphone level drives the filaments, the iris glow and the carrier waveform |
| `MESH` (or `M`) | Toggles the 1322 synapses and the feature loops |
| `HAIR` (or `H`) | Toggles the floating filaments |
| `PAUSE` | Freezes the rotation, so a frame can be studied |
| `R` | Recentres the view |
| `Space` / `P` | Fires a pulse |

She blinks. When nothing is happening the head idles on a slow sway and a
breath. With `prefers-reduced-motion` all of it settles to a still projection.

## Why it looks like *her*, and not like a generic head

The mesh is measured, not invented. `JarvisAI/tools/build_holo_face.py` runs
MediaPipe Face Mesh over the frontal reference and exports the raw geometry:

1. **478 landmarks**, each carrying `x`, `y` **and the real `z` depth** that
   MediaPipe estimates from the photo — nose tip at −0.102, chin at +0.032,
   a 0.333 span. That depth is the whole trick: it is what makes the head read
   as a solid object when it rotates instead of a flat drawing skewing.
2. **Subdivision.** The raw tessellation is only 1322 edges — a cage, not a
   face. The faces are recovered from the edge graph (a 3-clique is a triangle),
   then every triangle is split into four, recursively, until its area drops
   below a fraction of the median. Each new point's depth is interpolated from
   the triangle it belongs to, midpoints are shared between neighbours so the
   lattice stays welded, and the outer boundary never moves — it is still her
   measured jawline. Result: ~2,500 points, ~7,300 edges, uniform density.
3. **Feature loops** walked in contour order — the face oval, both eyelids, the
   outer lip. (A plain index-sorted set is *not* a contour: it draws a chord
   across her face, which is exactly the bug that had to be fixed.)
4. The page then scales y by `1 / aspect` (MediaPipe normalises to the photo
   rectangle, so undoing it keeps her proportions instead of stretching the
   face), centres the model, and renders it.

Rendering, in `hologram.js`:

* rotate (yaw → pitch) → perspective divide (`f / (f + z)`) → project;
* every edge is drawn additively, brightness and colour interpolated from its
  real depth — deep magenta at the back of the jaw, near-white at the nose;
* lines are grouped into 14 brightness buckets and stroked once per bucket, so
  the whole lattice costs about two dozen path calls a frame instead of 7,300;
* a quarter-resolution copy of the frame is blurred and added back for bloom;
* three faint shells behind the oval give the head a back;
* the hairline emits ~400 filaments: fine ones for the fuzzy crown, long ones
  that leave the oval, fall under gravity and float behind the jaw — geometry,
  animated by voice and time;
* quality adapts: if a frame runs long, the bloom pass is dropped first, then
  the landmark dots, so the rotation never stutters.

## The 3-D model (`model/`)

`model/` holds the real 3-D face — a Tripo3D PBR export of her, not geometry
we invented and not a render:

| File | What it is |
| --- | --- |
| `tripo_pbr_model_…_meshopt.glb` | 18 MB, 971k vertices / 1.84M triangles, PBR material with base-colour + normal maps. Compressed with `EXT_meshopt_compression` and `KHR_mesh_quantization`, so it needs a meshopt decoder to open |
| `view.html` | A viewer for that exact file — three.js, orbit controls, auto-rotate, wireframe and studio-light toggles |
| `vendor/` | three.js `r169` + `GLTFLoader` + `OrbitControls` + `BufferGeometryUtils` + `meshopt_decoder`, vendored so the viewer runs with no CDN and no network |

```bash
# module scripts and fetch() do not work over file://, so serve the folder
python -m http.server 8000 --bind 0.0.0.0 \
    --directory JarvisAI/assets/holo/face/model
# open http://localhost:8000/view.html
```

The decoder is the whole reason that page exists: GitHub shows a `.glb` as a
download, and most local viewers refuse a meshopt-compressed file. `view.html`
loads the meshopt WASM module, streams the 18 MB file with a progress bar, and
frames the model from its own bounding box (the export faces +X, so it is turned
90° to face the camera).

Heavy by design: 1.84M triangles is a desktop-GPU model. If you need it on a
phone or in a game engine, decimate it first —

```bash
npx @gltf-transform/cli optimize \
  tripo_pbr_model_*.glb face-lite.glb --simplify-ratio 0.15
```

## One file, no server (`hologram-standalone.html`)

```bash
python JarvisAI/tools/bundle_holo_face.py \
    --source JarvisAI/assets/holo/face \
    --out    JarvisAI/assets/holo/face/hologram-standalone.html
```

The bundle is pure text — HTML, CSS and two scripts, ~200 KB — because there is
no image to inline. Rebuild it after editing `style.css`, `hologram.js` or the
geometry. The folder stays the source of truth.

## Rebuilding the geometry

```bash
python -m pip install "mediapipe==0.10.14" numpy
python JarvisAI/tools/build_holo_face.py \
    --source JarvisAI/assets/holo/face/source/portrait_ref.jpg \
    --out    JarvisAI/assets/holo/face/face_data.js
```

`mediapipe==0.10.14` is pinned because later releases removed `mp.solutions`,
which is where the bundled face-mesh model lives — so the build runs fully
offline. It writes one file and prints the landmark, edge and depth statistics.

For a different face, drop a frontal, evenly lit photo into `source/`, point
`--source` at it and rebuild. The renderer needs no changes: it reads whatever
478 landmarks it is given.

## Status: standalone, deliberately not wired in

This is **not connected to JARVIS**. Nothing in `main.py`, `ui/`, `core/`,
`agent/` or `dashboard/` imports or references the page. The only project files
that mention it are the two build scripts in `JarvisAI/tools/`.

Keeping it detached is intentional for now — the hologram can be iterated on
without touching the Qt HUD or the app's start-up path. Wiring it in later would
be a deliberate `QWebEngineView` pointed at this folder, not something this
folder does on its own.

## Notes

* The geometry is derived from photographs of a real person. Keep `source/`
  only if you want to re-measure, and treat it as personal data in a fork.
* Paths are exercised headlessly two ways: a jsdom run of the real scripts with
  a mock canvas (boot, 240 frames, every control — 0 errors), and a Node run
  against a real `@napi-rs/canvas` backend that rasterises the frame for review.
