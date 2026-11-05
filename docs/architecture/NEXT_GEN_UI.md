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

## 9. Phase 1 status (foundation)

Implemented on `feature/next-generation-ui-phase1` (stacked on Phase 0):
* `frontend/` (React 19, TS 7, Vite 8, R3F, Zustand, Motion, lucide-react), design tokens as CSS variables, Vitest suite for the contract and store.
* `jarvis/webui/`: locked `QWebEngineView` host, typed `QWebChannel` bridge with an allowlist both ways, real telemetry (psutil), `JARVIS_UI` switch (legacy stays default), standalone preview `python -m jarvis.webui`.
* Hologram: shaded low-poly head from the legacy `get_head_mesh()` data (same geometry), orange eyes with blink, voice-driven jaw (output level only), heart, orb with state colours, energy wires.
* Glass HUD: clock, battery, CPU/RAM/disk, AI brain, network, activity widgets bound to real events; hamburger navigation; settings panel; Home, Activity Center, AI Models and System Monitor pages with real data.
* Not wired to the running assistant yet: `jarvis/webui` is a separate window. Feeding it from `ui_state`, the audio bridge and the provider router is Phase 3, together with the default flip.

Pages that need a backend capability that does not exist yet (AI Chat, Web Research, Reminders, Applications, Files & Media, Memory, Automation, Security) are listed but disabled and labelled with their phase instead of shipping as decoration.

Verification in the Linux sandbox: `tsc` clean, Vitest 5/5, full pytest 1380 passed / 4 skipped, and the built bundle was loaded in the real QtWebEngine (software WebGL): QWebChannel connected, real telemetry and injected state/provider events rendered, navigation and settings clicks worked. Screenshots: `docs/images/next-gen-ui-phase1*.png`.

## 10. Known gaps in this phase

* Windows desktop behaviour and real-GPU rendering are unverified (sandbox used software WebGL).
* The new window is not connected to the live assistant yet (see section 9).
* The base plate under the neck and bloom/post-processing from the legacy look are not reproduced yet.
* Windows desktop behaviour is unverified.
* `task.*` backend events do not exist yet.

## 11. Phase 2 status — windows, palette, island, workspaces

Built on the Phase 1 branch. All of it is real behaviour; nothing is decorative.

| Piece | What it does | Where |
|---|---|---|
| Floating glass windows | Drag, resize, focus (z-order), minimise (tray), maximise, close. One window per kind: System Monitor, AI Models, Activity Center. New windows are placed in the side gutters, never over the hologram when avoidable; edge snap; tile; clamped to the viewport on resize. Closing a window never stops a backend task. | `frontend/src/workspace/`, `ui/Windows.tsx` |
| Command palette | `Ctrl+K` (cmdk). Only implemented actions: navigate to ready pages, open/tile/minimise/close windows, settings, save/load/delete workspace. No fake commands. | `ui/Palette.tsx` |
| Dynamic Island | Real assistant state, window count, offline marker; click opens the palette. | `ui/Island.tsx` |
| Workspace persistence | Layout autosaved (debounced) as hidden `_last` and restored on connect; named workspaces via the palette. Stored by Python in `config/web_workspaces.json` (atomic write). | `jarvis/webui/workspace_store.py` |

Security/robustness: layouts are validated on both sides with the same schema (exact keys, bounded numbers, max 12 windows, max 24 workspaces, names `[a-z0-9 _-]{1,32}`). A corrupt or outdated layout is dropped, never applied. Only `workspace.save` may exceed 512 chars; the cap for it is 16 KiB. `_last` cannot be deleted from JS. The legacy `workspaces.json` is untouched.

Verification: tsc clean; Vitest 17/17; pytest 1399 passed / 4 skipped; real QtWebEngine run (3 windows placed in the gutters, autosave written, palette opened by Ctrl+K). Screenshots: `docs/images/next-gen-ui-phase2-*.png`.

Not in Phase 2: live assistant wiring (state bus, audio, provider router), task events, charts, notification centre, Windows/real-GPU verification — Phase 3.

## 12. Phase 3a status — live assistant wiring

`JARVIS_UI=web` now mounts the React UI over the main window's central area and feeds it from the existing `ui_state` bus (the same source the classic HUD reads).

- `jarvis/webui/live.py` — `LiveLink`: read-only bus → bridge forwarding of assistant state, audio level (20 Hz throttle; silence never dropped) and persona. Values with no contract name (e.g. the classic `MUTED` label) are dropped, not approximated. The state is re-sent whenever the page (re)loads.
- `jarvis/webui/attach.py` — mounts the host, keeps it sized to the central widget via an event filter (no change to legacy `resizeEvent`). Does nothing unless `ui_mode() == "web"`.
- `MainWindow._attach_web_ui` (one hook) and `bootstrap._prepare_web_ui` (QtWebEngine import before `QApplication`). Any failure prints and leaves the classic HUD running.
- Tests: `test_webui_live.py` (6) + attach no-op test; real QtWebEngine run with the real bus (pre-load state, live update, resize).

Still open (Phase 3b): provider/model status (needs a real source), task events, charts, notification centre, mute state in the contract, Windows/real-GPU verification, CI dist rebuild check, parity checklist before the default flips.

## 13. Phase 3b status — provider, mute, CI

- **Mute**: new contract event `assistant.muted`; the classic `_toggle_mute` publishes `audio.muted` on the bus; the Island shows "MIC MUTED".
- **Provider**: `provider_info.snapshot()` reads the real one-shot provider settings (never a key). Contract field `connected` means "API key configured" and the page labels it that way. Live voice is always Gemini Live and is stated as such. If settings cannot be read, nothing is sent and the page shows "not reported". Saving provider settings in the classic UI bumps `provider.active`, so the web UI re-reads.
- **CI**: `.github/workflows/webui-checks.yml` runs tsc, Vitest, the build, and fails if the committed `jarvis/webui/dist` differs from a fresh build (the build was verified deterministic).
- Tests: +3 Python, +1 Vitest. Full suite green.

Still open: task events and notification centre (no backend event source exists yet — needs one designed rather than faked), System Monitor history charts, accessibility pass, Windows/real-GPU verification, parity checklist before flipping the default.

## 14. Phase 3c status — monitor history and accessibility

- **History charts**: the store keeps the last 120 real telemetry samples (CPU, RAM, network down/up). `Spark` is a dependency-free inline SVG (no Recharts needed, no bundle growth): no line without data ("collecting…"), and each chart has a text equivalent (`aria-label` with now/min/max) plus the numeric rows below it. A missing network sample is never invented.
- **Keyboard**: a focused floating window moves with Alt+Arrows and resizes with Alt+Shift+Arrows (same clamping/snapping as the mouse). Windows are `role="dialog"` with labels; palette (Ctrl+K), nav and settings were already keyboard reachable; focus ring and reduced-motion handling were already in place.
- Tests: Vitest 21 (series cap/honesty, Spark with/without data). Real QtWebEngine run shows live curves.

Still open: task events + notification centre (needs a designed backend event source), Windows/real-GPU verification, full screen-reader pass with a real reader, parity checklist before the default flips.

## 15. Command bar — the first write path

`command.submit` is the only request that makes the assistant *do* something. Design:

- **Gate in Python** (`jarvis/webui/command_gate.py`), not in the page. The classic typed-text path also takes the Privacy Lock PIN and the guest-mode `/owner <PIN>` credential, so the page must never become a credential entry point. The gate refuses to forward while the assistant is locked, waiting for a PIN, silent, or in guest mode, and refuses credential-shaped text (`/owner`, `/pin`, `/login`, `/password`) even when otherwise available. If safety cannot be determined, it is "unavailable" (fail closed).
- Limits: 500 chars, control characters stripped, 0.5 s spacing and 30/min. The text is never logged or stored by the web layer and is cleared from the page once sent; the classic log line ("You: …") is written by the existing sink.
- Availability is pushed to the page whenever it changes (checked on the 1 Hz tick), so the box disables itself and says "use the native prompt". Results come back as a closed set of reasons.
- Forwarding reuses the classic `_submit_immersive_command`, so the existing wake/auth checks in `_on_text_command` still run after the gate.
- Tests: Python 16 (all four lock states, credential shapes, limits, fail-closed, bridge round trip, change-only availability), Vitest 31; real QtWebEngine run shows send, then lock on PIN state.

Not covered: showing JARVIS's reply as text in the page (needs a read-only, redacted log event).

## 16. Controls — interrupt, mute, fullscreen

`control.do` (closed set: `interrupt`, `mute`, `unmute`, `fullscreen`) via `ControlGate` in Python. Rule: things that stop or quiet JARVIS are always allowed; turning the microphone back **on** is refused from the page while the assistant is locked, awaiting a PIN, silent, or in guest mode (same availability check as the command bar). Idempotent (`noop` when already in that state), 0.3 s spacing, unknown actions do nothing, missing sink means unavailable. Actions call the classic window methods, so there is one implementation. Tests: Python +8, Vitest +4; real QtWebEngine: mute works, unmute while locked is refused and the mic stays muted.

## 17. Conversation log — read-only mirror

A read-only view of the HUD log (You / JARVIS / System / Error / File lines). There is no request that writes to it.

**The hazard found while designing it:** the classic typed-text box writes `You: <text>` to the log *before* it knows the text is a Privacy Lock PIN, so a PIN typed in the native prompt lands in the log. Forwarding the log naively would send PINs to the web layer. So:

- `jarvis/core/log_tap.py`: a minimal observer hook called from `LogPanel.append_log` (the one choke point).
- `LogFeed` judges every line **at the moment it is logged**, on the logging thread: if the assistant is not fully normal and unlocked (locked, awaiting PIN, silent, guest, or state unprovable) nothing is forwarded. A PIN logged while `auth_required` can never leak even if the PIN is accepted a moment later.
- `redact.py`: `SEC:` lines and credential-shaped input are dropped; API keys, JWTs, bearer/token/password/pin assignments and any long opaque token become `[redacted]`; home folder names become `~`; control characters stripped; 400-char lines.
- Rate limit: burst 40, then 10 lines/s. Page keeps the newest 200 lines; "Clear view" only clears the page's memory.
- Page renders text as text (no HTML), `role="log"`, `aria-live="off"` to avoid flooding screen readers.
- New window kind `log` (schema updated in Python and TS) and the `chat` page now shows it.

Tests: Python +21 (kinds, 8 secret shapes, home folders, all five blocked states, PIN-then-verified, fail-closed, flood cap, unsubscribe, observer isolation), Vitest +3. Real QtWebEngine run shows redaction and that a PIN typed during `auth_required` never reaches the page.

Not covered: persistent history (the log is this session only) and search.

## 18. Loading feedback and optimistic updates

Rules (`frontend/src/ux/phase.ts`, one place, unit-tested):

| Pending for | Shown |
|---|---|
| under 1 s | nothing |
| 1 s to 10 s | skeleton of the page (home widgets) and a quiet status label |
| over 10 s | progress bar and "about N s left (estimate)" |

The backend reports no real progress, so the bar and time left are an honest estimate: per-operation moving average of past durations, never 100 % before completion, growing when it overruns, and always labelled "(estimate)". An operation that never answers is dropped after 60 s with a notice.

Tracked operations: connecting (until `host.hello`), first live data, `workspace.load`, named save/delete, `command.submit`, `control.do`. Autosave (`_last`) is silent.

Tap first, sync later (`ux/actions.ts`): mic mute/unmute flips the UI at once; `assistant.muted` confirms, a refusal `control.result` (locked, guest, ...) or a 6 s silence rolls it back with a notice. Workspace save/delete update the list at once; `workspace.list` from Python reconciles (a missing answer triggers a re-sync). Python stays the authority; window moves are local and already instant. Skeletons are aria-hidden and static under reduced motion.

## 19. Reply panel

`ui/Reply.tsx` shows the latest exchange (your last line and JARVIS's answer, consecutive JARVIS lines joined, max 6) above the command bar. It is derived only from the existing log mirror, so it inherits the same redaction and the same rule that nothing is shown while locked, awaiting a PIN, silent or in guest mode. Read-only; text is rendered as plain text (escaped); dismissing hides it until the next reply. Limitation: it appears when Python writes the reply to the HUD log, so it is not a live token stream.

## 20. Accessibility audit (axe-core)

An automated axe-core run inside the real QtWebEngine page (home, settings open, palette open, timer window open) found 3 serious/moderate rule failures: a labelled `div` with no role (hologram), controls whose `aria-label` did not contain their visible text (Island and widgets), and content outside landmarks. All fixed (visible text now forms the accessible name, with a visually hidden "Open ..." suffix; the stage and controls are landmarks). Result: 0 violations in those four states, no colour-contrast failures. This is an automated check only; it does not replace a manual NVDA pass, which is still open in the parity checklist.

## 21. Persona, performance writes and the Dashboard window

`control.do` gained `mode_jarvis`, `mode_bihansa`, `perf_auto|full|balanced|lite`. They use the same `ControlGate` as unmute: refused unless the assistant is in a fully normal state (not locked, awaiting a PIN, silent or in guest mode), rate limited, and answered `noop` when already in that state. Python applies them through the existing HUD methods (`_mode_btn`, `set_performance_budget(save=True)`), so behaviour and persistence match the classic menu; the page then learns the result from the normal `ui.persona` / `ui.perf` events. The page does not decide anything.

New window kind `bento` ("Dashboard"): cards for assistant, model, CPU/RAM, network and storage from the data already mirrored; nothing invented ("not reported" / "collecting" when absent). An axe-core run in the real engine over Settings and the Dashboard window reports 0 violations.

Deliberately not built (documented in the parity checklist): the native media/tool windows, wake, task events and notification centre, persistent chat history. Each needs a backend or a privacy design first.
