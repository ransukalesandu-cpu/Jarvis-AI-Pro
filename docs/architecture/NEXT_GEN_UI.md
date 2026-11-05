# Next-generation JARVIS UI: Phase 0 (audit, decision, plan)

Status: proposal, implemented phase by phase on `feature/next-generation-ui*` branches, one PR per phase.
Nothing here is merged until the owner says so.

## 1. What the repository actually contains (audited at `a9f1e91`)

| Fact | Evidence |
| --- | --- |
| The shipped UI is **native PyQt6**, not a web frontend. `MainWindow` (`jarvis/ui/__init__.py`, ~6.7k lines) hosts `HudCanvas`, a `QOpenGLWidget` that paints the HUD with QPainter. | `jarvis/ui/__init__.py:511`, `:1701` |
| The standard JARVIS face is `HoloAvatar` (`jarvis/core/avatar.py`): MediaPipe canonical head mesh (`core/face_model.obj`, 468 vertices / 898 triangles), faceted shaded look, orange eyes, neck/base. Other looks (cyber, volume, image) exist as options. | `core/avatar.py`, `core/avatar_mesh.py` |
| Heart, orb and energy wires are drawn by `HologramStage` (`ui/hologram/stage.py`). | `ui/hologram/stage.py` |
| `NeuralWireframeHead` and `BihansaHologramWidget` live in `ui/hologram/` and are used by `ui/hud_main.py`, which is **not** the shipped entry point. | `ui/hud_main.py` |
| **QWebChannel is not used anywhere.** QtWebEngine is imported lazily only for web players and the Holo Hands page. | grep: no `QWebChannel` in the tree |
| Already implemented natively: Ctrl+K command palette, Dynamic Island, glass windows, window manager with named workspaces (JSON), design tokens, state bus + shared animation clock, performance tiers, hover menus. | `ui/command_palette.py`, `ui/dynamic_island.py`, `ui/glass_window.py`, `core/window_manager.py`, `core/ui_tokens.py`, `core/ui_state.py`, `core/ui_perf.py`, `core/ui_menus.py` |
| Real data sources exist: `_SysMetrics` (CPU/RAM/GPU/temps via psutil + NVML), `actions/battery_status.py`, provider/brain panels, scheduler, memory and security panels. | `ui/__init__.py:340`, `actions/` |
| Baseline: 229 UI-related tests pass, 2 skipped (`pytest -k "ui or hud or glass or island or palette or panel or menus or hologram or perf"`). | local run |
| Open PRs: #253, #254 (hologram v2 WebGL engine). Neither is merged; this work does not depend on them. | GitHub |

## 2. Decision

**React + TypeScript + Vite, rendered inside `QWebEngineView`, talking to the existing Python backend through a typed QWebChannel bridge. The legacy PyQt HUD stays as a working fallback until the new UI reaches verified parity.**

### Options compared

| Criterion | A. React/TS/Vite in QWebEngine (chosen) | B. Stay native PyQt6 | C. Qt Quick/QML |
| --- | --- | --- | --- |
| 3D neural face, particles, bloom | Three.js / R3F: GPU, mature | QPainter software rendering (current head is software-drawn); no real 3D | Possible (Quick3D) but small ecosystem |
| Glass UI, animation, spatial transitions | CSS `backdrop-filter`, Motion, GPU compositing | Hand-painted; heavy to maintain (`ui/__init__.py` is 6.7k lines) | Good, but few components |
| Component ecosystem (dialogs, menus, cmdk, charts, drag windows) | Very large, accessible (Radix), MIT | Build everything by hand | Limited |
| Accessibility (focus, ARIA, reduced motion) | Native web semantics | Weak | Moderate |
| Testing | Vitest + Testing Library + Chromium headless | Existing Qt tests | Few tools |
| Windows risk | WebEngine already ships in `PyQt6-WebEngine`; transparent compositing needs care (see risks) | None | GPU driver variance |
| Cost | Highest (rewrite UI layer, new bridge) | Lowest | High |

B is the lowest-risk option and would suffice for polish only. The owner explicitly prioritises quality and authorised a rewrite, and A is the only option that gives GPU 3D, an accessible component system and a testable frontend. The decision is conditional on the verification gates in section 8; if WebEngine cannot meet them on Windows, the fallback remains the native HUD.

## 3. Architecture

```
Python (unchanged)                       Qt bridge (new)                  Frontend (new)
GeminiLive, HybridLLMRouter,   <------>  jarvis/webui/bridge.py   <---->  frontend/  (React+TS+Vite)
AuthManager, ActionDispatcher,           QWebChannel object                 Zustand store
Privacy Lock, Supabase, audio            typed, allowlisted,                R3F hologram scene
_SysMetrics, ui_state bus                validated both sides               Radix/shadcn-style UI, cmdk, Motion
```

* `frontend/` holds the source; `npm run build` emits to `jarvis/webui/dist/`. The built bundle is committed so Windows users never need Node. CI checks that `dist/` matches source.
* `jarvis/webui/host.py` owns the `QWebEngineView`: locked navigation to the bundled `file://` dist, no remote content, `LocalContentCanAccessRemoteUrls=False`, off-the-record profile, permission requests denied, restricted CSP (`default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:`), crash reload with a retry cap, heartbeat.
* `jarvis/webui/bridge.py` exposes one `QObject` over `QWebChannel`. It has **no** raw access to backend objects. It has:
  * **events (Python to JS)**, each a JSON object with a `type` from a closed set and bounded fields;
  * **requests (JS to Python)** that map to an allowlist of backend calls and always go through the existing authorization checks (AuthManager, Privacy Lock, ActionDispatcher). The UI never decides authorization.
* Provider API keys never cross the bridge. The UI can see only provider id, model name and connection state.
* Fallback: if QtWebEngine, QWebChannel or `dist/` is unavailable, or the WebGL context fails, the legacy PyQt HUD starts (`JARVIS_UI=legacy` forces it).

### Message contract (proposed; implemented incrementally, validated in both languages)

Events: `assistant.state_changed`, `assistant.audio_level`, `task.started`, `task.progress`, `task.completed`, `task.failed`, `system.metrics_updated`, `provider.changed`, `notification.created`, `workspace.updated`.
Requests: `ui.navigate`, `ui.settings.get/set` (allowlisted keys), `assistant.send_text`, `assistant.cancel`, `workspace.save/load`, `system.open_app` (through ActionDispatcher).

Today the backend does not publish `task.*` or per-task progress. Phase 3 adds a thin publisher on top of `ui_state` and the existing agent engine; until then the UI shows only states and metrics that are real, and hides anything that has no source. No fabricated percentages.

## 4. Hologram (identity preserved)

Target is the standard JARVIS face: a **low-poly, shaded, blue head built from the same MediaPipe canonical mesh**, orange glowing eyes, neck and base plate, voice-synced jaw, blink and look. Plus a small quantum heart on the left, a larger energy orb below, animated neural connections, transparent rendering.

* Three.js through React Three Fiber. Flat-shaded mesh from `face_model.obj` (Apache-2.0, converted once to a compact binary and kept in `frontend/public`).
* Lip-sync from the existing output level (`sig_output_energy`) only while speaking, as in `core/avatar.py`; never from the mic.
* Transparent output: the page background is the HUD backdrop colour rather than true window transparency, because transparent QWebEngine views composite black on some Windows setups (learned during the v2 engine work). Visually it is indistinguishable against the HUD; there is no opaque rectangle.
* Bihansa stays a separate companion mode (profile switch), backend untouched.
* The `shaded` look will be compared side by side with the legacy renderer before the legacy head is retired.

## 5. Existing features: KEEP / UPGRADE / REPLACE / ADD / REMOVE

| Feature | Decision | Reason |
| --- | --- | --- |
| Python backend (Gemini Live, routing, auth, dispatcher, memory, audio) | KEEP | Out of scope; bridge adapts to it |
| `core/ui_state.py` state bus + clock | UPGRADE | Becomes the source for `assistant.*` events; frontend mirrors it in Zustand |
| `core/ui_tokens.py` | UPGRADE | Exported as CSS variables (single source: JSON) so Qt fallback and web share tokens |
| `core/ui_menus.py` command list | KEEP | Drives the web palette too, so menus and palette cannot disagree |
| `core/window_manager.py` + Workspaces | KEEP (logic), REPLACE (view) | Layout/persistence logic reused; web floating windows via react-rnd |
| `ui/command_palette.py` (Ctrl+K) | REPLACE | cmdk, same commands |
| `ui/dynamic_island.py` | REPLACE | Web pill for in-app; a small native always-on-top window remains for minimised mode (needs a native window) |
| `ui/glass_window.py` | REPLACE | Web windows; web players stay in embedded pages |
| `HudCanvas` / `HoloAvatar` / `HologramStage` | REPLACE after parity | Kept as fallback until acceptance gates pass |
| `ui/hud_main.py`, `NeuralWireframeHead` | REMOVE later | Not the shipped entry point; delete only after parity |
| Overlays (settings, provider, audio device, memory, customize) | REPLACE | Rebuilt as web settings categories bound to existing backend settings |
| Clock, battery, CPU/RAM, network, AI brain, activity, notifications widgets | ADD (clock/telemetry exist as labels) | Real sources: `_SysMetrics`, `battery_status`, provider state |
| Pages: Home, AI Chat, Activity, AI Models, Web Research, Reminders, Applications, Files & Media, Memory, Automation, System Monitor, Security | ADD/REPLACE | Each page must bind to a real backend capability or it is not shipped |
| Notification center | ADD | No central one exists |
| States `searching`, `executing`, task progress | ADD | Need backend events (Phase 3) |
| `ui_perf.py` tiers | UPGRADE | Same tiers; web side adds frame-time governor; user override kept |

## 6. Technology selection (versions checked on npm on 2026-11-05)

| Package | Version | License | Use | Verdict |
| --- | --- | --- | --- | --- |
| react / react-dom | 19.3.1 | MIT | UI | Use |
| typescript | 7.0.2 | Apache-2.0 | Types | Use |
| vite | 8.3.6 | MIT | Build | Use |
| vitest | 5.1.0 | MIT | Tests | Use |
| three | 0.187.0 | MIT | 3D | Use |
| @react-three/fiber | 9.8.2 | MIT | Declarative 3D | Use |
| @react-three/drei | 10.7.9 | MIT | Helpers (only what is needed) | Use sparingly |
| motion | 14.9.1 | MIT | Transitions, reduced-motion | Use |
| zustand | 5.0.16 | MIT | UI state | Use |
| cmdk | 1.1.1 | MIT | Command palette | Use (last release Aug 2025; stable, small) |
| sonner | 2.0.8 | MIT | Toasts | Use |
| @radix-ui/* | 1.x | MIT | Accessible dialogs/menus/tooltips (shadcn pattern, copied components) | Use |
| lucide-react | 1.69.0 | ISC | Icons | Use |
| recharts | 3.10.1 | MIT | Monitor charts, lazy-loaded | Use (Phase 3) |
| react-rnd | 10.5.3 | MIT | Floating windows | Use (Phase 2) |
| @assistant-ui/react | 0.15.32 | MIT | Chat | Defer: custom streaming chat on the bridge is smaller and the backend streaming protocol is not React-shaped; revisit in Phase 1 spike |
| React Bits | n/a | **MIT + Commons Clause** (GitHub page) | Effects | **Do not use**: Commons Clause restricts selling the software; owner resells work to clients |
| Magic UI | n/a | MIT (copy-in) | Optional borders/shimmer | Only individual files, license re-checked per file |
| React Grid Layout, React Resizable Panels | n/a | MIT | Dashboards, splits | Not needed until a page requires them |
| WaveSurfer.js | n/a | BSD-3 | Audio waveform | **Not used**: it is for files; a live mic waveform is a small canvas fed by the existing level |
| eDEX-UI | n/a | GPL-3.0, archived | Inspiration only | Not a dependency |

Licenses of repository pages for React Bits (MIT + Commons Clause), Lucide (ISC) and pyqtgraph (page links LICENSE.txt, not read) were checked from GitHub; npm metadata above is authoritative for packages. Every added dependency is re-checked at install and listed in the PR.

## 7. Migration plan (one PR per phase)

* **Phase 0 (this PR)**: audit and decision only. No code changes.
* **Phase 1, foundation**: `frontend/` scaffold, design tokens, `jarvis/webui` host + typed bridge with tests, R3F hologram (shaded head, heart, orb, wires), glass HUD widgets with real values (clock, battery, CPU/RAM, AI brain, network), navigation shell, settings shell, state visualization for existing states, legacy fallback switch (`JARVIS_UI`). Legacy UI remains default until parity.
* **Phase 2, workspace**: floating windows, context-aware panels through ActionDispatcher, persistence via the existing `Workspaces` JSON, Dynamic Island, cmdk palette.
* **Phase 3, intelligence**: `task.*` publisher, adaptive performance, notification center, System Monitor, accessibility pass, regression run, parity checklist; flip default to the new UI; remove obsolete legacy code only after sign-off.

## 8. Risks and acceptance gates

| Risk | Mitigation / gate |
| --- | --- |
| WebEngine transparency and compositing on Windows | Opaque backdrop matched to HUD colour; Windows run required before default flip (not verifiable in the Linux sandbox; will be reported as unverified until done) |
| Software-only WebGL in CI/sandbox hides GPU behaviour | Treat sandbox results as correctness only; add frame-time governor and a low tier |
| Bundle size and startup time | Code-split pages, lazy charts, budget checked in CI |
| Bridge becomes a privilege hole | Allowlist, typed validation on both sides, authorization stays in Python, no secrets in payloads, tests for rejected messages |
| Voice/Gemini regressions | No backend rewrite; regression suite run each phase |
| Committed `dist/` drift | CI rebuild-and-diff check |
| Scope | Pages that have no real backend source are not shipped as decoration |

Acceptance for flipping the default: original-look hologram verified against the legacy one; every nav item and widget bound to real data; voice in/out and Gemini Live unchanged; auth and Privacy Lock enforced on every sensitive request; adaptive performance does not hide the hologram or controls; full regression green; Windows run completed by the owner or a Windows CI job.

## 9. Known gaps in this phase

* No code has been written or run for the new frontend yet; the table in section 6 is registry metadata, not integration testing.
* Windows desktop behaviour is unverified.
* `task.*` backend events do not exist yet.
