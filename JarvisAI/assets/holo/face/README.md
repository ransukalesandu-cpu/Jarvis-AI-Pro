# Bihansa — neural hologram face (web)

An interactive, self-contained hologram built from the real portrait: her actual
face, her actual hair, wrapped in a live 478-point face mesh, floating
filaments, a projector base and a HUD. Plain HTML + CSS + JS — no framework, no
build step, no network calls.

```
face/
├── index.html        the page
├── style.css         projection, hair sway, HUD chrome
├── hologram.js       mesh / filaments / eyes / telemetry / voice engine
├── face_data.js      generated: 478 landmarks + 1322 edges + 236 hair seeds
├── portrait.webp     generated: alpha cut-out, hologram-graded (104 KB)
├── hair_left.webp    generated: left hair lock, sways on its own
├── hair_right.webp   generated: right hair lock
├── refs/             the three reference captures shown in the left rail
└── source/           the original photographs the assets were built from
```

## Look at it

```bash
# from the repository root — anything that serves files will do
python -m http.server 8000 --bind 0.0.0.0 --directory JarvisAI/assets/holo/face
# open http://localhost:8000
```

Opening `index.html` directly from disk also works: the scripts are classic
(non-module) scripts and the data is a `window.HOLO_FACE` global, so nothing is
blocked by `file://` CORS rules.

## What it does

| Interaction | Effect |
| --- | --- |
| Move the cursor | The whole figure tilts in 3D; her eyes follow the pointer; the HUD rails drift against it |
| Click anywhere on her | A resonance pulse expands through the body and the filaments spike |
| `VOICE LINK` (or `V`) | Requests the microphone; the projection breathes, the filaments stretch and the carrier waveform follows your voice |
| `MESH` (or `M`) | Toggles the face mesh |
| `HAIR` (or `H`) | Toggles the floating hair |
| `PULSE` (or `Space` / `P`) | Fires a pulse from the projector base |

Everything degrades politely: without a microphone the hologram idles on a slow
breath; with `prefers-reduced-motion` the parallax and sweeps are switched off.

## Why it looks like *her*

The face is not generated procedurally. `JarvisAI/tools/build_holo_face.py`
measures the real photo and the page draws those measurements:

1. **MediaPipe Face Mesh** finds 478 landmarks on the portrait. Their exact
   positions drive the wireframe, the eye-tracking glows and the feature rings,
   so the mesh sits on her eyes, nose and lips rather than approximating them.
2. **Selfie segmentation + GrabCut + a dark-hair growth pass** produce the alpha
   matte, which is what lets the plate sit on black with no rectangle behind it.
3. The cut-out is **graded as a projection**: blacks deepened, a violet bias, a
   thin rim light on the silhouette, and a high-pass filter over the hair that
   turns its bright ridges into magenta filaments.
4. Hair is **split at the parting** into two layers, so each side can sway with
   its own phase and amplitude — the "floating hair" is the real hair moving, not
   an added effect floating nearby.

## Rebuilding the assets

```bash
python -m pip install "mediapipe==0.10.14" opencv-python-headless pillow numpy
python JarvisAI/tools/build_holo_face.py \
    --source JarvisAI/assets/holo/face/source/portrait_ref.jpg \
    --outdir JarvisAI/assets/holo/face
```

`mediapipe==0.10.14` is pinned because later releases removed `mp.solutions`,
which is where the bundled face-mesh and selfie-segmentation models live — the
build therefore runs completely offline. The script writes only WebP (≈390 KB
for all three layers); pass `--keep-png` if you want the lossless intermediates.

To use a different portrait, drop it in `source/` and point `--source` at it.
A frontal, evenly lit photo with the hair clear of the background works best.

## Using it inside JARVIS

The page has no external dependencies, so it can be loaded straight into the
Qt WebEngine HUD as the hologram surface, e.g. pointing a `QWebEngineView` at
`QUrl.fromLocalFile(.../assets/holo/face/index.html)`. The microphone button is
optional and can be removed if the HUD owns the audio session.

## Notes

* Assets are generated from photographs of a real person. Keep
  `source/` alongside the derived files if you want to rebuild, and treat the
  portrait as personal data when publishing a fork.
* Tested paths: `hologram.js` is executed against a jsdom document with a mock
  2D canvas (boot sequence, 240 animation frames, every control) with no errors.
