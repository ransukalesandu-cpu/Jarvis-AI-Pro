# Bihansa 3D Neural Face — Architecture & Roadmap Documentation

## Overview
Bihansa Mode introduces an opt-in 3D-style neural wireframe face overlay aligned to facial landmarks extracted from the reference portrait (`JarvisAI/assets/bihansa_reference.png`).

It preserves the original portrait reference while layering a facial-landmark-derived 3D triangulated mesh with perspective projection, smooth 3D motion (yaw, pitch, roll), audio-reactive lip deformation, and glowing neural aura particles.

---

## 3D Wireframe Mesh Architecture

### 1. 2.5D Landmark Projection Model
- **Landmark Mapping:** Nodes in `BIHANSA_LANDMARKS_3D` (`ui/hologram/bihansa_hologram.py`) define 82 normalized 3D facial coordinates derived from the portrait landmark groups in PR #85 ($X, Y, Z$) matching the key facial features of the reference portrait:
  - Jawline / Face Oval (indices 0..16)
  - Eyebrows (indices 17..26)
  - Nose Bridge & Tip (indices 27..35)
  - Eyes (indices 36..47)
  - Outer & Inner Lips (indices 48..67)
  - Forehead / Hairline (indices 68..75)
  - Cheeks / Mid-face (indices 76..81)
- **Portrait alignment:** Projection uses the fitted image rectangle and separate image width/height scales. At rest, the eye/nose/jaw anchors match the normalized portrait coordinates; animation adds restrained parallax.
- **Triangulated Wireframe:** `BIHANSA_MESH_EDGES` links these landmarks into structural triangles, ensuring dense wireframe geometry across expression points (eyes, nose, mouth) while keeping hairline/face framing recognizable.
- **3D Rotation & Perspective Projection:** Applies Euler rotation matrices for Yaw ($\theta_y$), Pitch ($\theta_x$), and Roll ($\theta_z$) combined with perspective depth scaling:
  $$\text{dist} = \frac{\text{fov}}{\text{fov} + Z' + 0.4}$$
  $$\text{Pixel}_X = C_x + X' \cdot \text{scale} \cdot \text{dist}$$
  $$\text{Pixel}_Y = C_y + Y' \cdot \text{scale} \cdot \text{dist}$$

### 2. Audio-Reactive Mouth Motion
- Speech playback or audio energy level [0.0, 1.0] dynamically shifts lower-lip and jaw landmarks ($Y$ offset), opening and closing the mouth smoothly during `SPEAKING` and `LISTENING` states.
- Energy values are lerped (smoothed) to eliminate jitter and clamped to realistic bounds.

---

## Roadmap & Extension Guidelines

### Adding Additional Photos for True 3D Reconstruction
Currently, Bihansa 3D Neural Face uses a **2.5D photo-derived perspective model** from a single frontal reference image (`bihansa_reference.png`). Unseen lateral geometry (side profile / back of head) is inferred based on canonical facial geometry.

To upgrade to true multi-view 3D mesh reconstruction in future phases:
1. **Photo Requirements:**
   - Frontal view (0° yaw) — existing `bihansa_reference.png`.
   - Left side profile (+45° to +90° yaw) — place as `JarvisAI/assets/bihansa_side_left.png`.
   - Right side profile (-45° to -90° yaw) — place as `JarvisAI/assets/bihansa_side_right.png`.
2. **Mesh Optimization:**
   - Use multi-view stereo or neural radiance fields (NeRF/Gaussian Splatting) to compute exact 3D vertex positions and UV texture maps.
   - Update `BIHANSA_LANDMARKS_3D` with full 360° 3D mesh obj assets (`bihansa_head.obj`).

### Viseme / Phoneme Lip-Sync Integration Roadmap
`BihansaHologramWidget` exposes an extension interface `set_viseme(viseme_id: str, weight: float = 1.0)` to support phoneme-accurate lip-sync when voice/phoneme audio streams become available.

1. **Viseme Blend Weights:**
   Supported visemes: `aa` (open mouth), `ee` (wide smile), `oh` (rounded lips), `ou` (puckered lips), `ch` (teeth aligned), `m` (closed lips).
2. **Integrating with Voice Recordings / TTS Stream:**
   When the audio pipeline generates real-time phoneme timestamps or viseme ID events from speech synthesis (e.g. via `JarvisLive` or `edge-tts` viseme callbacks):
   ```python
   # Example callback dispatch to Bihansa visualizer
   hud_window.bihansa_visualizer.set_viseme("aa", weight=0.85)
   ```
3. **Voice Disclaimer:**
   Bihansa mode utilizes Gemini prebuilt voices (such as `Aoede` or `Kore`) and does not synthesize or mimic an actual person's voice without explicit authorization and training audio recordings.
