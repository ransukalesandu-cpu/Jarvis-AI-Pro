# Neural Entity Engine 2.0: the WebGL hologram

One Three.js / WebGL2 / GLSL scene (face, quantum heart, energy orb, neural wires, aura) rendered in a
locked-down `QWebEngineView`. It replaces the CPU-painted face, heart, orb and Bihansa widgets. Everything
else in the UI is unchanged.

## Correction to the Phase 1 audit
The audit named `ui/hud_main.py` as the shipped HUD. It is not launched: `test_launchers` pins that the
desktop launcher uses the **original UI** (`ui/__init__.py`: `JarvisUI` -> `MainWindow` -> `HudCanvas`).
The engine is therefore attached to `HudCanvas` (face mode). `hud_main.py` (an alternate HUD) is wired to the
same host so both stay consistent.

## Where things are
| Path | Purpose |
|---|---|
| `jarvis/hologram/main.js`, `index.html` | page bootstrap, CSP, frame loop, `window.__holo.receive` |
| `animation/` | state machine (idle, listening, thinking, processing, speaking, responding, error, disconnected, recovery + sleeping, locked), audio sync, damping |
| `entities/`, `shaders/` | face, heart, orb, connections, aura; GLSL as JS string modules |
| `profiles/` | JARVIS (cyan) and Bihansa (pink) profiles, smooth blend, no geometry rebuild |
| `core/` | renderer, capability detection, High/Balanced/Low tiers + frame monitor, lifecycle, context-loss recovery |
| `bridge/protocol.js`, `protocol.py` | strict message allowlists on both sides |
| `host.py` | `HologramHost`: navigation lock, off-the-record profile, coalesced messages, heartbeat, crash reload |
| `fallback.py` | inert stand-in when QtWebEngine is missing or `JARVIS_HOLOGRAM=off` |

## Integration (minimal)
* `HudCanvas.attach_hologram()` overlays the host on the face band; `_step()` feeds state and audio.
* While JARVIS speaks, only **output** audio moves the mouth (viseme frame due now, else the playback level from
  the new `VisualizerBridge.sig_output_energy`); the mixed mic+playback level is ignored. No raw audio is sent,
  only a 0..1 level; there is no second audio pipeline.
* Bihansa is a *profile* of the same engine (`set_hologram_profile`); the backend (`bihansa_settings`,
  `assistant_mode`) is untouched, and JARVIS can never be replaced permanently.
* If the engine is not ready (or fails), the old avatar/stage painters in `HudCanvas` keep drawing, so the HUD
  is never empty. `JARVIS_HOLOGRAM=off` forces that path.
* `prepare_qt()` runs before `QApplication` is created (QtWebEngine requires it).

## Removed
`ui/hologram/wireframe_head.py`, `bihansa_hologram.py`, `neural_heart_reactor.py`, `animation_engine.py` and
their tests. **Kept on purpose:** `ui/hologram/stage.py` and the avatar, as the fallback painter and for code
that still uses them; `bihansa_settings.py` and `hologram_theme.py` (preferences and palettes).

## Security
CSP `default-src 'none'; script-src 'self'`; navigation only to files inside `jarvis/hologram/`; no new
windows, permissions, clipboard, plugins or remote URLs; no QWebChannel and no objects exposed to the page;
messages are allowlisted and bounded on both sides (unknown keys reject the message); the page reports only via
`HOLO:` console lines which Python re-validates; off-the-record profile (nothing written to disk).

## Test status
Python 1404 collected, JS logic 17/17, ruff clean. The real engine is exercised in a child process with
**software** WebGL2 (`test_hologram_engine.py`): ready, state/profile delivery, output-audio speaking,
invalid-message rejection, tier switching without leaks, WebGL context loss and restore, full disposal,
navigation lock. This does not measure real GPU speed and was not run on Windows.

## Windows checklist (not yet done)
1. Start JARVIS; the hologram appears in the HUD with the HUD background colour (no black box, no flicker).
2. Resize, minimise/restore, switch to camera and back; no blank view.
3. Speak to JARVIS: mouth follows JARVIS's voice, not your microphone.
4. Switch Assistant mode to Bihansa and back; pink profile appears and JARVIS returns.
5. Tier chosen on your GPU (look for `tier` in the `ready` report) and a steady frame rate.
6. Lock screen / privacy lock shows the locked look.
7. If anything is wrong, set `JARVIS_HOLOGRAM=off` to return to the old painters and send the console output.
