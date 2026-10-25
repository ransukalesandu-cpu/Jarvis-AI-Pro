# Bihansa 3D Neural Face — implementation brief for Jules

## Goal
Upgrade the opt-in Bihansa mode from a 2D portrait with decorative overlays into the strongest practical portrait-derived 3D-style neural wireframe face possible, while preserving the source portrait and existing JARVIS mode.

## Existing state
- UI widget: `JarvisAI/ui/hologram/bihansa_hologram.py`
- HUD integration: `JarvisAI/ui/hud_main.py`
- Reference asset expected at: `JarvisAI/assets/bihansa_reference.png`
- Existing generic 3D wireframe widget: `JarvisAI/ui/hologram/wireframe_head.py`
- Dependencies include PyQt6 and numpy. Avoid breaking the existing app or requiring a GPU.

## Required implementation
1. Inspect the complete repository and current Bihansa PR before editing. Confirm the reference asset exists and loads from any working directory.
2. Build a dedicated portrait-derived face mesh:
   - Prefer a maintained facial-landmark/face-mesh solution if compatible with the project's Python versions and platform support. If introducing MediaPipe or another large dependency, make it optional and document installation/fallback behavior.
   - Extract facial landmarks from the reference image (eyes, brows, nose, lips, jawline, face oval) and triangulate them into a mesh. Do not claim unseen side geometry is exact from a single 2D photo.
   - Use the photo as a texture/reference where feasible, with a wireframe/triangular neural overlay aligned to the facial landmarks. Avoid simply drawing random lines over the entire rectangular image.
   - Add a subtle 3D-style projection and yaw/tilt illusion from inferred depth, preserving recognizable facial proportions. Clearly label this as photo-derived 2.5D if no true 3D reconstruction is available.
   - Keep hairline and face framing recognizable; do not distort the source portrait.
3. Animation:
   - Idle breathing/pulse, slow restrained yaw/tilt illusion, scan line, connected glowing nodes and particles.
   - Audio-reactive mouth opening/closing driven by actual playback audio energy if available; smooth interpolation and clamp values to avoid jitter. Treat this as approximate audio-reactive lip motion, not phoneme-accurate lip-sync.
   - Add a clean extension point for future phoneme/viseme-driven lip sync once a voice/audio stream is available.
4. Integration:
   - Bihansa Mode remains OFF by default and is enabled only by explicit user action.
   - Existing normal JARVIS wireframe remains unchanged and works when Bihansa Mode is off.
   - Preserve the current settings/toggles and existing privacy behavior. Do not enable mic/camera automatically.
   - If face landmark model/assets are missing, show a useful fallback/error status and retain the current portrait visualization rather than crashing.
5. Quality:
   - Respect PyQt6 thread/UI constraints; no blocking inference in the paint loop.
   - Cache model/landmark results; do not rerun face detection every frame.
   - Handle missing/invalid portrait paths gracefully.
   - Keep CPU use reasonable; test at common window sizes.
   - Add unit/smoke tests for widget initialization, missing asset fallback, mesh/landmark data validity, animation state updates, and settings/mode OFF behavior.
   - Run the repository's relevant tests/lint/type checks and report exact commands and results. Do not claim checks passed unless actually run.
6. Documentation:
   - Explain what is genuinely 3D versus a 2.5D approximation.
   - Document how to add extra front/side photos later to improve reconstruction and how voice data can later enable viseme-based lip sync.
   - Do not fabricate a voice or claim it recreates the person's actual voice.

## Acceptance criteria
- Bihansa OFF: old JARVIS mode behaves exactly as before.
- Bihansa ON: the user's reference face has visible, facial-feature-aligned triangulated wireframe, not only a portrait with decorative rings.
- The mesh is stable and recognizable, with denser landmarks around eyes/nose/lips/jaw than the background.
- Animation is smooth and audio-reactive when valid audio energy is supplied; no audio means the mouth remains in a neutral idle state.
- Missing optional dependencies/assets never crash the app.
- Tests/checks and limitations are accurately reported.

Please work on a feature branch, inspect existing code before modifying it, and open a PR for review. Do not merge automatically.
