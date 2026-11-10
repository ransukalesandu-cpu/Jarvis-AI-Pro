# JARVIS AI PRO — Full Runtime Integration Audit and P0 Remediation Plan

**Status:** Gate A (research and plan), approved by the owner 2026-11-10 for P0-1. This document itself changes no runtime code, settings, database or Supabase configuration.
**Inspected:** `main` @ `28c2889d6571fe58f9cf8113428dfdaf2e63a21d` (merge of PR #285), 2026-11-10.
**Environment:** Linux container, Python 3.13, Node 22. No Windows desktop, GPU, microphone, speakers, PyQt6 or Gemini key, so nothing here was measured on the owner's laptop.

Evidence labels used below:

* **CONFIRMED (runtime):** reproduced by running the real code path in this container. Probe scripts are listed in §15.
* **CONFIRMED (code):** read from the source; not executed end to end.
* **HYPOTHESIS:** plausible from the code, but it needs a measurement before it is treated as fact.

---

## 0. Executive summary

The repository is large (≈100k lines of Python, 87 tools when Computer Control is on) and well tested in isolation: 1670 Python tests and 76 frontend tests pass. The security layer is real and consistently applied. The problem the owner feels, "many features, little day-to-day improvement", has concrete causes in the *integration*, not in missing modules.

1. **The autonomous agent cannot start a single task unless Supabase personal memory is fully configured.** The agent's default store is cloud-only, so without Supabase every `autonomous_task` call (start, status, list) and every scheduled "task" trigger fails. The README calls that Supabase feature *opt-in and off by default*, and `docs/AUTONOMOUS_AGENT.md` still describes local persistence. The tests inject a local store, so CI never sees this. *(CONFIRMED, runtime.)*
2. **The Computer Control Engine (Projects 0–8) is invisible in normal use.** The only way to turn it on is an environment variable. There is no settings control, no voice path and no status surface. While it is off, even its status tool is hidden, so the owner cannot ask JARVIS why it is off. *(CONFIRMED, runtime.)*
3. **When it is on, it competes with older tools for the same jobs.** The model then sees 87 tools (≈84 KB of declarations per connection), with six overlapping groups: three app launchers, three file tools, three screen tools, five click/type tools, two browser tools and three multi-step task runners. The older ones use stronger wording ("Always call this tool", "MUST be called"), and the system prompt says "Prefer a direct tool over the planning agent". *(Overlap CONFIRMED, runtime; its effect on the model's tool choice is a HYPOTHESIS to measure.)*
4. **Background automation lives inside the voice connection.** The trigger scheduler is a task in the per-session Gemini Live task group, so no trigger fires while Live is disconnected. Task-mode triggers also inherit problem 1. *(CONFIRMED, code.)*
5. **Several surfaces report a state that is not true.** `docs/ROADMAP.md` lists merged work as "not started". `diagnose.py` reports Edge TTS as the "default speech engine", but nothing uses it. The multi-device launcher scripts were broken by the package restructure (fixed on an unmerged branch). `self_check` says "Autonomous task state unavailable" without the reason. *(CONFIRMED.)*

None of these needs a rewrite. Each P0 item in §12 is a small, testable PR against existing modules.

---

## 1. Inspected state and overlap with other work

| Item | State |
|---|---|
| `main` | `28c2889`, Computer Control Projects 0–8 merged (#277–#285) |
| Open PRs | **None** (checked through the GitHub API) |
| Branches with unmerged commits | `claude/magical-maxwell-4k08ak`: worker node + Phase 0 "Iron Man" audit (57 files, +4226, not opened as a PR). `claude/zealous-volta-haz97s`: launcher script fix (this session, 1 commit). `hologram-v2/*`: superseded and reverted |
| Earlier audits to reuse, not repeat | `docs/plans/IRON_MAN_UPGRADE_PHASE0_AUDIT.md` (on `magical-maxwell`: multi-device, proactive, hologram), `docs/research/router-engine-audit.md`, `docs/research/voice-and-nodes-audit.md`, `docs/computer-control/*`, `docs/architecture/WEB_UI_PARITY.md` |
| Supabase | Project `JARVIS-AI-PRO` (the ref in `docs/SUPABASE_HYBRID_PROVIDER_SETUP.md`) is ACTIVE_HEALTHY. Edge functions `jarvis-cloud-ai` v8, `jarvis-personal-memory` v3 (deployed 2026-11-02 06:16 UTC; same operation set as the repo copy, including `agent_task_*` and `workflow_*`) and `jarvis-default-owner-memory` v1 are deployed. **Database queries (tables, RLS, extensions, migrations) timed out three times**, so table presence, RLS and pgvector are **unverified** |

---

## 2. Architecture map and runtime entry points

```text
python main.py / run.py / Run_Jarvis.bat
  └─ jarvis.main.main() → core/runtime/bootstrap.run_application()
       ├─ UI: legacy PyQt HUD (jarvis/ui/__init__.py, 6.7k lines) — DEFAULT
       │    └─ optional React web UI mounted over it when JARVIS_UI=web (jarvis/webui/__init__.py:20)
       └─ JarvisLive (jarvis/main.py:691) — one Gemini Live native-audio session
            ├─ tools = 12 inline (main.py:435) + actions/*.py (action_loader) + plugins/*.py
            │          filtered by each tool's `available()` (action_loader.py:102) and
            │          JarvisLive._keep_declaration (main.py:1519, currently always True)
            ├─ tool call → core/runtime/live_tools._execute_tool (timeout, jobs, action log)
            │          → _execute_tool_impl → core/security.guard() on every branch
            │             (guest → Privacy Lock → provenance/untrusted → step-up auth →
            │              ActionDispatcher tier → rate limit → DANGEROUS confirm banner → audit)
            ├─ background tasks in the *session* TaskGroup (main.py:3060-3064):
            │          system monitor, background monitor, proactive mode, trigger scheduler, sleep watch
            └─ text-only fallback when Live is down (main.py:1111 → provider_fallback, BrainEngine)

Execution engines reachable from tools
  autonomous_task  → agent/ TaskRunner (plan→act→verify; store = CloudTaskStore → Supabase)
  cc_task, cc_*    → computer_control/ ActionRunner + orchestrator HostAgent (JobManager jobs)
  long_running tools → core/jobs.JobManager (asyncio jobs; the web UI Jobs window's only source)

Other entry points
  python -m jarvis.hub / jarvis.laptop_agent   multi-device hub mode (separate from desktop mode)
  dashboard/server.py (FastAPI)                phone/browser dashboard, loopback by default
```

---

## 3. Feature inventory

Status vocabulary from the directive §6.3.

| Area | Feature | Status | Evidence |
|---|---|---|---|
| Voice | Gemini Live native-audio session, reconnect, session resumption, model fallback between 3 Live models | implemented but unverified on owner hardware | `main.py:185-193`, `core/live_session.py`; audio paths cannot run here |
| Voice | Alternate STT/TTS (Edge TTS, Kokoro, ElevenLabs, pyttsx3) | **implemented but not integrated** (dead code) | `core/tts.py` has no importers; `voice/speech_engine.py` is imported only by its test |
| Routing | Text-only provider fallback when Live is down (no tools, honest prompt) | implemented, partially tested | `core/provider_fallback.py:17-28`, `main.py:1111` |
| Routing | Realtime voice failover to a non-Gemini provider | planned only | nothing exists |
| Security | `guard()` pipeline, tiers, Privacy Lock, guest mode, step-up, rate limit, audit ledger | working (tests) + unverified on owner hardware (voice ID, PIN dialog) | `core/security.py:962-1105`; every branch of `live_tools._execute_tool_impl` calls it |
| Agent | Autonomous TaskRunner (plan, act, verify, recover, pause, resume) | **broken in default configuration** | §4 B1 |
| Computer control | Policy/approval/audit/estop/runner | working in tests; real Windows pending | `computer_control/*`, `docs/computer-control/TESTING_REPORT.md` |
| Computer control | Windows UIA backend | implemented but unverified on owner hardware | CI runs 3 real Notepad tests on windows-latest |
| Computer control | Playwright browser on installed Edge/Chrome | implemented but unverified on owner hardware | `computer_control/browser/playwright_backend.py` |
| Computer control | Visual perception, workflows, `cc_file` | implemented but unverified on owner hardware | Project 4/5/7 reports |
| Computer control | Owner activation, settings and diagnostics surface | **planned only** | §4 B2 |
| Legacy control | `computer_control` (pyautogui), `ui_automate`, `ui_interaction`, `open_app`, `files`, `file_controller`, `browser_control`, `see_screen`, `screen_process` | working (older paths), overlapping | §4 B3 |
| Memory | Local SQLite store (`memory/long_term.db`, WAL, migration from JSON with backup) | working (tests) | `memory/memory_store.py` |
| Memory | Memory used in prompts and `recall_memory` | **off by default** (owner setting) | `memory/config_manager.py:404`, `live_tools.py:326` |
| Memory | Supabase personal profile facts (10 keys, consent, evidence quotes) | implemented, deployed function; DB unverified | `core/personal_cloud_memory.py`, edge function v3 |
| Memory | pgvector / cloud semantic memory | planned only (`docs/sql/memory_pgvector.sql` not applied by code) | |
| Automation | Triggers: cron, daily, interval, once, condition, quiet hours, run history, auto-disable | implemented; coupled to the Live session | `core/triggers.py`, `core/trigger_runs.py`, `live_services.py:259` |
| Automation | Task-mode triggers | **broken in default configuration** (B1) | `live_services.py:225` |
| Skills/MCP | `SKILL.md` registry, MCP stdio + HTTP client | implemented; real external servers unverified | PR #233, `core/mcp_client.py` |
| Skills/MCP | JARVIS exposes no MCP server (computer-control descriptors only) | working as designed | no `mcp.server` import on `main` |
| UI | Legacy HUD | working, default | `webui/__init__.py:20` defaults to `legacy` |
| UI | React web UI | partial: 5 of 12 pages live, 7 disabled and honestly labelled | `frontend/src/ui/Chrome.tsx:6-18` |
| UI | Task progress for autonomous tasks in the web UI | planned only (no `task.*` events) | `webui/jobs_feed.py:3`, `WEB_UI_PARITY.md §5` |
| Devices | Hub + laptop agent + web client | implemented; **launch scripts broken on `main`** | fixed on `claude/zealous-volta-haz97s` |
| Devices | Worker node (offload target for desktop mode) | implemented on an unmerged branch | `claude/magical-maxwell-4k08ak` |
| Devices | Phone dashboard | implemented; loopback by default, LAN only with TLS | `dashboard/server.py:47-51` |

---

## 4. Confirmed findings

### B1 — Autonomous tasks require Supabase, contrary to the docs (P0, critical, confidence high)

* **Where:** `jarvis/agent/integration.py:73` and `jarvis/agent/runner.py:91` default to `CloudTaskStore()`. `jarvis/agent/cloud_store.py:1-6` says "No task snapshot… is written to the local filesystem… durable saves fail closed". `jarvis/core/personal_cloud_memory.py:262` raises `RuntimeError("Supabase personal memory configuration is incomplete")` when `SUPABASE_URL` and the other settings are missing.
* **Path:** voice "do X as a task" → `autonomous_task(action=start)` → `AgentService.start` → `store.save` → raise → the model is told "The agent could not complete that request: Supabase personal memory configuration is incomplete". `status` and `list` fail the same way. Scheduled triggers with `mode="task"` (`core/runtime/live_services.py:225`) and `self_check` (`actions/self_check.py:7`, which only prints "Autonomous task state unavailable.") inherit the failure.
* **Reproduction:** §15 probe `at_probe.py`, with a simulated owner session and no Supabase environment, gives the message above for start, status and list.
* **Why it matters:** the flagship "autonomous" feature is unusable for any install that hasn't configured the *optional* cloud memory. If Supabase is configured, it still stops working whenever the network or Supabase is unavailable.
* **Why tests miss it:** `test_agent_core/integration/runner/voice/workflows.py` pass a local `TaskStore`. No test uses the default constructor without Supabase.
* **Contradictions:** README "Optional Supabase Personal Profile Memory… defaults off"; `docs/AUTONOMOUS_AGENT.md:35` says "Persist and resume | `agent/store.py` | Atomic JSON snapshot + fsynced JSONL journal".
* **Fix (owner decision, Q1):** choose the store in one place (`agent/integration.py`). Use the existing local `agent.store.TaskStore` (redacted, fsynced, atomic) by default. Use `CloudTaskStore` only when Supabase is configured, signed in and consented, optionally mirroring to local. Never claim a cloud save that didn't happen. Report the active store and the reason in `autonomous_task status` and `self_check`.
* **Verify:** a new test builds `AgentService()` with no Supabase environment and starts, lists and resumes a task after a simulated restart. The existing cloud tests stay green. Owner: say "start a task to list my Downloads folder" with Supabase unset and see it run.

### B2 — Computer Control has no owner activation, status or diagnostics surface (P0, high, confidence high)

* **Where:** `jarvis/computer_control/flags.py:33-38` (environment variable or in-process override only). `jarvis/actions/computer_control_engine.py` registers the tools with `available()` false while disabled. Repo-wide grep: no UI, settings or voice code calls `flags.set_overrides` or reads a persisted setting. `main.py:1320-1342` binds the approval prompt only when the flag is already on at start-up.
* **Runtime evidence (§15 `count_tools.py`):** with the flag off, 76 tools are offered and **no** `cc_*` tool, including `cc_engine_status` and `cc_emergency_stop`. With `JARVIS_COMPUTER_CONTROL=1`, 87 tools, including the 11 `cc_*` tools.
* **Further defects (CONFIRMED, runtime, §15 `cc_probe.py`):**
  * `cc_engine_status` returns only `enabled`, `dry_run` and stop state. It reports no platform support (`cc_app` on Linux fails with "Windows native control only works on Windows"), Playwright or browser channel, Tesseract, vision key presence, or approval-prompt binding.
  * With `JARVIS_COMPUTER_CONTROL_DRY_RUN=1`, `cc_engine_status` itself returns "Dry run: would perform engine.status". A read-only status check shouldn't be suppressed by dry-run.
  * Without owner access, `cc_engine_status` is denied ("Owner verification is required"). That's arguably right for a privileged engine, but the denial doesn't say whether the engine is on.
* **Why it matters:** eight merged projects never reach the owner unless they edit the launch environment. When they're off, JARVIS can't explain why.
* **Fix:** §12 P0-2.
* **Verify:** with the engine off, "is computer control available?" gives a truthful one-line answer naming the reason. With it on, `cc_engine_status` lists per-backend readiness. Dry-run no longer suppresses status.

### B3 — Overlapping tools and prompt guidance compete with the new engine (P0, medium-high; overlap confirmed, behavioural effect is a hypothesis)

* **Measured (§15 `count_tools.py`):** 87 declarations, 83,692 bytes of JSON (with the `device` parameter) sent at every Live connect, plus one line per tool in the system prompt (`main.py:291`, `_describe_tools`).
* **Overlap groups when Computer Control is on:**

  | Job | Tools offered to the model |
  |---|---|
  | Open an app | `open_app`, `cc_app`, `desktop_automation(launch_app)` |
  | Files | `files` (pc_tools), `file_controller`, `cc_file` |
  | Look at the screen | `screen_process`, `see_screen`, `cc_screen` |
  | Click / type | `computer_control` (pyautogui), `cc_control`, `cc_pointer`, `ui_interaction`, `computer_settings(type_text)` |
  | Browser | `browser_control`, `cc_browser` |
  | Multi-step | `autonomous_task`, `ui_automate`, `cc_task` |

* **Wording that steers the model:** `actions/open_app.py:285` "Use this whenever the user asks to open… Always call this tool"; `main.py:466` `screen_process` "MUST be called when user asks what is on screen"; `core/prompt.txt:152` "Prefer a direct tool over the planning agent whenever one can do the job."
* **Risk tiers differ for the same act (§15 `tiers.py`):** `computer_control` click → DANGEROUS (a confirmation banner on every click). `file_controller` and `files` delete → DANGEROUS, while `cc_file` delete passes the outer guard as SENSITIVE and then goes through the engine's own per-action policy and approval. The two paths behave differently for the same request.
* **Hypothesis to measure:** with Computer Control on, Gemini picks legacy tools for most desktop requests, so the new verified engine rarely runs. Measure with a fixed set of utterances against the real Live model, counting which tool is called (owner key needed).
* **Fix:** §12 P0-3. `JarvisLive._keep_declaration` (`main.py:1519`) already exists as the hook to hide superseded tools.

### B4 — Scheduler and proactive services stop while Gemini Live is disconnected (P1, medium, confidence high from code)

* **Where:** `main.py:3060-3064` creates `_run_trigger_scheduler`, `_run_proactive_mode` and the monitors inside the per-session `TaskGroup`. `live_services.py:259-293` sends announcements through `self.session.send_client_content`.
* **Effect:** with no network, a Live outage or a key problem, no trigger fires, including `mode="task"` triggers that never need to speak. Missed runs depend on the catch-up policy in `core/triggers.py` (not exercised here).
* **Fix:** move the scheduler loop to an app-lifetime service. Only *spoken* delivery waits for a session; task-mode runs and run history proceed. Part of P1 automation, after P0-1 makes task mode work.
* **Verify:** a test with no session object fires a task-mode trigger and records the run.

### B5 — Surfaces that report untrue state (P0 hygiene, low risk, confidence high)

| Surface | What it says | Truth |
|---|---|---|
| `docs/ROADMAP.md` | Automation "A1 in progress"; skills/MCP, browser snapshot "in review"; tasks 4–8 "not started" | Merged in PRs #230–#238 (2026-11-05) |
| `jarvis/diagnose.py:29-30` | "Edge TTS (default speech engine)", miniaudio "speech playback decoder" | No runtime code imports `edge_tts`, `miniaudio` or `core/tts.py`; Gemini Live is the only voice |
| `requirements.txt` | `edge-tts` "default cloud TTS engine", `miniaudio` | Installed on every laptop, unused |
| `scripts/start_hub.*`, `start_agent.*` | Launch the multi-device mode | Broken since the package restructure (#227); fixed on `claude/zealous-volta-haz97s` (not merged) |
| Hub and agent hints (`hub/__main__.py:38`, `laptop_agent/runner.py:19`, `client.py:184`) | "python -m laptop_agent pair …" | Must be `python -m jarvis.laptop_agent …` |
| `self_check` | "Autonomous task state unavailable." | Hides the actual reason (B1) |
| `docs/AUTONOMOUS_AGENT.md:35` | Local JSON persistence | Cloud-only (B1) |
| Master directive §2.3 | "SQLite-backed memory store (`memory/long_term.db`)" | Correct. `MEMORY_PATH` still names `long_term.json`, because the `.db` path is derived from it (`memory_store.py:22`) |

### B6 — Autonomous tasks are invisible in the web UI (P0 for UI, medium, confidence high)

* `webui/jobs_feed.py:3` says the source of truth is `JobManager` only, and `webui/contract.py` has no `task.*` events. `cc_task` runs as a JobManager job and is shown; `autonomous_task` (TaskRunner) is not. There are three job systems (TaskRunner, JobManager, computer-control HostAgent), with no shared task ID, status vocabulary or history.
* **Fix:** an adapter first, not a rewrite (§12 P0-4).

---

## 5. Design limitations and owner-decided defaults (not bugs)

1. **Memory provider access is off by default** (`config_manager.py:404`). Memories are saved locally but not given to the model or returned by `recall_memory` until the owner enables it in the HUD Memory panel. This is a valid privacy default, but it makes JARVIS seem to forget. The owner should know about it and make a deliberate choice (Q4).
2. **Voice failover is Gemini-to-Gemini only.** It switches among three Live models (`main.py:185-193`, 300 s cooldown). Non-Gemini fallback is text-only and honestly says it has no tools (`provider_fallback.py:17-23`). There is no realtime alternative provider.
3. **Computer Control is Windows-only** (`UnavailableBackend` elsewhere). It fails honestly, as shown in the probe.
4. **The web UI is opt-in.** It's at parity for state, controls and settings, with 7 pages intentionally disabled. The open gates are an owner GPU run on Windows and an NVDA pass (`WEB_UI_PARITY.md §6`).
5. **The benchmark is synthetic** (13 fake-backend scenarios, strict `verified_success_rate = 0.429`). It is not an OSWorld or WindowsAgentArena score.
6. **Hub mode moves the voice session off the laptop.** It's a separate mode, not an offload target for desktop mode (see the Phase 0 audit on `magical-maxwell`; the worker node there is the proposed offload path).

---

## 6. Keep / upgrade / integrate / rebuild / remove

| Module | Decision | Reason |
|---|---|---|
| `core/security.py` `guard()`, `core/dispatcher.py`, `security/*` | **KEEP** | Applied on every tool branch; layered and tested. Don't touch except for the specific additions below |
| `computer_control/*` | **KEEP + INTEGRATE** | Solid engine; the gap is activation, diagnostics and routing (B2, B3) |
| `agent/*` TaskRunner | **KEEP + FIX** store selection (B1); later share the task lifecycle with JobManager | Planner, runner and budgets are good; persistence default is wrong |
| `agent/store.py` (local) | **KEEP and reuse as default** | Already redacted, atomic and fsynced; unused today |
| `agent/cloud_store.py` | **KEEP as opt-in** | Correct fail-closed behaviour once it isn't the only option |
| `core/jobs.JobManager` | **KEEP** as the UI-facing job source; extend with an adapter for TaskRunner tasks | Used by `cc_task`, long-running tools and the web UI |
| Legacy desktop tools (`computer_control`, `ui_interaction`, `ui_automate`, `open_app`, `files`, `file_controller`, `browser_control`, `see_screen`) | **INTEGRATE → later REMOVE individually** | Hide when Computer Control is on and the platform is supported. Remove only after measured parity on the owner PC |
| `core/triggers.py` + `live_services` scheduler | **REFACTOR** (move the loop out of the Live session) | B4 |
| `core/tts.py`, `voice/speech_engine.py` | **Decide in the VoiceGateway design**: reuse as TTS adapters or remove with their requirements | Dead code today (B5) |
| `memory/*` local store | **KEEP** | Working, migrated, backed up |
| Cloud memory (pgvector, `MemoryStore` contract) | **DESIGN first** (P1) | Live DB unverified; `memory_pgvector.sql` not applied |
| Legacy HUD `ui/__init__.py` (6.7k lines) | **KEEP** (no rewrite) | Default and fallback; add small hooks only |
| React web UI | **UPGRADE** incrementally | Honest; needs task events and a Computer Control status window |
| Hub / laptop agent | **KEEP**; merge the launcher fix | Works when launched correctly |
| Worker node (`magical-maxwell`) | **HOLD** until P0 lands, then review as its own PR | 4.2k lines; independent of the P0 issues |

---

## 7. Security, privacy and permissions (state observed)

* **Execution boundary:** every branch of `live_tools._execute_tool_impl` (inline tools, actions, plugins) goes through `security.guard()`. Order: guest identity → Privacy Lock → HUD-media provenance → untrusted-content provenance for SENSITIVE/DANGEROUS → adaptive step-up → `ActionDispatcher` tier → Full Access shortcut (audited) → rate limit → DANGEROUS confirmation → audit-before-run, which fails closed if the ledger is unwritable.
* **Computer Control** adds its own policy, approval, estop and redaction inside the engine, and denies without owner access (verified).
* **No external MCP server:** no `mcp.server` import on `main`; `computer_control/integrations/mcp_adapter.py` is descriptor-only.
* **Network exposure:** the dashboard binds `127.0.0.1` and refuses LAN without TLS (`dashboard/server.py:47-51`); the Twilio app binds loopback; the hub refuses public addresses (`hub/netbind.py`).
* **Supabase edge function (read from the deployed v3):** `verify_jwt` on; service-role key used only server-side; per-request nonce + timestamp (±300 s) replay check; daily quotas; every row scoped to the authenticated `user_id`; consent re-checked server-side for profile facts. `Access-Control-Allow-Origin: *` is acceptable with bearer auth, but could be narrowed. **RLS on the tables could not be verified** (DB timeouts).
* **Permissions matrix to finish in P0-2:** one table of tool → resolved tier → engine policy level → approval → owner/guest/Privacy Lock behaviour, generated from code rather than written by hand, so it can't drift.

---

## 8. Performance baseline (this container only)

| Measure | Result | Note |
|---|---|---|
| `import jarvis.main` (headless, no Qt) | 0.56–0.89 s, max RSS 80 MB, 756 modules | `google.genai.types` ≈ 0.2 s of it |
| Tool declarations per Live connect | 76 tools / ≈74 KB (CC off), 87 / ≈84 KB (CC on) | Plus one line per tool in the system prompt |
| Computer Control calls (simulated owner, Linux) | 0–13 ms per call to refusal or result | No real backend here |
| Owner laptop: startup, idle CPU, RAM, voice latency, UI frame time | **not measured** | Needs the owner run in §14 |

---

## 9. Test coverage matrix

| Layer | State | Evidence (this audit) |
|---|---|---|
| Python unit/integration | `pytest jarvis/tests` excluding 4 PyQt6-at-import modules: **1670 passed, 40 skipped, 1 failed** (123 s) | The failure is `test_ui_core::test_qt_palette_reads_the_tokens` (`ModuleNotFoundError: PyQt6`, environmental). Skips: Qt/libGL missing (28), needs Windows (5), slow (1), cv2 (1), other (1) |
| Lint | `ruff check jarvis`: all checks passed | |
| Frontend | `tsc --noEmit` ok; `vitest` 76/76 | |
| Windows CI | `windows-ui-smoke` job (subset), 3 real Notepad tests | Not run here |
| Default-configuration integration | **Missing** | B1 shows the agent path is never tested with its default store |
| Real Gemini Live tool selection | **Missing** | Needed for B3 |
| Real browser / audio / multi-monitor / GPU / NVDA | Owner-run only | `docs/computer-control/TESTING_REPORT.md` pending list |
| Supabase live (tables/RLS) | **Unverified** | DB queries timed out |

---

## 10. Recommended external projects (unchanged from earlier audits)

The Phase 0 audit and the Computer Control docs already evaluated UFO², Playwright, OpenAdapt, OSWorld, WindowsAgentArena and MCP. No new dependency is needed for any P0 item. For P1:

* **OSWorld / WindowsAgentArena:** adopt their *task-definition and verifier* format for owner-run Windows scenarios. Reject running their VMs or harness on the owner PC.
* **NextChat:** `web/` already hosts a NextChat-based app alongside the React HUD. Decide a single role for each before adding UI (Q6).

---

## 11. What not to do (from this evidence)

* Don't flip `JARVIS_COMPUTER_CONTROL` on by default. Make the owner's choice explicit and persistent (P0-2).
* Don't delete the legacy tools before measured parity on the owner PC. Hide them first, behind a reversible setting.
* Don't replace TaskRunner or JobManager. Add a thin shared task-status adapter.
* Don't add a VoiceGateway before measuring current first-audio and end-of-turn latency on the owner laptop.

---

## 12. P0 remediation plan (one PR each, in this order)

### P0-1 Agent persistence works without Supabase (fixes B1) — S/M

* **Change:** `jarvis/agent/integration.py` (store selection), `jarvis/agent/runner.py:91` (same default), `jarvis/agent/cloud_store.py` (expose `configured()` / reason), `jarvis/actions/autonomous_task.py` (status shows store and reason), `jarvis/actions/self_check.py` (report the reason), `docs/AUTONOMOUS_AGENT.md`, README.
* **Don't change:** `core/personal_cloud_memory.py` request and signing code, edge functions, migrations.
* **Design:** `select_task_store()` returns the local `TaskStore` unless Supabase is configured *and* the owner chose cloud task storage (setting, Q1). Optional mirror mode later. No silent fallback from cloud to local mid-task: if cloud was chosen and fails, the task pauses with a visible reason.
* **Tests:** a default constructor without Supabase starts, lists and resumes after restart; cloud chosen + outage → paused with reason, no local write; a trigger task-mode run succeeds locally; existing cloud tests unchanged.
* **Acceptance:** `at_probe.py` (§15) shows a started task; full suite and ruff green; owner voice test on Windows.
* **Rollback:** revert the PR. Local task files live under the existing `JARVIS_AGENT_DIR` layout.

### P0-2 Computer Control activation, status and diagnostics (fixes B2) — M

* **Change:**
  * `jarvis/computer_control/flags.py`: read a persisted owner setting in addition to the environment variable; the variable still wins; default stays OFF.
  * New `jarvis/computer_control/readiness.py`: platform, pywinauto import, Playwright + channel, Tesseract, vision key *presence* (never values), approval prompt bound, estop state. Each check gets a reason code.
  * `jarvis/computer_control/tools.py`: `engine.status` is always available (owner-gated, read-only), returns readiness, and is not affected by dry-run.
  * `jarvis/actions/computer_control_engine.py`: keep `cc_engine_status` visible while disabled.
  * `jarvis/actions/jarvis_settings.py` or `security_settings.py`: owner-only "enable / disable computer control (and dry-run)" through `guard()` as DANGEROUS, i.e. with confirmation.
  * `jarvis/main.py`: after a change, rebind the approval prompt and reconnect Live so the tool list is re-sent (declarations are fixed per connection).
  * Legacy HUD settings row and a read-only web UI status window (`webui/contract.py`, `frontend/src/ui/`).
* **Tests:** readiness on Linux reports "unsupported platform"; with CC disabled, the status tool exists and says "off (owner setting)"; dry-run returns real status; the toggle requires owner + confirmation; guest/Privacy Lock denied; the environment variable overrides the setting.
* **Acceptance:** voice "why can't you control my computer?" gives a truthful reason. Owner on Windows: enable → `cc_engine_status` lists backends ready → `cc_task` on Notepad in a temp folder.
* **Rollback:** the setting defaults to off; deleting it restores today's behaviour.

### P0-3 One tool per job when Computer Control is on (addresses B3) — S/M + measurement

* **Step 1, measure (no code change):** a 30-utterance tool-selection eval run against the real Live model with CC off and on, recording the first tool chosen (owner key; script kept under `jarvis/eval/`, results without transcripts).
* **Step 2, change:** `JarvisLive._keep_declaration` (`main.py:1519`) hides the superseded tools (`computer_control`, `ui_interaction`, `ui_automate`, `see_screen`, `files`, `browser_control`; `open_app` stays for websites and URIs) when CC is enabled *and* readiness says the Windows backend is usable. Behind a reversible setting. Soften "Always/MUST" wording in descriptions that conflict; update `prompt.txt:152` to route multi-step desktop work to `cc_task`.
* **Tests:** declaration-set snapshot tests for CC off, on+ready and on+unsupported; no tool name lost when CC is off.
* **Acceptance:** after the change, the eval shows `cc_*` chosen for desktop requests with CC on; no regression with CC off; declaration size reported before and after.

### P0-4 One visible task list (fixes B6) — M

* **Change:** a small adapter publishes TaskRunner task state into `JobManager` (or the same `jobs.updated` feed) with `source="agent"` and a shared status vocabulary (queued, running, waiting_approval, paused, succeeded, failed, cancelled). Cancel from the UI maps to `AgentService.cancel`. `webui/jobs_feed.py`, `webui/contract.py`, `frontend/src/bridge/contract.ts`, `frontend/src/ui/Jobs.tsx`, and the legacy HUD job list.
* **Not in this PR:** merging the engines or a new orchestration package.
* **Tests:** contract validation; task start → row appears; cancel propagates; estop cancels all three sources.

### P0-5 Truth pass on docs and diagnostics (fixes B5) — S

* Merge the launcher fix (`claude/zealous-volta-haz97s`); update the `jarvis.*` hint strings; rewrite `docs/ROADMAP.md` from merged PRs; mark Edge TTS as unused in `diagnose.py` (or remove `edge-tts`/`miniaudio` from `requirements.txt` if the owner agrees, Q5); `docs/AUTONOMOUS_AGENT.md` store section.
* **Tests:** the launcher tests (already on the branch); a test that every `diagnose.py` "default" component is imported by runtime code.

### P0-6 Owner Windows validation run (no code; produces the "before" numbers) — owner-run

A checklist in `docs/WINDOWS_SMOKE_TEST_CHECKLIST.md` (extend it, don't duplicate):

1. Start JARVIS normally; 2 minutes idle; `python -m jarvis.tools.profile_ram --pid <pid> --duration 120 --label idle`; note CPU % from Task Manager.
2. Three short questions; time end-of-speech → first audio.
3. `python -m pytest -q` on Windows.
4. With `JARVIS_COMPUTER_CONTROL=1` and a temp folder only: Notepad open/type/save via `cc_task`; Edge open/search via `cc_browser`; say "Jarvis, stop" mid-task; press the HUD interrupt mid-task.
5. "Start a task to list my Downloads folder" (shows B1 before and after P0-1).

### After P0 (P1/P2, unchanged in intent from the directive, re-ordered by evidence)

| Order | Work | Depends on |
|---|---|---|
| P1-1 | Scheduler as an app-lifetime service (B4), budgets per trigger and per day | P0-1 |
| P1-2 | Shared task lifecycle contract (IDs, checkpoints, events) across TaskRunner / HostAgent / JobManager | P0-4 |
| P1-3 | Memory: inventory readers/writers, `MemoryStore` contract, verify the live Supabase schema/RLS, then a pgvector design | Q3, DB access |
| P1-4 | VoiceGateway design from measured latency; decide on `core/tts.py` | P0-6 numbers |
| P1-5 | Worker node review and merge (`magical-maxwell`) | P0 done |
| P2 | Research pipeline, proactive suggestions, web UI default flip, hologram tiers | Parity gates |

---

## 13. Questions that block implementation

1. ~~**Agent task storage (P0-1):** local by default with optional cloud, or cloud-only?~~ **Answered 2026-11-10: local by default, cloud optional.** P0-1 is approved and in progress.
2. **Is Supabase configured on the laptop today** (are `SUPABASE_URL` and the sign-in set up and working)? This decides whether B1 hits the owner today or only offline.
3. **Supabase target:** is `JARVIS-AI-PRO` (the ref in `docs/SUPABASE_HYBRID_PROVIDER_SETUP.md`) the intended project? Its DB was unreachable from this session; can the owner confirm tables and RLS from the dashboard, or allow a read-only retry later?
4. **Memory provider access** is off by default. Keep it off and make the setting more visible, or ask during first-run setup?
5. **Unused voice dependencies:** remove `edge-tts`/`miniaudio` now, or keep them for a future TTS adapter?
6. **UI roles:** the React HUD (`frontend/`) and the NextChat app (`web/`): which one is the phone/chat surface going forward?
7. **Worker node branch:** hold until P0 is merged (recommended), or review first?

---

## 14. Owner validation still pending from PRs #277–#285

Real owner-PC app discovery; real Edge/Chrome through Playwright; real downloads; multi-monitor/high-DPI; the interactive approval dialog; microphone stop word during a task; HUD interrupt; hosted vision with real credentials; Tesseract on the owner PC; live RSS/CPU before and after (`bench baseline --pid`); Supabase workflow-metadata sync. Source: `docs/computer-control/TESTING_REPORT.md`.

---

## 15. Reproduction probes used in this audit

Run from the repository root with an isolated data folder (`HOME=<tmp> JARVIS_DATA_DIR=<tmp>`). They simulate owner access in-process only and change no code.

| Probe | What it does | Result |
|---|---|---|
| `count_tools.py` | `discover_actions` + `discover_plugins` + inline tools, exactly as `JarvisLive.__init__`, CC off and on | 76 / 87 tools; ≈74 KB / ≈84 KB; `cc_*` list; overlap table in B3 |
| `cc_probe.py` | `cc_engine_status`, `cc_app`, `cc_task`, `cc_browser` through the action registry; no owner / owner / dry-run | Denied without owner; dry-run suppresses status; on Linux honest "Windows only" failure |
| `agent_probe2.py`, `at_probe.py` | `AgentService.start` and `autonomous_task` start/status/list without Supabase | "Supabase personal memory configuration is incomplete" for all three |
| `tiers.py` | `security.tier_for` on overlapping tools | Table in B3 |
| Test runs | `pytest jarvis/tests` (4 PyQt6 modules ignored), `ruff check jarvis`, `npx tsc --noEmit`, `npx vitest run` | §9 |
