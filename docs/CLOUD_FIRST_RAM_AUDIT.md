# Cloud-first & 4 GB RAM audit — 2026-10-28

This is the audit behind the changes on `arena/c888c855-jarvis-ai-pro`. It records
what was **verified in the repository**, what was **measured**, and what still
**needs the Windows laptop**. Nothing here is inferred from documentation alone.

---

## 1. Method and limits

* **Static inspection** of the real modules (entry points, audio, routing, screen
  intelligence, agent, memory, security, UI) plus the existing tests and CI.
* **Measured runs** in the agent's Linux sandbox: Python 3.11, PyQt6 6.12,
  `QT_QPA_PLATFORM=offscreen`, and hand-built stub `libxkbcommon`/`libdbus`/`libGL`
  shims because the sandbox image lacks those system libraries.
* **Not measurable here**, and therefore not claimed:
  * Windows RSS of the Chromium (Qt WebEngine) libraries — they cannot even load
    in this sandbox (missing `libxcb-dri3`);
  * PortAudio device behaviour, microphone/speaker timing;
  * Gemini Live network behaviour, quota errors;
  * the live Supabase project (needs credentials).
* Every number below is sandbox-measured. **They are not your laptop's numbers.**

---

## 2. What the repository already contains (verified)

| Area | Where | State |
| --- | --- | --- |
| Entry point | `main.py` → `JarvisAI/main.py` (`main()`), `run.py` | single window: `HologramHUDUI`; the legacy `JarvisUI` is never instantiated (`main.py` refuses the fallback) |
| Live voice | `JarvisAI/main.py` + `core/live_audio.py`, `core/audio_capture.py`, `core/audio_playback.py` | 16 kHz in / 24 kHz s16 mono out, prebuffer, barge-in, viseme synthesis |
| Text fallback routing | `core/hybrid_llm_router.py` (`HybridLLMRouter`) used by `agent/integration.py`, `core/ai_error_repair.py` | Gemini/Groq/OpenAI/Claude order, offline Ollama fallback |
| Cloud AI proxy | `supabase/functions/jarvis-cloud-ai/index.ts` | server-side provider multiplexing with host-key signature auth |
| Cloud memory | `core/personal_cloud_memory.py`, `supabase/functions/jarvis-personal-memory`, migration `202610270001_jarvis_personal_memory.sql` | RLS enabled on both tables, consent gated, allowlisted fact keys, local+server validators |
| Screen intelligence | `agent/screen_vision.py`, `agent/computer_use.py`, `actions/screen_processor.py` | accessibility tree → OCR → cloud vision, cheapest first |
| Autonomous tasks | `agent/` (`planner`, `runner`, `journal`) | retries, deadlines, loop detection, resumable JSON/journal |
| Security | `core/security.py`, `security/`, `core/confirm.py` | rate limits, dangerous-action windows, owner voice ID + PIN, Privacy Lock |
| UI | `ui/hud_main.py` (Hologram HUD), `ui/__init__.py` (legacy 5k-line UI), `ui/hologram/*` | copper wireframe face, heart/orb, Bihansa mode, task panels |

---

## 3. Findings

### 3.1 Critical security / reliability issues

**None found in the reviewed code paths.** Evidence:

* `alter table … enable row level security` on both personal-memory tables
  (`supabase/migrations/202610270001_jarvis_personal_memory.sql:9,29`).
* No service-role key anywhere in the desktop code: `grep -rn "service_role" JarvisAI`
  returns nothing; privileged work happens in the Edge Function.
* Secret redaction runs before provider requests and before summaries are stored
  (`memory/memory_manager.py:1133 redact_sensitive_content`).
* Rate limiting for costly/dangerous tools exists (`core/security.py:411-420`,
  windowed deques, 4 dangerous calls / 300 s).
* The remote Supabase configuration (project `mcjsicxdlsjhenzpssqd`, region
  `ap-south-1`) was **not** contacted; its state must be verified by the owner
  (see §6).

### 3.2 High-priority bugs

**None reproduced.** Running the suite (`836 passed, 1 skipped`) produced no
failing audio, auth, routing or UI test. The previously reported playback issues
are covered by `test_playback_interrupt.py`, `test_pending_playback_interrupt.py`,
`test_audio_recovery_regressions.py`, `test_live_pcm_buffering.py` — all green.

### 3.3 Memory / performance bottlenecks (evidence + action)

| # | Finding | Evidence | Action |
| --- | --- | --- | --- |
| 1 | **Qt WebEngine was imported at startup.** `ui/__init__.py` eagerly imported `PyQt6.QtWebEngineCore/Widgets` and the two WebEngine-backed panels (`core.earth_globe`, `core.hud_workspace`). The Hologram HUD never constructs any of them; `main.py` explicitly refuses the legacy UI. | measured below | **fixed** (lazy, `core/qt_webengine.py`) |
| 2 | **Every screenshot did a PNG round-trip.** `_capture_screen` encoded raw RGB → PNG, then PIL decoded it, thumbnailed and re-encoded JPEG. | 251 ms → 26 ms measured on a synthetic 1920×1080 frame; output byte-identical | **fixed** (`actions/screen_processor.py`) |
| 3 | **OpenCV was imported at startup** for a camera feature used rarely; screen capture itself only needs `mss`. | `import cv2` at module level; camera is the only consumer | **fixed** (lazy, guarded) |
| 4 | `google.genai` costs 584 ms / 63 MB peak at import. | measured | **not changed** — the live session needs it immediately; deferring it would only move the cost |
| 5 | The Live playback `asyncio.Queue` is unbounded. | `HYBRID_ROUTING_RAM_AUDIT_STEP_1B.md`; `main.py` playback queue | **not changed on purpose** — dropping queued PCM can truncate valid speech. Needs the Windows stall/barge-in test described in §5 |
| 6 | HUD polling | `_poll_timer` 1.5 s, `_status_timer` 5 s, one shared probe thread | bounded and already documented; no change |

Measured (`import` in a fresh interpreter, median of 5 runs, peak RSS includes
the ~10 MB interpreter baseline):

| Measurement | before | after | delta |
| --- | --- | --- | --- |
| `import ui` | 137 ms / 69 MB peak | 109 ms / 49 MB peak | −28 ms, −20 MB |
| `import ui.hud_main` (the HUD the app actually runs) | 164 ms / 62 MB peak | 150 ms / 58 MB peak | −14 ms, −4 MB |
| one 1920×1080 screenshot encode | 251 ms | 26 ms | **−225 ms per screenshot** |

The WebEngine saving measured here is only the Python-side part: in this sandbox
Chromium cannot load at all, so its libraries were never mapped. On Windows the
same deferral additionally avoids mapping Chromium into the HUD process — that is
the number the RAM profiler exists to capture (§5). **Do not quote a Windows MB
figure until it has been measured.**

### 3.4 Architecture / cloud-migration gaps

* **Cloud is already the default for reasoning.** `jarvis-cloud-ai` proxies
  Gemini/OpenAI/Groq/Anthropic server-side behind a host-key signature; personal
  memory lives in Supabase behind RLS + an Edge Function. No new paid resource was
  created or reconfigured by this branch.
* **Gap — cloud scheduling does not exist.** `actions/reminder.py` schedules on the
  local OS (Task Scheduler / launchd / cron). Nothing fires while the laptop is
  off, and this branch does not claim otherwise. A real implementation needs a
  hosted queue (e.g. `pg_cron` + Edge Function) plus a device-side delivery path;
  that is infrastructure work, not a code tweak, and it was not attempted.
* **Gap — autonomous tasks are in-process.** `agent/` persists resumable state, but
  a task stops when the app closes. Moving it to a cloud worker is the same class
  of work as the scheduler gap.
* **Local control is correctly local.** Screen capture, OCR, mouse/keyboard and
  app/file operations never leave the machine except as explicitly uploaded
  frames through the vision provider.

### 3.5 UI / voice

* The hologram, heart/orb, task panels, Bihansa mode and the responsive chrome are
  unchanged by this branch; the HUD path is byte-identical in behaviour.
* The legacy `JarvisUI`/immersive overlay/globe/workspace still work — they now
  import WebEngine when they are actually constructed.
* No voice or audio code was modified, so the existing voice tests remain the
  regression net.

### 3.6 Testing / maintenance

* Suite: **836 passed, 1 skipped, 109 subtests** (skip: camera test cannot load
  `cv2` because the sandbox has no real `libGL`; it passes on CI where
  `libgl1`/`libegl1` are installed). `ruff check JarvisAI` clean.
* New regression guards: import-boundary tests (subprocess + meta-path recorder)
  that fail if the HUD import starts pulling Chromium, OpenCV or the WebEngine
  panels again.

---

## 4. Files changed in this branch

| File | Why |
| --- | --- |
| `JarvisAI/core/qt_webengine.py` | new: one place that decides when Chromium loads; cached, thread-safe, honest about availability |
| `JarvisAI/ui/__init__.py` | WebEngine, `EarthGlobePanel` and `HudWorkspace` imported on first use instead of at package import |
| `JarvisAI/actions/screen_processor.py` | direct RGB→JPEG encode (no PNG round-trip); OpenCV loaded on first camera use |
| `JarvisAI/tools/profile_ram.py` | RAM profiler (adopted from PR #143, split into testable helpers, `--label`/`--append`) |
| `JarvisAI/tools/__init__.py` | package marker so the tool is importable from tests |
| `JarvisAI/tests/test_lazy_ui_imports.py` | import-boundary + laziness + WebEngine helper + camera-fallback tests |
| `JarvisAI/tests/test_screen_capture_encoding.py` | direct path, byte-identical output, fallbacks, mss-missing message |
| `JarvisAI/tests/test_ram_profiler.py` | real-process sampling, CSV append, CLI validation |
| `docs/CLOUD_FIRST_RAM_AUDIT.md` | this report |

Nothing in `AuthManager`, `ActionDispatcher`, Privacy Lock, owner voice ID, PIN
fallback, the hologram renderers, the Live audio pipeline or the Supabase schema
was modified.

---

## 5. What still needs your Windows laptop

1. **Measure the real baseline.** With JARVIS running:

   ```bat
   python tools\profile_ram.py --pid <python.exe pid> --duration 120 --label idle
   python tools\profile_ram.py --pid <pid> --duration 60 --label voice --append
   python tools\profile_ram.py --pid <pid> --duration 60 --label screen --append
   python tools\profile_ram.py --pid <pid> --duration 60 --label hologram --append
   ```

   Read `uss_mb` (the honest "cost of JARVIS") and `system_available_mb` on a 4 GB
   machine. Compare with the same runs on the previous commit to size the WebEngine
   win — that comparison is the missing measurement, not a code question.

2. **Prove the deferred features still open**: the immersive overlay / neural-hand
   view, the Earth globe panel and the document workspace each construct a
   `QWebEngineView` on first use now. Open each once and confirm Chromium starts
   then (not at launch).

3. **Camera**: `_capture_camera()` now imports OpenCV on first call. Ask JARVIS to
   look through the camera once and confirm the frame arrives.

4. **Playback queue under stall** (unchanged code, still unverified): play a long
   reply, pause speaker output (or unplug the audio device) for ~10 s, then resume.
   If voice comes back late-but-complete, the queue drains correctly; if memory
   grows without bound, a bound is justified and can be added with a drop policy
   that preserves the tail.

5. **Gemini Live / Supabase**: connect with real keys to confirm the network paths
   this sandbox cannot exercise.

---

## 6. Configuration and secrets

No new keys, projects or paid services are required for the changes here.

To verify cloud memory on your machine (read-only checks first):

* Supabase project `JARVIS-AI-PRO` (`mcjsicxdlsjhenzpssqd`, `ap-south-1`) — confirm
  in the dashboard that `public.jarvis_personal_memories` and
  `public.jarvis_personal_memory_settings` show **RLS enabled** and that the
  `jarvis-personal-memory` function is deployed.
* The desktop app should hold only the anon key plus the host-key material — never
  a service-role key. Do not paste keys into an issue or PR.

---

## 7. Not done, on purpose

* No bounded playback queue (needs the stall test above; a wrong bound truncates
  speech).
* No cloud scheduler / cloud task worker (needs hosted infrastructure and a cost
  decision).
* No dependency removal: `cv2`, `playwright`, `QtWebEngine` are all still declared
  and still used — they are simply no longer imported until needed.
* No change to authentication, memory schema, prompts, or the hologram renderers.
