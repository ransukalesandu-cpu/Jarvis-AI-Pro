# Neural Entity Engine 2.0 — Phase 1 audit

Scope: the hologram only (face, heart, orb, wires). Main UI layout stays as is. Everything below was read from the repository on `main` (after Security V2 was merged); nothing has been deleted yet.

## What the current hologram actually is
All of it is **CPU QPainter code in `jarvis/ui/hologram/`**, not WebGL.

| File | Role | Lines |
|---|---|---|
| `wireframe_head.py` | JARVIS face (parametric head mesh, particles, states, painter) | 663 |
| `bihansa_hologram.py` | Separate pink Bihansa face widget (visemes, effects) | 369 |
| `stage.py` | Orb under the face, heart bottom-left, 5 energy wires | 232 |
| `neural_heart_reactor.py` | Heart overlay widget (`_heart_reactor`) | 160 |
| `animation_engine.py` | `smooth_damp`, `pulse` helpers | 35 |
| `bihansa_settings.py` | Bihansa preferences dialog and settings data | 238 |

Related but **not** the shipped hologram: `core/neural_viz.py`, `avatar*.py`, `core/face_model.obj` belong to the legacy `ui/__init__.py` UI (HudCanvas "Synapse Field / Neural Orb" and the avatar). `assets/holo/` (54 MB, MediaPipe, props, notes) is the separate hand-gesture / document "holo workspace", and `core/qt_webengine.py` serves it and the Earth globe. These are out of scope and stay untouched.

## Integration contract (hud_main.py)
- Container: `self._hologram_stage` (QWidget) holding a `QStackedWidget` with `wireframe_visualizer` and `bihansa_visualizer`, the `_mini_orb`, and the `_heart_reactor` overlay. Persona switch = `_set_bihansa_enabled` (stack current widget, orb/dashboard mode).
- Methods the HUD calls on the visualizers: `set_audio_energy`, `set_state`, `set_performance_budget(frame_ms, particle_scale, glow_scale)`, `set_reduced_motion`, `set_palette`, `set_glow`/`set_glow_intensity`, and for Bihansa `set_viseme`, `set_effects_enabled`, `set_voice_reactive`.
- Events in: `VisualizerBridge.sig_audio_energy` (one float 0..1) and `sig_state_changed` (string). The app emits `IDLE, LISTENING, THINKING, SPEAKING, SLEEPING, ERROR, LOCKED, PRIVACY_LOCK`. `sig_auth_state_changed` feeds the security panel and stays as is.
- Persona prefs live in `ui/hologram/bihansa_settings.py` (QSettings keys `bihansa/*`) and `core/hologram_theme.py` (pure-data palettes, Qt-free).

## Audio finding (matters for the speaking requirement)
Microphone level (`main.py` mic callback → `ui.set_audio_level`) and **output** level (`core/audio_playback.py` after each chunk → `ui.set_audio_level`, or the viseme peak) both land on the same `sig_audio_energy`. The face therefore cannot tell them apart. v2 adds a separate output-level path (additive, old path kept) and uses it only while speaking. No raw audio is sent to the page; only one float per update.

## State finding
There is no distinct Processing, Responding, Disconnected or Recovery signal today. Plan: Processing = THINKING with a tool running or lasting more than a short time (events in `live_tools`), Responding = the short SPEAKING→LISTENING settle, Disconnected/Recovery = `core/live_health` events (`unexpected_drop`, `connected`). I will state plainly in the final report which of these are real events and which are derived.

## Tests that pin the old implementation
`test_ui_hologram.py` (33), `test_hologram_stage.py` (3), `test_bihansa_integration.py` (5), `test_ui_restore_baseline.py` (7; it asserts the attribute names `wireframe_visualizer`, `bihansa_visualizer`, `_visualizer_stack`, `_hologram_stage`, `_mini_orb`, `_heart_reactor` exist in hud_main), `test_lazy_ui_imports.py` (11), `test_hologram_theme.py` (13, data only, keep). They will be updated, not weakened: tests of deleted painters go with them; the baseline test is rewritten to the new contract.

## Packaging
`pyproject.toml` package-data includes `assets/**/*`. New hologram assets live in `jarvis/hologram/` and need a `hologram/**/*` entry. Three.js: the repo already vendors r160 under `assets/holo/vendor/` for the other feature; v2 vendors its own copy (MIT) so the two features stay independent.

## Classification
**REMOVE (only after v2 is working, last phase):** `wireframe_head.py`, `bihansa_hologram.py`, `stage.py`, `neural_heart_reactor.py`, their tests, `_mini_orb` under the face (replaced by the v2 orb; the dashboard's own orb use is not touched).
**REWRITE:** face, heart, orb, neural connections, state machine, audio sync, both persona looks, as `jarvis/hologram/` (JS + shaders) plus a thin Python host.
**PRESERVE:** `animation_engine.py` if still referenced, `bihansa_settings.py` (prefs, dialog, backend persona switching), `hologram_theme.py` (palettes), `visualizer_bridge`, `ui_state`, AuthManager/Security panel, audio capture/playback, Gemini Live, memory, `assets/holo/`, `qt_webengine.py`, `neural_viz.py` and the legacy UI.
**MINIMAL INTEGRATION CHANGE:** `hud_main.py` (imports, the three construction lines, signal hookups, budget/resize, persona toggle), `visualizer_bridge.py` (one new output-level signal), `audio_playback.py` (report output level on the new path), `pyproject.toml` (package data), tests listed above.

## Environment and verification limits
- No GPU, no Windows, no real microphone. Node 22 and PyQt6 WebEngine are present, so I will try software WebGL2 (SwiftShader) inside the real QtWebEngine to render screenshots. If that works it verifies shaders and layout, not real GPU speed or Windows behaviour.
- Performance figures from software rendering will not be presented as GPU or Windows measurements.

## Visual direction (from the reference image)
Dense wireframe grid skin with brighter neural nodes, particle strands, spiral orbital rings, a base disc of concentric rings, vertical data lines, cyan-blue glow. The face is a generic procedural head and bust, not a likeness of any real person.
