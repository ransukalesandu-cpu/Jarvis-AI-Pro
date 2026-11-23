# Next-generation UI — Phase 0 audit (2026-11-23)

Audited against the "JARVIS AI PRO — Ultimate Next-Generation UI Upgrade" master prompt, on `main` at `141d92c`
(PR #314: web UI is the default, `JARVIS_UI=legacy` for the classic HUD).

## Baseline (before this change)

| Check | Result |
| --- | --- |
| `frontend`: `tsc --noEmit` (strict) | clean |
| `frontend`: Vitest | 153 passed, 27 files |
| `frontend`: `npm run build` | OK; chunks: three 762 kB, app 565 kB, react 275 kB (gzip 193 / 185 / 84 kB) |
| `pytest jarvis/tests/test_webui_*.py` (Linux, no PyQt6) | 86 passed, 15 skipped (Qt-only) |
| `python -m jarvis.webui.selfcheck` (Linux container, offscreen Qt WebEngine, software GL) | bundle, backend link, live data, canvas PASS; WebGL2 present but software (WARN); 16 fps (FAIL, expected without a GPU) |

The Windows-only checks (real GPU, voice pipeline, Voice ID, packaging) could not be run here and are **not** claimed.

## What already exists (verified by reading the code, not by file names)

Most of the target architecture in the prompt is already built and merged:

- **Shell**: PyQt6 + `QWebEngineView` host (`jarvis/webui/host.py`, `bridge.py`), web UI is the default, classic HUD
  kept as the fallback and chosen automatically when the page reports no WebGL 2 (`hologram.capability`).
- **Bridge**: one QWebChannel object, typed closed contract on both sides (`jarvis/webui/contract.py` ↔
  `frontend/src/bridge/contract.ts`), size caps, rejected-not-coerced validation, listener cleanup, StrictMode-safe
  start, heartbeat reload. Actions go through `CommandGate` / `ControlGate` with a narrow allow-list and the existing
  authorisation (locked / PIN / guest refuse); the page is never the security authority.
- **Frontend**: React 19 + TypeScript strict + Vite, Zustand stores, Motion, Lucide, CSS design tokens, glass surfaces,
  floating window manager (`react-rnd`, z-order, minimise/restore, saved layouts), command palette, command bar,
  Dynamic Island, Task Flow window and page, Features Hub, jobs, news, timer, settings, toasts and loading rules.
- **Hologram**: React Three Fiber scene with GLSL materials: neural brain (default centre) or head (circuit / mechanical),
  glass orb with plasma core and rings, energy strands and arcs, GPU particles, backdrop; per-state moods; audio-reactive
  from real input/output levels; quality tiers (full / balanced / lite) chosen by the host, frame-budget DPR governor,
  FPS overlay, rendering stopped while the window is hidden, reduced motion, resources disposed on unmount.
- **Telemetry**: real CPU / RAM / disk / battery / network from `psutil`, batched at 1 Hz; nothing is invented.
- **Persona**: JARVIS / Bihansa switch goes to the backend (`mode_jarvis` / `mode_bihansa`), guarded like unmute.

## Classification

| Area | Verdict | Note |
| --- | --- | --- |
| QWebChannel bridge + contract | **Reuse** | Already typed, validated, allow-listed. No second bridge added. |
| React/TS/Vite/Zustand/R3F stack | **Reuse** | See ADR-0001 for libraries the prompt lists that were deliberately not added. |
| Hologram states | **Improve** → done | No "offline" look; a muted mic could still show "listening". |
| Renderer failure handling | **Improve** → done | No WebGL 2 or a lost GPU context left a blank stage in the page itself. |
| Live HUD | **Improve** → done | Mic, voice output, backend link and running task were not shown together. |
| Sinhala text | **Improve** → done | Font stack had no Sinhala-capable fallback. |
| Classic PyQt HUD (`jarvis/ui/hud_main.py`, `jarvis/ui/__init__.py` 6 718 lines, `jarvis/ui/hologram/*`) | **Reuse as fallback, do not touch** | Still the `JARVIS_UI=legacy` path and the no-WebGL fallback. Not modified. |
| `web/` (Next.js upstream app) | **Unknown / requires owner decision** | Not loaded by the desktop app; separate project. Left alone. |
| Neural heart, face as primary centre | **Conflicts with later owner decisions** | Owner chose "no heart" and the neural brain at the centre (Nov 2026); the head is still one setting away. Not changed without his answer. |
| ESLint / Prettier / Playwright | **Not started** | Not in the repo; `tsc` strict + Vitest + CI `webui-checks.yml` are the current gates. |

## Done in this change

1. `hologram/visualState.ts`: one pure function decides what the hologram shows: `offline` when the backend link is down,
   never `listening` while the microphone is muted. Brain, orb, arcs, strands, particles, both heads, the Island and the
   Activity widget all use it. Offline has its own cold, near-still look.
2. `hologram/engine/RendererGuard.tsx`: visible, plain-language notice for no WebGL 2, a lost GPU context
   (`webglcontextlost`) and a crash inside the scene, with "Restart renderer" (remounts the canvas) where a retry can help.
3. `VoiceLinkWidget`: Mic (on / listening / muted / unknown), Voice (speaking / quiet), Backend (connected / connecting /
   offline), Task (latest running Task Flow title). Text for every state; input level rounded to 5% steps so audio frames
   do not re-render React.
4. Sinhala font fallback: `Nirmala UI`, `Iskoola Pota`, `Noto Sans Sinhala`.

## After this change

| Check | Result |
| --- | --- |
| `tsc --noEmit` | clean |
| Vitest | 166 passed, 30 files (+13 tests) |
| `npm run build` | OK; app chunk 565 → 569 kB |
| `pytest jarvis/tests/test_webui_*.py` | 86 passed, 15 skipped (unchanged) |
| Qt WebEngine selfcheck (container) | same as baseline: link, live data, canvas PASS |
