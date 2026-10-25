# Bihansa Mode — Implementation Plan

Status: planning specification only. This document does not change the current JARVIS UI or voice behavior.

## Goals

Add an optional **Bihansa Mode** alongside the existing JARVIS mode. The existing mode remains the default and must keep its current hologram, audio pipeline, wake-word behavior, and assistant features.

## Mode settings

- `assistant_mode`: `jarvis` (default) or `bihansa`.
- Persist the selected mode through the application's existing settings/config mechanism after it is identified in the codebase.
- Provide an explicit mode selector in Settings and a visible indicator in the main UI.
- Switching modes must not restart the assistant, interrupt active audio unsafely, or duplicate microphone/audio workers. If a live response is in progress, apply the visual/voice change at a safe boundary.
- Add a “Restore defaults” option for Bihansa-specific settings only.

## Hologram settings

- Theme: rose pink / light pink on a near-black background.
- Visual layers: head silhouette, hair silhouette, neural wireframe, node points, eye glow, subtle particles, and soft bloom.
- Animation controls: idle movement, particle effects, glow intensity, animation speed, and reduced-motion toggle.
- Speaking state should be driven by actual audio/playback state where possible. Do not claim true lip sync unless usable audio timing/viseme data exists.
- Face reference image and face-specific tuning are intentionally deferred until a reference image is available. The visual component must support replacing a generic placeholder/reference asset without changing mode or audio logic.
- If real-time 3D rendering would add heavy dependencies, first inspect the existing UI stack and choose the lightest compatible approach. Do not add a new graphics framework without evidence it is necessary.

## Voice settings

- JARVIS mode: preserve the current male voice and existing Gemini Live/audio configuration.
- Bihansa mode: use a configurable female voice only if the current provider/API supports selecting it. If Gemini Live returns a fixed voice or requires a session-level voice setting, configure it through the supported session configuration and recreate a session only at a safe point.
- Voice options: provider-supported voice, speaking rate, volume, and optional test-voice action.
- Keep the voice selection separate from hologram appearance.
- Never place API keys or secrets in source code or settings files; use existing secret/config handling.
- If the provider cannot guarantee a female voice, expose the limitation clearly instead of pretending the switch succeeded.

## UI states

The hologram component should support these states:
- `idle`
- `listening`
- `thinking`
- `speaking`
- `muted` / `error`

Use a single state source and avoid multiple timers/workers competing to update the UI. All UI updates must follow the application's existing Qt thread-safety pattern.

## Suggested separation

Keep the implementation modular, adapting to the real project structure after inspection:
- A mode/settings model for persisted Bihansa preferences.
- A separate Bihansa hologram widget/component.
- A small mode controller that selects the visual component and voice configuration.
- Tests for defaults, persistence, mode switching, state transitions, and fallback when a requested voice is unsupported.

Do not rewrite the large existing `JarvisAI/main.py` wholesale. Prefer small integration points and new modules where the existing architecture allows them.

## Acceptance checks

1. App starts in JARVIS mode by default.
2. Existing JARVIS hologram and male voice remain unchanged.
3. Selecting Bihansa mode changes only the intended visual and supported voice configuration.
4. Switching back restores JARVIS mode without duplicating audio/microphone workers.
5. Selected mode persists after restart.
6. UI remains responsive while animation runs; worker/audio callbacks do not update Qt widgets from the wrong thread.
7. Tests pass and the existing audio/wake-word behavior is not regressed.
8. Work stays on a separate branch and is reviewed in a PR; do not merge automatically.
