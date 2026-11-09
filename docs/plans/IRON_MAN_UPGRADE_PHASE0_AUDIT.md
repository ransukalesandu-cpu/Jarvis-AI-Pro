# Iron Man upgrade — Phase 0 audit (docs only, no code changes)

Scope: the four owner-selected areas of `JARVIS_IRON_MAN_UPGRADE_FOR_CLAUDE.md` —
**(2) Proactive Intelligence, (4) Holographic 3D, (5) Engineering Lab, (6) Multi-Device**.
Everything below was read from the live repository, not from the directive's snapshot.

## 0. Repository snapshot

| Item | State (2026-11-09) |
|---|---|
| `main` | `28c2889` — merge of PR #285 (computer-control progress table). Computer Control Projects 0–8 merged #277–#285 |
| Open pull requests | **None** |
| Closed without merge, relevant | #253 / #254 "Hologram v2 / Neural Entity Engine 2.0 (WebGL)" — closed 2026-11-05, superseded by the next-gen UI series #255–#260 (merged) |
| Branches | ~200 remote branches. Every one I could match to a PR is merged or closed; none carries pending work for these four features. I did not diff every branch head individually |
| Python | `requires-python >=3.11`; CI uses 3.12; this audit container has 3.13.18 |
| Frontend | React 19, R3F 9.8, three 0.187, TypeScript 7, Vite 8, Vitest 5 |

## 1. Findings that change the directive's assumptions

1. **A multi-device runtime already exists and the directive does not mention it.**
   `jarvis/hub/` + `jarvis/laptop_agent/` (README "Multi-device setup") provide:
   one-time pairing codes → device tokens stored only as SHA-256 hashes, per-device revocation
   (`hub/pairing.py`); a device registry with heartbeats and a 10 s offline window
   (`hub/devices.py`); one WebSocket per device with replace/timeout close codes
   (`hub/connections.py`); binding that refuses public addresses and allows only loopback, LAN and
   Tailscale ranges (`hub/netbind.py`); TLS for non-loopback; tool routing by a `device` argument
   with cancellation propagation (`hub/remote_tools.py`); and `requirements-hub.txt` for ARM hosts.
   README already documents "Moving the hub off the laptop" to an always-on Linux/Pi host.
2. **But the hub is a separate mode, not an offload target for the desktop app.** In hub mode the
   Gemini Live voice session itself moves to the hub (laptop mic audio streams over the network),
   the laptop shows the vanilla-JS client (`jarvis/client/`) instead of the React HUD, and
   `autonomous_task.py` is a *device-side* tool (`hub/live.py:HUB_ACTION_FILES` excludes it), so
   autonomous tasks run inside the **laptop agent** — the opposite of the owner's goal. The agent
   has no confirmation UI, so consequential steps are denied there (fail-closed, but unusable).
   Desktop mode (`python main.py`) — where all recent work (computer control, web UI) lives —
   has no offload path at all.
3. **There are two phone pathways**: the desktop-mode dashboard (`dashboard/server.py`, FastAPI,
   loopback by default, reached through Tailscale Serve) and the hub web client. Neither shows approval requests.
4. **There are three job/task systems**, which a new one must not duplicate:
   `agent.TaskRunner` (plan → act → verify, one active task, queue of 8, Supabase-only store that
   fails closed), `core/jobs.JobManager` (asyncio jobs on the live loop; the only source the web
   UI "Background Jobs" window shows), and the computer-control orchestrator (runs as JobManager
   jobs). Triggers with `mode="task"` start TaskRunner tasks.
5. **The hand-tracking pipeline lives in the Holo deck, not the React UI.**
   `assets/holo/holo.html` vendors its own `three.module.js`, `GLTFLoader.js`, MediaPipe
   `vision_bundle.mjs` and `hand_landmarker.task`, and owns the camera while open.
6. **The laptop has 4 GB RAM** (`docs/CLOUD_FIRST_RAM_AUDIT.md`, `jarvis/tools/profile_ram.py`),
   which makes offload the main benefit — and makes measurement mandatory.
7. **Reusable building blocks already exist**: `core/sandbox.py` (disposable dir, scrubbed env,
   wall-clock + RSS watchdog, security-ledger entry), `security/host_device_identity.py`
   (Ed25519 device key in the OS keystore), `core/user_data.user_data_dir()`, the security ledger,
   and the `mcp` SDK (already a runtime dependency).

## 2. Gap tables

Legend: ✅ already works · 🟡 partial · ⬜ missing · ❌ broken

### Feature 2 — Proactive Intelligence

| Requirement | Status | Evidence / gap |
|---|---|---|
| Validated planning | ✅ | `agent/planner.py`, registry-aware `REGISTRY_CALL` steps (#273–#276) |
| Bounded runner: step/attempt/retry/wall-clock budgets, pause/resume/cancel, loop detection | ✅ | `agent/runner.py`, `test_agent_runner.py` |
| Restart without duplicating work | 🟡 | A step that was `RUNNING` at a crash is reset to `PENDING` and re-executed (`agent/models.py:491`). Approval is re-requested because it happens at execution time (`executor.py:174`), so nothing sensitive resumes *silently*, but there is no idempotency key: a non-idempotent command/tool step can run twice |
| Triggers: cron/daily/interval/once/condition, quiet hours, `max_per_hour`, auto-disable after 3 failures, run history, catch-up | ✅ | `core/triggers.py`, `core/trigger_runs.py`, `core/runtime/live_services.py` |
| Trigger-loop / self-modification guard | 🟡 | A trigger-started task cannot change triggers (`actions/proactive_triggers.py:_called_by_scheduled_task`) and plans cannot call `autonomous_task` (`tool_catalog.PLANNER_EXCLUDED`). Nothing source-scoped stops a trigger task's plan from calling standing-order, settings, skills, MCP-config or hook-related tools |
| Goal/intent registry (create, review, pause, resume, complete, archive; due window, progress, blockers, linked tasks) | 🟡 | `memory/prospective_memory.py` stores intentions (event/project-state/time trigger, status). No goal lifecycle, due window, progress, blockers or task links |
| Event-driven context checks | 🟡 | `core/hooks.EVENTS` covers startup, shutdown, session start/end, trigger fired/failed, task_finished, tool_error, privacy_lock; owner rules via `core/events.py`. No device online/offline events |
| Suggestions with reason, benefit, cost, proposed action; dismissible | 🟡 | `actions/proactive.py` (silence-gated prompt to Gemini) and `actions/proactive_planner.py` (suggestion dicts with urgency/usefulness, `requires_permission`, feedback). No cost estimate, no dismiss/accept state, no UI surface |
| Resource-aware planning | ⬜ | No node or resource concept in the planner or runner |
| Per-goal budgets | ⬜ | Per-trigger `max_per_hour` exists only |
| Owner-visible audit trail | 🟡 | Task journal, trigger runs and security ledger exist; the web UI contract has no `task.*` events (NEXT_GEN_UI §5) — it shows JobManager jobs only |
| Approval tiers, emergency stop | ✅ | `core/confirm.py`, `agent/policy.py`, `computer_control/estop.py` |

### Feature 4 — Holographic 3D

| Requirement | Status | Evidence / gap |
|---|---|---|
| R3F hologram (head, heart, orb, wires) | ✅ | `frontend/src/hologram/*`; tsc, 76 Vitest tests and build pass (see §6) |
| Real state only, nothing fabricated | ✅ | Closed, validated contract (`bridge/contract.ts` ↔ `webui/contract.py`) |
| Web UI as default | 🟡 | Still opt-in (`JARVIS_UI=web`). Open gates in `WEB_UI_PARITY.md` §6: owner GPU run on Windows, NVDA pass |
| Bihansa in the web hologram | 🟡 | Persona is in the contract, but no file in `frontend/src/hologram/` reads it. The Bihansa visual exists natively (`ui/hologram/bihansa_hologram.py`). Needs a Windows check of what the web UI shows in Bihansa mode |
| Performance tiers applied to the canvas | 🟡 | Tier is in the store, but `HologramScene.tsx` uses a fixed `dpr={[1,2]}` and always-on frame loop |
| WebGL failure → usable fallback | ⬜ | No WebGL detection or error boundary in the page; `Suspense fallback={null}`. (Host-level fallback to the legacy HUD covers start-up failure only) |
| Reduced motion | ✅ | `prefers-reduced-motion` + toggle, honoured by hologram animation |
| Engineering 3D viewer (load, orbit/pan/zoom, fit, reset, select, measure, close) | ⬜ | Nothing exists. `three` is a 743 kB chunk already; the viewer must be a lazy chunk |
| Gesture input | 🟡 | MediaPipe hands work inside the Holo deck (opt-in via `holo_gestures`), not connected to the React UI |
| Task / node / engineering events in the UI | ⬜ | No `task.*`, `nodes.*` or engineering events in the contract |

### Feature 5 — Engineering Intelligence Lab

| Requirement | Status | Evidence / gap |
|---|---|---|
| Typed CAD / circuit / simulation specs | ⬜ | No `jarvis/engineering/` |
| CadQuery, ngspice, OpenModelica adapters | ⬜ | None present. Only hardware integration: `plugins/printer_control.py` (MQTT) — stays separate |
| Isolated, limited execution | 🟡 | `core/sandbox.py` has the watchdog/env-scrub/ledger pattern to reuse; no engineering workspace or quotas |
| Preview to 3D viewer | ⬜ | Depends on Feature 4 viewer |

### Feature 6 — Multi-Device Intelligence

| Requirement | Status | Evidence / gap |
|---|---|---|
| Remote MCP nodes over HTTPS + `bearer_env` | ✅ (client) | `core/mcp_client.py:validate_node_url`, `test_mcp_http_node.py`. Verified on loopback only, never over Tailscale or on Windows |
| A JARVIS worker that *serves* a node | ⬜ | Remote nodes today are arbitrary third-party MCP servers; JARVIS has no node server |
| Pairing, hashed tokens, revocation | 🟡 | Complete in the hub (`TokenStore`); MCP nodes use a static env-var token with no rotation or revocation |
| Registry + heartbeat + offline detection | 🟡 | Complete in the hub; desktop mode's `McpManager` only knows idle/ready/failed |
| Typed capability advertisement, version, resources | 🟡 | Hub agents announce tool declarations; no capability names, no resource summary. Protocol version is sent but never checked |
| Resource-aware routing | ⬜ | Hub routes only by an explicit `device` argument |
| Job lease / claim, idempotent submit, durable job ledger | ⬜ | Hub remote calls are in-memory request/response; an agent drop fails the call; nothing persisted |
| "Waiting for node", stale-result rejection, reconnect without duplicates | 🟡 | Hub speaks "X is offline" and drops unknown call IDs; no waiting state or lease epoch |
| Cancellation propagation | ✅ (hub) | `RemoteToolRegistry.cancel_all` on the stop word |
| Narrow phone permissions | 🟡 | Dashboard `/api/command` forwards free text into the full assistant; dispatcher tiers still apply, but there is no phone-scoped allowlist. No approval view on the phone |
| Low-resource laptop mode | 🟡 | UI perf tiers and lazy agent imports exist; no "no local workers while the node is healthy" policy (no node exists) |
| Private networking | ✅ | Hub netbind refuses public addresses. Dashboard binds loopback by default; LAN (`0.0.0.0`) only with TLS (`_select_dashboard_bind_host`); README recommends Tailscale Serve, never Funnel |

## 3. GitHub projects from the directive (§3), against the live code

| Project | Classification | Reason |
|---|---|---|
| langchain-ai/langgraph | **not needed** (reference only) | `TaskRunner` already has checkpoints, interrupts (pause/approval), budgets and recovery. The real gaps (idempotency, goals, placement) are small additions to it |
| mrdoob/three.js | **already present** | `three@0.187`. Viewer controls/loaders come from `three/examples/jsm` (OrbitControls, GLTFLoader, STLLoader) — no new package |
| pmndrs/react-three-fiber | **already present** | `@react-three/fiber@9.8` |
| google-ai-edge/mediapipe | **already present** (vendored JS in Holo deck) | Reuse the vendored `hand_landmarker.task`; no Python `mediapipe`, no second camera owner |
| CadQuery/cadquery | **new optional dependency — dedicated node only** | 2.8.0 (2026-06), Apache-2.0, Python ≥3.11. Pins `cadquery-ocp <8` (OCP 8 has cp311–cp314 wheels incl. linux aarch64; the 7.9.x pin must be verified on the node's actual CPU). Pulls scipy, numba, casadi, nlopt, trame/VTK — far too heavy for the 4 GB laptop |
| OpenModelica/OpenModelica | **new optional external program — dedicated node only** | Called as the `omc` executable with generated `.mos` scripts; not linked or redistributed, so its OSMC-PL/AGPL terms are not pulled into this Apache-2.0 repo. OMPython (4.1.0) not needed |
| ngspice/ngspice | **new optional external program — dedicated node only** | `ngspice -b` in batch mode from an OS package; source not vendored |
| PySpice-org/PySpice | **not needed** | Last release 1.5 in 2021; GPLv3. Generating a validated netlist and running ngspice in batch is smaller and licence-clean |
| nats-io/nats-server | **not needed** (deferred) | MCP request/response with polling covers job submit/status/cancel; revisit only with measurements |
| tailscale/tailscale | **already present** (pattern) | Used by hub and dashboard docs; nothing to vendor |

## 4. Architecture decision needed before Phase 1

**Option A — run the existing hub on the dedicated device.** Reuses the most code, but moves the
voice session off the laptop, replaces the React HUD with the browser client, and leaves the
computer-control engine, approval banner and TaskRunner on the desktop path unused. Autonomous
tasks would still run on the laptop agent unless that is reworked too. Large change to daily use.

**Option B — recommended: keep desktop mode on the laptop; add a headless JARVIS worker node.**
The laptop keeps voice, HUD, approvals and computer control. The dedicated device runs
`python -m jarvis.node`: an MCP streamable-HTTP server (the `mcp` SDK is already a dependency)
that owns a durable job ledger with leases and runs background and engineering jobs. It reuses
`hub/pairing.TokenStore` (hashed tokens, revocation) and `hub/netbind` (no public binding). The
laptop talks to it through the existing `McpManager` remote-node path (`https` + `bearer_env`), as
the earlier nodes audit (`docs/research/voice-and-nodes-audit.md`) already proposed. Hub mode
keeps working unchanged and can call the same node later.

The rest of this plan assumes **Option B**.

## 5. Implementation roadmap (one focused PR per phase)

Complexity: S < 300 LOC, M < 1k, L < 3k, XL ≥ 3k (including tests).

### Phase 1 — Multi-device foundation (L)

New — dedicated node (`jarvis/node/`):

| File | Purpose |
|---|---|
| `node/__init__.py`, `node/__main__.py` | CLI: `serve`, `pair <device>`, `revoke <device>`, `list` |
| `node/protocol.py` | Versioned, closed schemas validated on both ends (same style as `webui/contract.py`): `NodeHello`, `Capability` (closed set: `assistant.orchestrate`, `engineering.cadquery`, `engineering.ngspice`, `engineering.openmodelica`, `laptop.desktop_control`, `laptop.audio_io`, `phone.dashboard`), `Health`, `JobSpec` (idempotency key, kind, capability, payload, deadline, priority, privacy class), `JobStatus`, `JobResult`, `Lease`. Version mismatch → refused with a clear message |
| `node/server.py` | MCP streamable-HTTP tools: `node_hello`, `node_health`, `job_submit`, `job_status`, `job_cancel`, `job_result`, `job_list`. Bearer check through a `TokenStore` instance in the node's state folder; peer filter + bind rules from `hub/netbind`; TLS required off loopback |
| `node/ledger.py` | Durable ledger (JSON snapshot + fsynced journal, same pattern and redaction as `agent/store.py`): idempotency map, lease (holder, epoch, expiry), states `queued → leased → running → succeeded / failed / cancelled / expired`, retry count, deadline. Local to the node: same-LAN work never depends on Supabase |
| `node/worker.py` | Bounded pool (global and per-kind limits), runs each job in a child process with the `core/sandbox.py` watchdog (time + RSS + output caps, scrubbed env, own work dir). Phase 1 job kinds are test fixtures only (`diag.echo`, `diag.sleep`) |
| `node/resources.py` | Coarse CPU %, available RAM, free disk, optional GPU presence. No process lists, user names or paths |

New — laptop side (`jarvis/core/nodes/`):

| File | Purpose |
|---|---|
| `core/nodes/registry.py` | Nodes from `mcp_servers.json` entries marked `"role": "worker"`; heartbeat poll of `node_health` with backoff; online / degraded / offline; version check; emits `node_online` / `node_offline` hooks |
| `core/nodes/router.py` | Placement: capability → health → headroom → privacy → priority. `laptop.*` capabilities pinned to the laptop; engineering defaults to the node; local fallback only when allowed by config, resources suffice, and the owner agrees. Returns placement + reason |
| `core/nodes/jobs_client.py` | Idempotent submit, status polling, cancel propagation (JobManager cancel and the emergency stop), lease-epoch stale-result rejection, explicit `waiting_for_node`. Each remote job appears as a JobManager job, so the existing Jobs window and voice announcements work |
| `actions/node_jobs.py` | Voice tool: node status, list jobs, cancel (read / low risk). Submitting comes with engineering tools in Phase 3 |

Modified: `core/mcp_client.py` (accept `role`/`node_id` keys; transport unchanged),
`core/hooks.py` (`node_online`, `node_offline`, `node_job_finished`),
`hub/pairing.py` (a third role for node controllers, with test), `webui/contract.py` +
`frontend/src/bridge/contract.ts` (`nodes.updated`; `JobRow` gains `node` and `waiting`),
`webui/jobs_feed.py`, a read-only Nodes window in `frontend/src/ui/`, `dashboard/server.py`
(owner-authenticated read-only `GET /api/nodes`, `GET /api/jobs`), `requirements-node.txt`,
`scripts/start_node.{sh,cmd}`, `docs/architecture/MULTI_DEVICE.md`, `docs/SKILLS_AND_MCP.md`,
`CHANGELOG.md`.

Tests: protocol validation; ledger idempotency, lease expiry, restart recovery, stale epoch;
server auth (no token, wrong token, revoked token, public peer, plain http off loopback);
router (capability, headroom, laptop-pinned, node offline); a real loopback MCP-HTTP integration
test (submit → progress → result; kill node mid-job → waiting → restart → no duplicate run; cancel
propagation); secrets scan of logs, ledger and UI events.

Risks: `mcp` server API changes within the `<3` range (pin tested minor versions); certificate
provisioning and service start-up on the node (owner-run); polling latency (measure; acceptable
for jobs measured in seconds).

### Phase 2 — Proactive Intelligence (L)

| File | Change |
|---|---|
| `agent/goals.py` (new) | Goal lifecycle (active, paused, completed, archived), due window, blockers, linked task IDs, per-goal budgets. Progress derived only from linked tasks — never estimated. Stored as memory records next to prospective intentions (compatibility with the Supabase personal-memory function's validators to be checked first) |
| `agent/suggestions.py` (new) | Suggestion = reason, expected benefit, estimated cost, proposed action, expiry, state (open / dismissed / accepted). Built from hook events, goals and `ProactiveMemoryPlanner`. Never executes; *accept* goes through `AgentService.start` with the normal owner checks |
| `agent/cost.py` (new) | Estimate from plan step kinds + node placement (runtime, node, local RAM need) |
| `agent/policy.py` | Source-scoped deny list for `trigger` / `suggestion` tasks (no trigger, standing-order, security, settings, skills, MCP-config, self-update, dev-agent tools); scope frozen at creation |
| `agent/models.py`, `agent/runner.py` | Step `side_effect` / idempotency flag; a non-idempotent step found `RUNNING` after a restart becomes *blocked — needs owner review* instead of re-running |
| `core/runtime/live_services.py` | Subscribe the suggestion engine to hook events; de-duplicate by event ID; quiet hours; failure backoff |
| `actions/goals.py` (new) | Owner-only voice tool: create / review / pause / resume / complete / archive goals; list / dismiss / accept suggestions |
| `webui/` + `frontend/` | `task.*`, `goals.updated`, `suggestions.updated` events; Suggestions and Goals windows |
| `dashboard/server.py` | Phone view of pending approvals. Approving from the phone stays **off by default**; if enabled it requires an owner-verified session plus PIN re-entry (owner decision) |

Tests: event ordering, duplicate events, retry limits, quiet hours, cancellation, node loss
mid-task, approval denial, trigger task calling a denied tool, restart with a non-idempotent step.

### Phase 3 — Engineering Lab (XL)

| File | Purpose |
|---|---|
| `engineering/specs/units.py`, `cad.py`, `circuit.py`, `modelica.py` | Typed specs: bounded numbers with units, allow-listed CAD operations (box, cylinder, hole, fillet, chamfer, polyline extrude, pattern, union/cut), allow-listed SPICE elements and analyses (op, dc, ac, tran), curated Modelica templates |
| `engineering/planner.py` | Model output → JSON → validated spec, shown to the owner before running. Never code |
| `engineering/cadquery_adapter.py` | Fixed worker script reads the spec as JSON on stdin; exports STEP / STL / DXF and a glTF preview |
| `engineering/ngspice_adapter.py` | Netlist generated from templates; rejects `.include`, `.lib` paths, `.control`, `shell`, `system`; runs `ngspice -b`; parses output |
| `engineering/openmodelica_adapter.py` | Version detection (`omc --version`); fixed `.mos` template; CSV results |
| `engineering/jobs.py` | Registers `engineering.*` job kinds with the node worker; workspace under `user_data_dir()/engineering/<job>` with quotas and owner-visible cleanup |
| `engineering/results.py` | Values with units, series for plotting in the UI, warnings, assumptions, a fixed "simulation estimate — not a safety certification" label |
| `engineering/preview/` | Artifact transfer node → laptop in bounded chunks with size and type checks |
| `actions/engineering.py` | Voice tool: draft spec, show spec, run, status, export |
| `requirements-engineering.txt` | Node only. ngspice and OpenModelica documented as OS packages |

Tests: spec validation (units, bounds, path traversal, netlist injection), small fixtures with
tolerances (box 10×20×30 mm → 6000 mm³; RC low-pass at t = τ → 63.2 %; voltage divider;
mass-spring-damper period), timeout and memory-kill do not block the caller. Engine tests skip
cleanly when the engine is absent; normal start-up never imports engineering packages.

Risks: CadQuery's dependency footprint (~1 GB with VTK/scipy/numba); OCP 7.9.x wheels on the
node's CPU (ARM especially); OpenModelica availability on ARM; artifact transfer through the 16 KB
bridge message cap (chunked request or a loopback, token-protected asset host like
`core/holo_gestures.py`).

### Phase 4 — Holographic 3D (M–L)

| File | Change |
|---|---|
| `frontend/src/hologram/SafeCanvas.tsx` (new) | WebGL detection + error boundary + non-3D fallback panel |
| `frontend/src/hologram/HologramScene.tsx`, `Stage.tsx` | Apply perf tier (dpr cap, frame-rate cap / `frameloop`), pause when hidden; read persona if Bihansa belongs in the web UI (owner decision) |
| `frontend/src/engineering/Viewer.tsx`, `controls.ts`, `loaders.ts`, `dispose.ts` (new) | `React.lazy` chunk, own canvas mounted only while open, `frameloop="demand"`; orbit/pan/zoom, fit, reset, visibility, selection, bounding-box dimensions from the spec, Home; full disposal on close |
| `webui/engineering_feed.py` (new), contract files | `engineering.preview` event and a chunked artifact request |
| Phase 4b | Opt-in gestures reusing the vendored hand landmarker, mutually exclusive with the Holo deck camera, visible indicator and stop control, view operations only (never consequential actions) |

Tests: Vitest for loaders, disposal, controls and fallback; contract tests; build size budget.
Owner-run: Windows GPU smoke test before any default changes.

## 6. Dependencies (keep the laptop light)

| Where | Added |
|---|---|
| Laptop `requirements.txt` | **Nothing** in any phase (`mcp`, `psutil`, `cryptography`, `keyring` are already there) |
| Frontend `package.json` | **Nothing** (controls and loaders ship inside `three`) |
| Dedicated node `requirements-node.txt` | Subset of existing packages (mcp, psutil, cryptography, uvicorn) |
| Dedicated node `requirements-engineering.txt` | `cadquery` (pinned range, verified on the node's CPU) |
| Dedicated node OS packages | `ngspice`, OpenModelica (`omc`) |

## 7. Test and benchmark baseline

Measured in this audit container (Linux, Python 3.13.18, Node 22.23.4):

| Check | Result |
|---|---|
| `npm ci` | ok |
| `npx tsc --noEmit` | ok, 0 errors |
| `npx vitest run` | 76 passed / 76 |
| `npm run build` | ok; `jarvis/webui/dist` reproduced byte-identical (no git diff). Chunks: three 742.9 kB, index 466.8 kB, react 275.1 kB |
| `ruff check jarvis` | All checks passed |
| `pytest` targeted (hub ×5, agent runner/core/integration/events/android, MCP HTTP node, skills/MCP, triggers, cron, hooks, standing orders, webui contract/jobs/command gate, dashboard USB, computer-control phase 0) | 383 passed, 5 skipped (PyQt6 absent / Windows-only). The 2 hub browser tests that first failed needed only the Python `playwright` package; with it installed they pass in the full run |
| `pytest` full suite, `--ignore` on 4 modules that import PyQt6 at collection time (`test_glass_window`, `test_hologram_stage`, `test_security_v2_ui`, `test_ui_menus`) | **1670 passed, 40 skipped, 1 failed, 207 subtests passed** (114 s). The single failure, `test_ui_core.py::TokenTests::test_qt_palette_reads_the_tokens`, is `ModuleNotFoundError: PyQt6` — environmental, not a code defect |

Environment limits: requirements installed without PyQt6, PyQt6-WebEngine and opencv-python
(slow network here), so Qt/WebEngine UI tests were not run — CI installs them and runs them.
Real audio, Windows behaviour and GPU rendering cannot be exercised here. No laptop CPU/RAM
numbers are claimed from this sandbox.

**Owner-run baseline on the Windows laptop (before Phase 1):**

1. Idle: start JARVIS, wait 2 minutes, then
   `python -m jarvis.tools.profile_ram --pid <pid> --duration 120 --label idle`.
2. One ordinary task (e.g. "search the web for …"):
   `python -m jarvis.tools.profile_ram --pid <pid> --duration 60 --label task --append`.
3. Note CPU % from Task Manager for both; note `JARVIS_UI` (web or legacy).
4. Voice latency: time from end of speech to first audio for three short questions.
5. `python -m pytest -q` on Windows and the Windows-only computer-control tests.

These numbers are the "before" for the Phase 1 benchmark claim.

## 8. Owner decisions needed

1. **Option A or B** (§4). Recommendation: B.
2. **Dedicated device hardware and OS** (CPU architecture, RAM, Linux distribution or Windows).
   This decides whether CadQuery/OCP and OpenModelica wheels/packages exist for it.
3. **Phone approvals**: view-only (recommended for Phase 2) or approve with PIN re-entry.
4. **Bihansa in the web hologram**: should the R3F scene render Bihansa, or does Bihansa stay in
   the native HUD?
5. **Laptop fallback when the node is offline**: never, or ask each time (recommended: ask, and
   only for jobs that fit the laptop budget; engineering engines never run on the laptop).
