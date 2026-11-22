# Cybernetic Hologram Engine V2: architecture report and phased plan

Status: **Phase 0 (inspection and plan). No renderer code changes in this PR.**
Visual reference: [`reference.jpg`](reference.jpg). It shows a dark metallic android head with orange emissive circuit engravings, blue chip modules in the forehead, blue nose structure, burning orange eyes, ears, a circuit-engraved neck and shoulders, and a cyan circuit background with orange sparks.

Base: this plan builds on the web hologram in PR #289, which is stacked on #286. Neither is merged yet; see the decisions at the end.

---

## 1. What exists today (inspected, not assumed)

### 1.1 Web renderer (primary), `frontend/src/hologram/`, about 1.1k lines
| File | Role |
|---|---|
| `HologramScene.tsx` | R3F `<Canvas>` (Three r187, WebGL2), `FitCamera` (fits fixed world bounds to any window), fixed `dpr={[1,2]}`, three scene lights |
| `Head.tsx` | Head mesh (810 verts), jaw driven by output audio level, blink, gaze, depth pre-pass, fat traces (`LineSegments2`), vias, running current |
| `shape.ts` | Re-proportions the MediaPipe mesh to the reference (dome, jaw, neck) |
| `faceCircuit.ts` | Landmark-designed, mirrored circuit traces; contours; neck runs |
| `glass.ts` | Fresnel "glass" `ShaderMaterial`, twinkle points shader, seeded RNG |
| `Eye.tsx` | Shader eye (iris fibres, dilating pupil, glint, scan ring) |
| `FaceData.tsx` | Forehead chips: live CPU/RAM drawn to a `CanvasTexture` |
| `Ears.tsx` | Glass ears with rim lines |
| `Stage.tsx` | Strands neck→orb, glass orb, backdrop (blue circuits, sparks, rings), **unused `Plexus`** |
| `palette.ts` | Orange/blue palette, `orbColor(state)` |
| `headMesh.json` | Exported by `scripts/export_head_mesh.py` from `jarvis/core/avatar_mesh.py` (MediaPipe canonical face, Apache-2.0, plus generated skull and neck) |

Tests: `faceCircuit.test.ts` (mirror map, mesh paths, symmetry, neck, chips, shape). There are no WebGL or shader compile tests.

### 1.2 Classic renderer (fallback): Python, PyQt6 `QPainter`, NumPy, about 4.6k lines
`jarvis/core/avatar.py` (`HoloAvatar`, looks: cyber, volume, image), `avatar_image.py` (photo hologram with warp lip-sync and emotions), `avatar_volume.py`, `avatar_mesh.py`, `ui/hologram/stage.py` (heart, orb, five wires), `ui/hologram/neural_heart_reactor.py`, `animation_engine.py`, `bihansa_hologram.py`, `wireframe_head.py`. It is painted inside `HudCanvas` (`jarvis/ui/__init__.py`). It is the **default UI**; the web UI is opt-in with `JARVIS_UI=web`.

### 1.3 Desktop integration
`jarvis/webui/`: `host.py` (`QWebEngineView` + `QWebChannel`), `bridge.py`, `contract.py` mirrored by `frontend/src/bridge/contract.ts` (closed, versioned event and request sets), and `live.py` (ui_state bus → page). Events relevant here:

| Need (spec §9) | Exists? | Where |
|---|---|---|
| Assistant state | yes | `assistant.state_changed`: idle, sleeping, listening, thinking, searching, executing, speaking, error |
| Warning state | **no** | — (spec §8 asks for WARNING) |
| Voice activity / amplitude | partly | `assistant.audio_level` with `source` input/output, but `live.py` **only ever sends `output`** |
| Execution progress | yes (PR #286) | `task.flow` (steps, status), core `task_flow.py` |
| Performance configuration | yes | `ui.perf` tier `full / balanced / lite` + control actions `perf_*` |

### 1.4 Problems found
1. **The orb's listening reaction is dead.** `Orb` reads `inputLevel` while listening, but the host never sends input levels, so it is always 0.
2. **No WebGL check and no fallback.** If WebGL2 fails, the page shows nothing; nothing tells Python to fall back to the classic HUD.
3. **Perf tier ignored by the web hologram.** It uses a fixed DPR, has no frame throttling when hidden or minimised, and runs the same effects on every machine.
4. **Waste:** `Head.tsx` creates a twinkle `nodes` material and updates it every frame but never renders it. `Stage.Plexus` is dead code. The three scene lights do nothing, because every hologram material is unlit (`ShaderMaterial` / `MeshBasicMaterial`).
5. **Speech "sync" is amplitude-only.** This is honest (spec §8: do not invent phoneme sync), and it must stay that way.
6. **Abandoned work:** `hologram-v2/engine` and `hologram-v2/phase1-audit` (the owner paused that engine) vendor their own `three.module.min.js`, `holo.html` and MediaPipe `.task` files outside the frontend build. **Do not revive.** About 10 stale `feat/*hologram*` branches exist and are not part of `main`.
7. Legacy `hud_main.py` / `wireframe_head.py` load only from `windows_setup`. Leave them alone (spec §12: avoid legacy UI changes).

### 1.5 Constraints this environment cannot meet (stated up front)
- **No Blender here.** I cannot author a sculpted GLB. See decision D1.
- **No Windows / QWebEngine here.** Desktop integration, QWebChannel round trips, real FPS, CPU and GPU memory must be measured on the owner's machine. Headless Chromium uses SwiftShader (CPU rasteriser), whose numbers are **not** representative and will be labelled as such.

---

## 2. Target architecture

```
frontend/src/hologram/
  engine/            renderer core (no React): quality profiles, frame scheduler, resource registry
    quality.ts       Ultra / Balanced / Eco  <-> host tiers full / balanced / lite
    scheduler.ts     pause when hidden, adaptive DPR, frame-time budget
    resources.ts     dispose-on-unmount registry
    capability.ts    WebGL2 probe -> report to host (fallback trigger)
    perf.ts          FPS, frame ms, draw calls, JS heap -> optional overlay + host report
  shaders/           GLSL chunks, one concern each, composed by materials
    fresnel.glsl  circuitFlow.glsl  scanlines.glsl  surfacePulse.glsl
    eyeEmission.glsl  glitch.glsl  displacement.glsl
  materials/         typed factories with configurable params
    titanium.ts  blackChrome.ts  carbon.ts  emissiveCircuit.ts  holoSurface.ts  holoOverlay.ts
  face/              mechanical face parts (geometry builders + components)
    panels.ts (forehead plates, cheekbones, chin)  jaw.ts  sockets.ts  nose.ts  neck.ts  shoulders.ts
    engravings.ts (existing faceCircuit.ts moves here)  Eyes.tsx  FaceData.tsx  Ears.tsx
  energy/            Orb.tsx  Heart.tsx  Connections.tsx (animated arcs)  Particles.tsx (GPU)  Backdrop.tsx
  anim/              stateMachine.ts (7 states, timed transitions)  audio.ts (amplitude smoothing)
  HologramScene.tsx  composition only
```
Rules: typed interfaces everywhere; no file over about 300 lines; every GPU resource registered for disposal; React only at the composition layer. Geometry and math stay pure and unit-tested.

### 2.1 Mechanical face (decision D1 picks the source)
- **D1-A (recommended): procedural, in code.** Build on the existing reshaped head. Panelise the surface by landmark regions (forehead plates, temple, cheekbone, jaw, chin, nose bridge), extrude each panel slightly with a bevel, and leave **real grooves** between them. The emissive circuits sit in the grooves, so the engravings are geometry, not texture. The jaw becomes a **separate part** hinged at the existing pivot (it moves as one piece; no vertex skinning of the face). Eye sockets become recessed rings with a mechanical iris (aperture blades) inside. The neck gets ring segments; shoulders are optional, behind a flag, because they collide with the orb and strands. Facial identity stays neutral, because it comes from the MediaPipe canonical face.
- **D1-B: authored GLB.** A Blender model (made or licensed by the owner) goes through a pipeline using `gltf-transform` (dev-only dependency): Meshopt plus KTX2. It is loaded with Three's own `GLTFLoader`, `MeshoptDecoder` and `KTX2Loader` (no new runtime dependency; the Basis transcoder wasm, about 0.5 MB, is copied into `dist`). Named nodes (`jaw`, `eye_L`, `circuits_*`, …) map onto the same components.
- A + B: A ships first; the loader path is added later behind the same component interfaces when a GLB exists.

### 2.2 Materials
`MeshPhysicalMaterial`-based **titanium**, **black chrome** and **carbon** (procedural weave normal map, generated once), lit by a `RoomEnvironment` PMREM env map (built into Three, nothing downloaded) plus one key and one rim light. These become the first lit materials, so the scene lights become meaningful. **Emissive circuit** (orange, flowing energy via `circuitFlow`) and **holo surface/overlay** (cyan, fresnel, scanlines) are `ShaderMaterial`s composed from the chunks. Every material takes a typed params object, so palettes and personas can swap them.

### 2.3 Effects and cost control
Selective bloom uses `EffectComposer` + `UnrealBloomPass` from `three/examples` with a bloom layer (only emissives bloom). **Ultra only by default.** Balanced uses a cheap additive halo (as today); Eco has no post-processing. Glitch is rare and short, and off in Eco and in *Reduce motion*. GPU particles use one `Points` draw with all motion in the vertex shader (no per-frame CPU work).

### 2.4 Quality profiles (map to the existing host tiers, no second system)
| | Ultra (`full`) | Balanced (`balanced`) | Eco (`lite`) |
|---|---|---|---|
| DPR | up to 2, adaptive | 1–1.5, adaptive | 1 |
| Bloom | selective | halo only | none |
| Particles | 3k | 1k | 200 |
| Traces | fat + halo | fat | thin |
| Target | 60 fps | 60 fps | 30 fps cap |
All profiles pause when the window is hidden or minimised (`document.visibilityState` + host minimise event), and drop DPR when the frame time exceeds budget for 2 s.

### 2.5 Protocol (bridge contract additions, Python + TS, closed sets as today)
- `assistant.state_changed`: add **`warning`**. Python decides when (for example, approval needed or a degraded provider); the page only shows it.
- `assistant.audio_level`: `live.py` also sends **`input`** while listening. This fixes problem 1, at the same 20 Hz cap.
- `hologram.capability` (page → host request): `{webgl2: bool, renderer: str}`. The host falls back to the classic HUD when false.
- `hologram.perf` (page → host, every 5 s, Ultra/Balanced only when the overlay is on): `{fps, frameMs, drawCalls, heapMb}`. Python adds the `QtWebEngineProcess` CPU and RAM from psutil for one combined report.
- Execution progress: reuse `task.flow` (PR #286). Eye scan speed and orb rings follow the running step.

### 2.6 State animation
One `stateMachine.ts` handles the 7 spec states (IDLE, LISTENING, THINKING, SPEAKING, EXECUTING, WARNING, ERROR; `searching` maps to THINKING and `sleeping` to IDLE-dim). Each state is a typed target set (eye glow, iris aperture, circuit flow speed and hue, orb colour and spin, particle rate, glitch chance) with eased transitions (250–600 ms). Audio amplitude only modulates (jaw, glow, orb size). There is **no phoneme lip-sync**.

### 2.7 Classic fallback
Unchanged renderer. It shares **configuration**: a JSON palette and state map in `jarvis/config/hologram_theme.json` read by both. The classic renderer cannot use GLB/WebGL assets; that is stated, not hidden. It activates when (a) `JARVIS_UI` is not `web`, (b) the page reports no WebGL2, or (c) the page fails to load within the existing timeout.

---

## 3. Phases (one focused PR each; the existing suites run before and after)

| # | Phase | Ships | Tests (actually run) |
|---|---|---|---|
| 0 | **This report** | docs only | — |
| 1 | Foundation | `engine/` (quality, scheduler, capability, resources, perf overlay), shader chunk library, contract additions (`warning`, input level, capability, perf), dead-code removal, fixes for problems 1–4 | vitest; headless WebGL shader-compile test for every chunk; Python contract and live-bridge tests |
| 2 | Mechanical face | panels and grooves, separate hinged jaw, sockets, nose, chin, neck rings, engravings in grooves, PBR materials | geometry unit tests (watertight panels, symmetric, jaw hinge); render smoke test |
| 3 | Mechanical eyes | aperture iris geometry + emission shader, independent L/R control, state reactions | uniform/state mapping tests |
| 4 | Neural energy | orb v2, quantum heart (left), animated arcs face↔heart↔orb, GPU particles, cyan circuit background | draw-call budget test per profile |
| 5 | Animation and post | state machine (7 states), audio modulation, selective bloom (Ultra), glitch | state-transition tests; audio smoothing tests |
| 6 | Integration and fallback | WebGL probe → classic fallback, shutdown cleanup, shared theme JSON, optional GLB loader path | Python host tests (fallback switch); dispose test (no leaked GPU objects) |
| 7 | Measure and tune | real numbers from the owner's Windows machine via the perf overlay + report | owner runs; results recorded in this doc |

Each phase is self-contained, keeps the current hologram working until its replacement is validated, and does not touch the legacy main UI.

## 4. Decisions needed from the owner
- **D1. Face source:** A (procedural, recommended, starts now) or B (Blender GLB; who makes or provides the model?).
- **D2. Quantum heart:** the spec puts it on the left, but the reference image has none, and an earlier request removed it. Add it back (behind a toggle)?
- **D3. Shoulders:** they collide with the orb and strands under the neck. Keep the orb and leave shoulders off, or add shoulders and move the orb?
- **D4. Base branch:** merge #286 and #289 first (recommended), or keep stacking V2 on top of them?
