# JARVIS AI — Project Map and Health Snapshot

A practical orientation document: what the app is, how a request flows through
it, which module owns what, and what state the codebase is in today. Written
after a full read/run of the repository (static inspection + full test suite).

---

## 1. What this is

A **local-first, cross-platform desktop voice assistant** (`Python ≥ 3.11`,
PyQt6 HUD, Gemini Live audio session). One process owns the microphone, the
speaker, the holographic HUD, the tool/security pipeline and a background
autonomous task engine.

* **Primary target:** Windows 10/11 laptop (the docs repeatedly optimize for a
  4 GB machine); macOS and Linux are supported.
* **Not** a web app. The only HTTP surface is the *remote dashboard* (FastAPI +
  Uvicorn) used by a phone/tablet, plus optional Supabase Edge Functions.
* Everything personal (memory, PIN vault, audit ledger, API keys) lives in
  `JarvisAI/config/` and `JarvisAI/memory/`, never in the checkout.

### Size at a glance

| Area | Python LOC | Notes |
| --- | --- | --- |
| `JarvisAI/ui/` | ~15.7 k | HUD + panels; `ui/__init__.py` alone is 8,600 lines |
| `JarvisAI/core/` | ~21.4 k | 74 modules: audio, LLM routing, security, HUD workspace, visuals |
| `JarvisAI/actions/` | ~15.3 k | 40 auto-discovered tool modules |
| `JarvisAI/tests/` | ~13.6 k | 76 modules, 773 collected tests |
| `JarvisAI/agent/` | ~5.9 k | Autonomous task engine (plan → act → verify → report) |
| `JarvisAI/memory/` | ~4.3 k | Multi-type memory + audit chain + retrieval |
| `JarvisAI/plugins/` | ~2.7 k | 10 drop-in plugins + template + loader tests |
| `JarvisAI/dashboard/` | ~2.2 k | FastAPI remote dashboard, AES session tokens, TLS |
| `JarvisAI/security/` | ~1.2 k | Auth manager, PIN, voice/face auth, lockdown |
| `supabase/` (TypeScript/SQL) | ~700 | 2 edge functions + 2 migrations |
| **Python total** | **~88.9 k** | ~75 k source, ~14 k tests |

---

## 2. Runtime architecture

```
main.py / run.py  ──►  JarvisAI/main.py :: main()
                         │
                         ├─ HologramHUDUI  (ui/hud_main.py)   ← Qt main thread
                         │     └─ HudWorkspace, DynamicIsland, panels/
                         │
                         └─ thread: JarvisLive.run()  (asyncio)
                               ├─ Gemini Live session (audio in/out, tools)
                               ├─ audio capture / playback / VAD / wake word
                               ├─ _execute_tool → security.guard → registry
                               │        ├─ ActionRegistry  (actions/*.py, 40 tools)
                               │        └─ PluginRegistry  (plugins/*.py, 10 tools)
                               ├─ memory.memory_manager (local JSON + audit chain)
                               ├─ agent.integration.AgentService (autonomous tasks)
                               └─ dashboard/server.py (FastAPI, optional)
```

Key entry points:

* `main.py` (root) — thin shim that puts `JarvisAI/`, repo root and `voice/` on
  `sys.path` and re-exports `JarvisAI.main`.
* `run.py`, `setup.py` (root) — same pattern for the runtime and installer.
* `JarvisAI/main.py` — real entry point: `--headless` (daemon, no Qt),
  `--hologram-hud`, otherwise the HUD. The legacy `ui.py` window is **removed**;
  `main()` refuses to fall back to it.
* `JarvisAI/tools/windows_setup.py` — the Windows installer/repair/launch CLI
  wrapped by `Jarvis_Setup.bat` and `Run_Jarvis.bat`.

Notable global behaviour in `JarvisAI/main.py`:

* Patches `subprocess.Popen` on Windows to force `CREATE_NO_WINDOW`.
* Reconfigures stdout/stderr to UTF-8 so emoji log lines cannot crash a
  non-UTF-8 Windows code page.
* Sets QtWebEngine Chromium flags *before* any Qt import
  (`core/qtwebengine_flags.py`), and imports Chromium lazily
  (`core/qt_webengine.py`) to keep HUD start-up RAM down.

---

## 3. The security contract (the most important design decision)

Every tool call — hardcoded branch, bundled action, or plugin — is wrapped in
`core/security.py::guard(name, params, run)`:

1. **Risk tier** — `TIER_SAFE / TIER_SENSITIVE / TIER_DANGEROUS` from
   `core/security.py` (tier table), with `core/dispatcher.py` deciding
   restricted-vs-owner-privileged (unknown actions default to privileged).
2. **Privacy Lock / re-auth window** — denies *everything*, including reads.
3. **Owner verification** — `security/auth_manager.py` states
   (`FULL_ACCESS_MODE`, `RESTRICTED_MODE`, `PRIVACY_LOCK`). Voice sessions are
   revalidated per sensitive turn; speaker-role labels never grant access.
4. **Provenance guard** (`core/injection_guard.py`) — text that arrived from a
   web page, email or document is treated as untrusted and cannot silently drive
   a consequential action.
5. **Human confirmation** (`core/confirm.py`) — banner + voice confirmation for
   consequential steps; `confirm.resolve_by_voice` still requires owner + live
   speech anti-spoof.
6. **Rate limiting** — per-window caps, because an injected instruction loop
   looks like a burst.
7. **Tamper-evident ledger** — SHA-256 chain + HMAC anchor in
   `core/security.py`, written to `JarvisAI/security/audit_log.jsonl`.

Memory has its own parallel integrity chain (`memory/memory_audit.py`, node
signatures and an anchor), with a recovery tool (`Repair_Memory_Audit.bat`,
`repair_memory_audit.py`).

---

## 4. Tools: discovery, not registration

`core/action_loader.py` and `core/plugin_loader.py` scan their folders at
start-up. A module exposes a module-level `TOOL` dict
(`name`, `description`, `parameters`, `handler`, optional
`behavior=NON_BLOCKING`, `scheduling=WHEN_IDLE|SILENT|INTERRUPT`). Handlers are
invoked by signature introspection, receiving only the context kwargs they
declare (`player`, `speak`, `response`, `session_memory`).

Consequences worth knowing:

* Adding an action = one file, no edit to `main.py`.
* A broken action/plugin is logged and skipped; discovery never aborts.
* 40 actions + 10 plugins + the hardcoded branches in `_execute_tool`
  (memory, undo, screen capture, system status, shutdown, dashboard, ...).

---

## 5. Memory

`memory/memory_manager.py` is the façade (1,798 lines) over a layered model:
semantic, episodic, procedural, prospective, autobiographical, associative,
plus `retrieval_engine` (scoring), `consolidation`, `reflection`,
`lifecycle`, `memory_safety`, `adaptive_memory`.
`memory/memory_scoring.json` and `planner_config.json` are tunables.

* Local store: `memory/long_term.json` (atomic writes, migration backups).
* Redaction before anything leaves the machine (`provider_safe_memory`,
  `redact_sensitive_content`).
* Optional Supabase "personal cloud memory" (`core/personal_cloud_memory.py`,
  `supabase/functions/jarvis-personal-memory/`) — opt-in, validated server-side
  in TypeScript with Deno tests.
* Offline retrieval eval harness: `eval/run_eval.py` + `eval/cases.jsonl`.

---

## 6. Autonomous agent and computer use

`JarvisAI/agent/` is a self-contained, testable subsystem:

| Module | Role |
| --- | --- |
| `planner.py` | model-driven or deterministic plan; validated steps |
| `runner.py` | bounded execution, retries/backoff, deadlines, loop detection |
| `executor.py` | step kinds, context, per-step risk |
| `policy.py` | risk classification + approval decisions |
| `store.py` | resumable JSON state + fsynced journal |
| `computer_use.py` | named-target desktop actions, dry-run, re-observation |
| `screen_capture.py` / `screen_vision.py` | on-demand capture, local OCR, Gemini/OpenAI vision, accessibility tree |
| `voice.py` | stop/pause/resume/status/report routing |
| `presentation.py` / `events.py` | dashboard card + Dynamic-Island summaries, event bus |
| `integration.py` | `AgentService` singleton wired into `main.py` and UI |

Safety is inherited, not re-implemented: steps go through the same tiering and
confirmation gate; emergency stop is never gated.

---

## 7. UI surface

* `ui/hud_main.py` — `HUDMainWindow` (2,018 lines) + `HologramHUDUI` façade,
  first-run setup controller (API key, owner PIN), start-up wiring.
* `ui/__init__.py` — legacy `MainWindow` (8,600 lines) plus the drawing
  primitives, overlays and dialogs still reused (avatar canvas, confirm banner,
  provider tiles, memory overlay, …). This is the single largest file in the repo.
* `ui/hologram/` — copper/amber wireframe face, neural heart reactor, settings.
* `ui/panels/` — telemetry ring, memory, scheduler, security, battery, hybrid
  brain, modern dashboard.
* `core/hud_workspace.py` — the in-HUD "workspace" tabs: Earth globe, video,
  web reader, image gallery, PDF reader, news/email/calendar, telemetry.
* `core/neural_viz.py` (1,435) — the neural field visualisation; `assets/holo/`
  carries local MediaPipe/Three.js bundles for hand + face tracking.

---

## 8. Remote dashboard and cloud

* `dashboard/server.py`: FastAPI app, short-lived AES-encrypted session tokens,
  origin-validation middleware, rate limiting on login, optional TLS with a
  self-signed cert, ADB reverse-port-forward path for USB tablets, Twilio media
  stream endpoint for the phone assistant.
* `dashboard/static/` — `login.html`, `app.html`, `crypto-js.min.js`.
* `supabase/functions/jarvis-cloud-ai` (provider proxy) and
  `jarvis-personal-memory` (validated, typed, with Deno tests); migrations under
  `supabase/migrations/`.

---

## 9. Testing, lint, CI — measured today

Run in this sandbox (`Python 3.11`, full `requirements.txt` installed,
`QT_QPA_PLATFORM=offscreen`):

| Check | Result |
| --- | --- |
| `ruff check JarvisAI` (the CI gate) | **clean, 0 findings** |
| `python -m compileall JarvisAI` | clean |
| `pytest JarvisAI` | **751 passed**, 109 subtests, 14 skipped, 3 failed + 6 errors |
| Coverage (line) | 27 % overall; **35 %** excluding `ui/` and `main.py`; `ui/__init__.py` 1 %, `ui/hud_main.py` 0 %, `main.py` 16 % |

The 3 failures / 6 errors are **environmental, not code**: this container has no
`libGL`/`libxkbcommon`, so `import PyQt6.QtWidgets` fails and
`tests/test_lazy_ui_imports.py` cannot spawn its probe; `test_battery_settings`
and `test_agent_ui` error for the same reason. CI installs `libgl1 libegl1` and
runs those Qt tests on both Linux and Windows.

CI (`.github/workflows/python-checks.yml`):

1. **lint** — ruff only, no deps, ~seconds.
2. **checks** (Ubuntu) — install requirements, `compileall`, `diagnose.py`,
   full pytest, failure annotations through `scripts/ci_pytest_annotate.py`,
   plus Deno type-check/tests for the Supabase function.
3. **windows-ui-smoke** (Windows, offscreen) — the Qt/launch/auth/audio subset,
   installer CLI contract (`status`/`verify` must exit 1 without `.venv`), and a
   smoke of the `.bat` files.

Test suites worth knowing about beyond unit detail:

* `test_project_health.py` — static import-graph check: fails if any module
  imports a name its target no longer defines. Passes (10 tests).
* `test_ui_import_smoke.py` / `test_lazy_ui_imports.py` — every `ui/` module
  imports once; the HUD import must not drag in Chromium/OpenCV.
* `test_security_end_to_end.py`, `test_owner_identity_security.py`,
  `test_security_hardening.py` — the guard pipeline.
* `test_agent_*` (6 files) — planner/runner/vision/voice/UI.

Conventions enforced in code review checklists (`docs/DEVELOPMENT.md`,
`pyproject.toml`): no bare `except: pass` (use `core/failsoft.suppress`, which
records the suppression and is printed under `JARVIS_FAILSOFT_REPORT=1`), no
new dependency without a version cap, no module-level Qt/WebEngine import.

---

## 10. Observations and open risks

1. **Documentation drift.** The README's project-structure block still lists
   `JarvisAI/ui.py` and `security/audit_log.jsonl` under `security/`, but `ui.py`
   no longer exists and the HUD moved to `ui/hud_main.py`. The README is 112 kB;
   its accuracy is load-bearing for users and is hard to keep current by hand.
2. **Two very large files.** `ui/__init__.py` (8,600 lines) and
   `JarvisAI/main.py` (4,899) hold most of the untested code (1 % and 16 %
   coverage). Splitting `main.py`'s `_execute_tool` (2,300 lines of hardcoded
   tool branches) into the `actions/` discovery pattern would shrink it a lot.
3. **Overlap / dead weight.** `voice/persona.py` at the repo root is byte-identical
   to `JarvisAI/voice/persona.py`; `actions/holo_gestures.py` and
   `actions/earth_globe.py` are thin wrappers over `core/` equivalents. Harmless,
   but they widen the surface new contributors must learn.
4. **15 open PRs, 14 of them UI/hologram work** (`#148`–`#162`, from
   "restore pre-upgrade HUD" to "sharpen the neural face"), several mutually
   exclusive. This — not the code — is currently the biggest source of risk:
   the hologram composition is being edited from a dozen directions at once.
   `docs/OPEN_PR_RECONCILIATION.md` documents an earlier consolidation of a
   similar pile-up and is a good template for doing it again.
5. **Heavy Qt coupling in tests.** Only 35 % coverage runs headless here; the
   most complex UI (the HUD) is validated by import smoke tests plus a Windows
   offscreen subset, not by behaviour tests.
6. **Sandbox/lint ratchet is healthy.** 0 ruff findings and one commit's worth of
   clean `compileall` is a good baseline; the fail-soft discipline (283
   `failsoft.suppress` call sites vs 991 broad `except Exception`) is real, if
   still partially ungated.

---

## 11. Sensible next steps (in suggested order)

1. Reconcile the open UI PRs (pick a canonical hologram, close the rest) — the
   repo is otherwise green and the merge queue is the bottleneck.
2. Update the README structure/feature sections to match the current tree and
   link this map.
3. Split `_execute_tool`'s hardcoded branches into discovered actions, then
   shrink `JarvisAI/main.py` to session lifecycle only.
4. Add behaviour tests around `HUDMainWindow` (offscreen) before the next UI
   refactor, so the hologram work cannot silently regress.
5. Delete the duplicated `voice/persona.py` shim at the root, or make it a real
   re-export with a comment, and document `actions/` vs `core/` split.
