# Production architecture + self-healing upgrade: P0 audit and plan

Status: **plan only, docs only. Waiting for owner approval before any code.**
Audited at commit `ffa0dc5` (main, 2026-11-24). Source brief: "JARVIS AI Pro — Production Architecture + Self-Healing Upgrade, Master Prompt v1".

Every number below was measured for this plan unless it is marked *est.* or *from docs*.
Linux numbers come from a Python 3.12 container (CI's version) with software OpenGL. They are a
reference for before/after comparisons, **not** the owner's Windows laptop numbers (section 4.2 says how to get those).

---

## 0. What the owner needs to know first

1. **The repository is public**, not private. That makes the signing design in the brief possible
   (on Free, Pro and Team plans GitHub offers required reviewers only on public repositories), but it also means that
   anything the self-heal pipeline commits, files as an issue or prints in an Actions log is world-readable.
   The brief's `issues/journal/<fp>.md` would publish crash journals. See Q1.
2. **The engine split is feasible.** `jarvis.main` already imports with PyQt6 made unimportable (measured), a
   `--headless` mode with `HeadlessJarvisUI` already exists, and everything the engine asks of the UI goes through one
   duck-typed `ui` object with 39 members. Those 39 members become the JSON-RPC schema.
3. **Runtime state lives inside the code directory.** About 35 modules resolve `config/`, `memory/` and `logs/` relative
   to the source tree, or to the `.exe` folder when frozen. That includes `config/api_keys.json`, the memory database
   and Security V2 auth state. Immutable, swappable packs (P1.5) are impossible until that state moves to the user data
   folder. That move is a data migration, so it needs your yes (Q3).
4. **Two update/repair paths already exist outside the planned root of trust:** `jarvis/actions/self_update.py`
   (git fast-forward of `main`, runs tests, `git reset --hard` on failure) and `jarvis/actions/self_heal.py`
   (`pip install` of an allowlisted dependency after confirmation). The brief does not mention either. See Q10.
5. **Library verdict:** adopt pydantic (already installed through five other packages, it only needs declaring),
   Hypothesis, pytest-qt, PyInstaller (onedir), WinSparkle, and sentry-sdk as opt-in. Skip LangGraph, pydantic-ai,
   LiteLLM, Langfuse (for now), mem0, graphiti, Unleash, deepeval and E2B. qdrant only if a P3 benchmark shows a win.
   LiteLLM is the clearest skip: 255 MB installed, about 175–200 MB extra RAM, and it **fetches a price list from
   `raw.githubusercontent.com` on import** (measured), which breaks the privacy contract.
6. **The eval only measures memory retrieval** (40 cases). The self-heal gate "eval not more than 2% below baseline"
   would guard nothing about routing, planning or tool choice. See Q8.
7. **There is no mic → first-audio-byte instrumentation.** It has to be added before anything touches the audio path,
   or the +50 ms budget cannot be checked.
8. **Security findings to fix early (none are root of trust):**
   `OFFLINE=1` can be bypassed by a proxy on `127.0.0.1` (loopback is allowed, and the proxy carries the traffic out; reproduced);
   `hybrid_llm_router.is_online()` opens a TCP connection to `1.1.1.1:443` that is not in `NETWORK.md`;
   secret redaction exists in **six** copies, not two.
9. **P3 conflict:** the Supabase personal-memory function validates fact *content* server-side
   (`domain.ts: isSensitiveFactContent`). Client-side end-to-end encryption makes that impossible, so validation has to
   move to the client and the schema has to change (Q13).
10. **`Claude.md` forbids automatic update checks.** The pack updater and WinSparkle must default to a manual
    "Check for updates" button unless you opt in (Q6).
11. **Ring 1 cannot be both automatic and owner-signed.** The brief wants the owner as required reviewer on the signing
    environment and also wants ring 1 to become automatic after 10 patches. One key cannot do both; section 5 proposes
    two keys (Q7).

---

## 1. Verified current state (corrections to section 1 of the brief)

| Area | Brief says | Verified | Evidence |
|---|---|---|---|
| Repo | private use | **Public** on GitHub. Default branch `main`. | GitHub search API: `"private": false` |
| Host | PyQt6 + WebEngine, CI on 3.12 | Correct. `pyproject.toml` allows 3.11–3.13; dev runs on 3.13 here. | `pyproject.toml`, workflows |
| UI | React + TS + Vite in `frontend/`, web default, `JARVIS_UI=legacy` | Correct, with one structural detail: the web UI is an **overlay mounted on top of the legacy window's central widget** (`webui/attach.py`). The legacy HUD (`jarvis/ui`, 12k lines, `JarvisUI` in a 6.7k-line `__init__.py`) is always built underneath and is the fallback when WebGL2 is missing. The built bundle (1.7 MB) is committed to `jarvis/webui/dist`, and CI fails if it is stale. | `webui/attach.py`, `webui/fallback.py`, `webui-checks.yml` |
| Bridge | one slot `request(raw)`, `contract.py`, four gates | Correct. `contract.py` is hand-written validators, **not pydantic**, but already strict: closed set of 15 request kinds and 23 event kinds, extra fields rejected, nothing coerced, 16 KB hard cap and a 512 B default cap per request. Rate limits exist inside each gate (Command 0.5 s / 30 per min, Control 0.3 s, Job 0.3 s, Link 1 s), but **none on cheap kinds** (`ping`, `workspace.*`, `prefs.*`, `hologram.perf`). Mirror in `frontend/src/bridge/contract.ts`. | `webui/contract.py`, `webui/command_gate.py` |
| Engine | in-process, `main.py` ~3.6k lines | Correct: 3,634 lines. `JarvisLive` is one class built from 7 mixins in `core/runtime/`. `live_session.py` is only 50 lines of model-selection policy; the Live loop itself is in `main.py`. The engine runs on a non-daemon thread with its own asyncio loop, started by `core/runtime/bootstrap.py` after the API-key prompt. **`--headless` already exists** and runs `JarvisLive` against `HeadlessJarvisUI` (`core/ui_coordinator.py`, 20 methods). | `main.py`, `runtime/bootstrap.py` |
| Engine → UI surface | not described | 39 distinct `self.ui.*` members across `main.py` and the mixins (`write_log` ×104, `set_state` ×19, `muted` ×11, ...). Some are notifications, some need a reply (`prompt_pin`, `show_confirm`, `hud_video_is_active`, `current_file`, `get_plugins`), some are callbacks registered *on* the UI (`on_text_command`, `on_interrupt`, ...). One is a reach-in to the private Qt window (`self.ui._win`, in the reconnect path) that has to go. Full list in section 3.5. | grep of `self.ui.` |
| Qt outside the UI packages | not described | Qt is imported by avatar/visual helpers (`core/avatar*.py`, `neural_viz.py`, `earth_globe.py`, `hud_workspace.py`, `jarvis_logo*.py`, `startup_*.py`, `audio/visualizer_bridge.py`), which are UI and move to the host, and by **`computer_control/qt_prompt.py`** (approval prompt), which becomes an IPC request. | grep |
| Routing | router, fallback, providers, Ollama | Correct. `hybrid_llm_router.py` (420 lines): gemini, groq, openai, claude, ollama; per-provider latency tracking. `usage_meter.py` has a daily budget **alert**, not a cap; `claude_usage.py` is visibility only. Gemini Live audio usage is not metered at all. | files listed |
| Agent | planner graph, executor, runner, policy | Correct, 7.4k lines. Model planner plus deterministic planner (`planner.py`), DAG (`dependency_graph.py`, topological sort), parallel read layers, runner with pause/resume/cancel/retry, `policy.py` risk tiers with an approval callback for consequential steps. The five-layer plan already decided "LangGraph: skip". | `agent/`, `docs/plans/FIVE_LAYER_STACK_PLAN.md` |
| Memory | episodic ... consolidation, Supabase | Correct, 4.5k lines. SQLite + FTS5 with schema versioning and rolling backups (`memory_store.py`); optional 256-dim Gemini embeddings cached in `vectors.sqlite3` with brute-force cosine (`vector_index.py`, off by default); optional **local Fernet encryption** of sensitive rows. Supabase personal memory stores small plaintext facts and validates their content server-side. | `memory/`, `supabase/functions/jarvis-personal-memory/domain.ts` |
| Guest vs memory | guests never write owner memory | Guest restrictions are enforced at tool dispatch (`core/security.py:1026`). I found no guest check inside `jarvis/memory`, so background writes (session summaries, personal-fact capture) need a test in P3. | grep |
| Self-repair | `self_repair.py`, `ai_error_repair.py`, doc forbids auto-apply | Correct. `self_repair.record_error()` writes a redacted, fingerprinted JSONL incident log, which is the natural P2 intake. But **`install_global_exception_hooks()` is never called by the app** (only by tests), so uncaught crashes are not captured today, and hard crashes in native libraries never reach Python at all. **Not in the brief:** `actions/self_heal.py` (read-only health check + allowlisted `pip install`) and `actions/self_update.py` (git updater, refuses frozen builds). | files listed |
| Redaction | merge two modules | **Six** implementations: `core/self_repair.redact_secrets`, `core/ai_error_repair.redact_secrets`, `agent/store.redact`, `computer_control/redaction.redact_text/redact_params`, `memory/memory_manager.redact_sensitive_content` (adds email/phone PII), `webui/redact` (display: adds home paths and long opaque tokens). Some call each other. | grep |
| Aider | integrated | Correct. Installed separately (`aider-install`), driven as a CLI subprocess, analytics and update checks switched off. | `docs/AIDER.md`, `actions/aider_agent.py` |
| Security V2 | owner registry, Argon2, Voice ID, guest, full_access, guards | Correct. Spread over `core/` (`security.py` 1,171 lines, `owner_registry`, `owner_store`, `voice_id`, `guest_session`, `guest_audit`, `identity`, `full_access`, `confirm`, `injection_guard`, `path_guard`, `security_settings`) **and** `jarvis/security/` (`auth_manager`, `adaptive_auth`, `face_auth`, `voice_auth`, `lockdown`, `host_cloud_access`, `host_device_identity`). PIN is collected by a native Qt dialog (`ui.prompt_pin`) and verified by `auth_manager.verify_pin` on the engine side. | files listed |
| Eval | `run_eval.py` + `cases.jsonl` | Correct, but it is a deterministic, offline **memory-retrieval** eval only: recall@5, MRR, wrong-recall rate, abstention. Nothing about routing, planning, tools or voice. | `eval/run_eval.py` |
| Tests | ~170 files | 172 `test_*.py` files, 2,106 tests + 233 subtests (section 4). | pytest run |
| CI | no Windows runner | **Wrong: there is a `windows-latest` job** (`windows-ui-smoke` in `python-checks.yml`). It runs 23 test files offscreen, the computer-control resource baseline, the installer CLI and both `.bat` files. Correct that there is no packaging, updater or signing. Frontend CI: tsc, oxlint, prettier, vitest, token freshness, build, Storybook build, dist freshness. **No Playwright, no axe-core.** Security: detect-secrets (blocking), Semgrep (report-only), OSV-Scanner. | workflows |
| Repo rules | `Claude.md`, `OFFLINE=1`, `NETWORK.md` | Correct. `Claude.md` also says "assume yes, don't stop for approval". For this upgrade the brief's ASK BEFORE list overrides that, and this plan follows the brief. | `Claude.md` |
| Local servers | not described | Three exist already: the dashboard (FastAPI/uvicorn, `127.0.0.1`, or `0.0.0.0` when LAN is allowed), the device hub (WebSocket, `PROTOCOL_VERSION = 1`, pairing tokens) and the laptop-agent relay. They are precedents for the IPC handshake, and they stay in the engine. | `dashboard/server.py`, `hub/`, `laptop_agent/relay.py` |
| Data folder | not described | `core/user_data.py` resolves `%LOCALAPPDATA%\jarvis` on Windows (its docstring says `JarvisAI`, which is wrong). Only 27 modules use it; about 35 write next to the code instead. | grep |
| Measuring tools | not described | `tools/profile_ram.py` (process-tree RSS/USS to CSV), `computer_control.bench baseline` (Windows CI artifact), `webui/render_perf.py`. Reuse them, don't add new ones. | files listed |

---

## 2. Library decision table

Measured per library in a fresh Python 3.12 venv: growth of `site-packages`, number of packages pulled in, RSS added
by importing it, and any network attempt during import (sockets were trapped).
"Already" means it is in today's install.

| Library | Job | Existing JARVIS module | Decision | Install | Pkgs | Import RSS | Network on import | Why |
|---|---|---|---|---|---|---|---|---|
| pydantic 2.x | schemas for IPC, bridge, manifest | `webui/contract.py` (hand-written) | **Adopt** (declare it) | already | already | already | no | Already installed through fastapi, mcp, google-genai, openai and anthropic. Declare `pydantic>=2.7,<3` directly. |
| LangGraph 1.2 | agent graph, `interrupt()` | `agent/planner.py` + `dependency_graph.py` + `runner.py` + `policy.py` | **Skip** | 55 MB | 38 | 64.8 MB | no | It would sit beside a planner that already does DAG, retries, pause/resume and approvals (rule 2). The approval gate is wired to Security V2 over IPC instead (P1-M7). Also decided in the five-layer plan. |
| pydantic-ai (slim) 2.71 | typed agent framework | router + planner | **Skip** | 25 MB | 17 | 52.2 MB | no | Overlaps the router and planner; pydantic alone gives the typing. |
| LiteLLM 1.110 | provider routing, cost tracking | `core/hybrid_llm_router.py` (420 lines) + `usage_meter.py` | **Skip** | 255 MB | 60 | 174–200 MB | **yes**: `raw.githubusercontent.com` price list, unless `LITELLM_LOCAL_MODEL_COST_MAP=True` | Bigger than the problem: 7 s import, and it phones home on import. Hard caps go into `usage_meter` instead (P1-M8). |
| Langfuse 5.2 (client) | LLM traces | `core/plan_trace.py`, `core/action_log.py`, agent events | **Skip for now** | 23 MB | 28 | 32.9 MB | no | The client is fine, but self-hosting v3 means Postgres, ClickHouse, Redis and S3-compatible storage (*from docs*), which is not workable on a 4 GB laptop. P1-M9 writes a local, redacted JSONL trace from existing modules instead. |
| mem0 2.2 | adaptive memory | `memory/` (consolidation, scoring, lifecycle) | **Skip** unless the P3 benchmark wins | 133 MB | 33 | 98.3 MB | no | Needs an LLM call per write (cost, and data leaves the device) and duplicates consolidation. |
| graphiti-core 0.32 | temporal knowledge graph | `memory/associative_memory.py`, `memory_links` | **Skip** | 94 MB | 28 | 88.2 MB | no | Needs a graph database backend; the RAM budget does not allow one. |
| qdrant-client 1.20 (local mode) | vector search | `memory/vector_index.py` (SQLite + cosine) | **Benchmark-gated in P3** | 86 MB | 20 | 88.7 MB | no | Local mode runs in-process and is meant for small collections; at JARVIS's scale it is unlikely to beat SQLite. Adopt only on a measured recall or latency win. |
| tenacity 9.2 | retry/backoff | `agent/runner._backoff`, `self_repair.run_with_recovery` | **Skip** | <1 MB | 1 | 1.1 MB | no | Tiny, but supervisor restarts are a state machine (crash-loop counter, safe mode), not a function retry. About 20 lines inline. |
| psutil | CPU/RAM limits | already a dependency | **Reuse** | already | | | no | |
| sentry-sdk 3.0 | crash reporting | `self_repair` JSONL incident log | **Adopt in P1.5, opt-in** | 2 MB | 3 | 13.6 MB | no | Off by default, lazy-imported only when opted in and a DSN is set. The local crash queue stays the primary self-heal intake. |
| Hypothesis 6.x | property/fuzz tests | none | **Adopt (dev only)** | 4 MB | 2 | 15.2 MB | no | Manifest, bridge and IPC fuzzing. |
| pytest-qt 4.5 | Qt tests | `conftest.py` offscreen setup | **Adopt (dev only)** | 7 MB | 7 | ~0 | no | Supervisor, bridge and window tests. |
| E2B 2.64 | Linux repro sandbox | none | **Skip** | 35 MB | 27 | 36.2 MB | no (on import) | Paid third-party cloud that would receive code and crash data. Actions runners are free for public repos, and a local worktree covers the rest (Q1). |
| UnleashClient 7.0 | feature flags | `computer_control/flags.py`, config | **Skip** (deferred by the brief) | 10 MB | 18 | 20.3 MB | no | The signed manifest `channel` is the flag. |
| deepeval 4.3 | eval wrapper | `eval/run_eval.py` | **Skip** | 110 MB | 80 | 89.2 MB | no | `run_eval.py` is deterministic; deepeval's value is LLM-judge metrics, which cost money and send data out. |
| promptfoo | prompt regression | none | **Defer to P2** | Node CLI | | | | Dev-only, and only if we add prompt cases; it calls providers. |
| PyInstaller 6.22 vs Nuitka 4.3 | freeze the host | none (code already checks `sys.frozen`) | **PyInstaller onedir**, with a P1.5-M1 spike | 11 MB / 22 MB (build tools) | | n/a | n/a | Onedir avoids onefile's per-launch temp extraction (slow, and a common antivirus trigger). Mature PyQt6-WebEngine hooks; builds in minutes rather than a long C compile. Size, cold start and Defender results get measured on a Windows runner before committing; Nuitka is the fallback. Without a code-signing certificate both trigger SmartScreen (Q11). |
| WinSparkle | host updates | none | **Adopt in P1.5** | native DLL | | | only when checking | Manual check by default (`Claude.md`). If the pinned WinSparkle version cannot verify EdDSA appcast signatures, the host verifies the installer with the pinned key before launching it. |
| cryptography | Ed25519, AES-GCM | already a dependency | **Reuse** | already | | | no | No PyNaCl. |
| keyring | key storage | already a dependency | **Reuse** | already | | | no | |
| uv (dev tool) | hashed lockfile | none | **Adopt (dev only)** | n/a | | | | `uv pip compile --universal --generate-hashes` handles the `sys_platform` markers in one file; CI installs with `--require-hashes`. pip-tools (13 MB) is the alternative. |
| @playwright/test + @axe-core/playwright | frontend E2E + accessibility | vitest only | **Adopt (frontend dev only)** in P1.5-M7 | n/a | | | | |

---

## 3. Process split map

### 3.1 Host process (frozen, rarely updated)

Window and Qt: `core/runtime/bootstrap.py` (desktop path), `startup_sequence.py`, `startup_video.py`, `qt_webengine.py`, `qtwebengine_flags.py`, `jarvis/ui/**` (legacy HUD, Q5), avatar/visual helpers (`core/avatar*.py`, `neural_*`, `earth_globe.py`, `hud_workspace.py`, `jarvis_logo*.py`, `audio/visualizer_bridge.py`).
Web UI: `webui/host.py`, `bridge.py`, `contract.py`, the four gates, `navigation.py`, `telemetry.py` (local psutil metrics), `render_perf.py`, `workspace_store.py`, `fallback.py`.
New: `jarvis/host/supervisor.py`, `jarvis/host/updater/`, `jarvis/host/manifest.py`, pinned public key(s), safe-mode screen, native PIN and confirm dialogs, and an `EngineUIProxy` that turns engine events into calls on `JarvisUI` / `WebUIHost`.

### 3.2 Engine process (Python subprocess, no Qt)

`main.JarvisLive` + `core/runtime/*` (minus the bootstrap desktop path), `live_session`, `live_audio`, `audio_capture`, `audio_playback`, `barge_in`, `echo`, `viseme`, `vocal_behavior`, `wake_word`, `clap_wake`, `voice_id`, `tts`, `gemini`, the router and providers, `agent/`, `computer_control/` (with `qt_prompt` replaced by an IPC request), `memory/`, `actions/`, `plugins/`, `knowledge/`, `dashboard/` (it calls the assistant), `mcp_client`, `jobs`, `triggers`, `routines`, `usage_meter`, the Security V2 decision logic (Q4), and `self_repair` hooks.
The engine owns the audio devices, so **no audio crosses the IPC**: only levels and viseme batches do.
The hub (`python -m jarvis.hub`) is already a separate process and stays one.

### 3.3 What a Qt-free engine needs

- A CI test that imports the engine with PyQt6 blocked (the probe used for section 4 does exactly this and passes today).
- `HeadlessJarvisUI` grows into `RemoteUI`: same 39 members, each sending an IPC message.
- `computer_control/qt_prompt.py`, `core/confirm.py` and the agent's approval callback all go through one `host.confirm` request.

### 3.4 Transport: decision needed (Q2)

The brief offers a Windows named pipe or a 127.0.0.1 socket. **I recommend a third option: the child process's own
stdin/stdout pipes**, created by the supervisor with `subprocess.Popen`.

| | stdio pipes (recommended) | named pipe | 127.0.0.1 TCP |
|---|---|---|---|
| Who can connect | nobody: there is no endpoint | same-user processes unless ACL'd and first-instance flagged | any local process, any user |
| Extra code / deps | none | pywin32 or asyncio private API, ACL handling | port handling; firewall and AV noise possible |
| Orphan guard | stdin EOF is immediate | must poll | must poll |
| Cross-platform | identical | Windows only (needs a Unix-socket twin) | identical |
| Downside | stray `print()` would corrupt framing (fixed by moving fd 1 to stderr at engine start); cannot reattach after host restart (not wanted anyway) | | |

Details either way: the per-launch token (32 random bytes) is the first line on stdin, never argv and never env.
Framing is newline-delimited JSON-RPC 2.0, at most 64 KiB per frame, with tighter caps per method.
Every method has a pydantic model with `extra="forbid"`. The first exchange is `sys.hello`
(`protocol_version`, versions, token). The engine exits when (a) stdin hits EOF, (b) the parent PID disappears
(checked every second, matching create time), or (c) on Windows, the host's Job Object closes
(`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`). That gives the "engine exits within 5 s" guarantee three ways.

There is deliberately no generic "call any tool" method, so the IPC never becomes a way to serve JARVIS tools
(`test_no_mcp_server_exposes_the_tools` stays meaningful).

### 3.5 Host ↔ engine calls (seed of the JSON-RPC schema)

**Engine → host, notifications**

| Method | Replaces | Notes |
|---|---|---|
| `ui.log {text}` | `write_log` (×104) | ≤ 2,000 chars; the host still runs `webui/redact` before display |
| `ui.state {state}` | `set_state` | enum |
| `ui.audio_level {level, source}` | `set_audio_level` | rate-limited to 30 Hz |
| `ui.visemes {frames, hop, at}` | `push_visemes` | one batch per playback write |
| `ui.avatar_text {text}` | `react_avatar_text` | |
| `ui.content {title, text}` | `show_content` | ≤ 32 KiB |
| `ui.voice_id_enabled {enabled}` | `set_voice_id_enabled` | |
| `ui.phone_connected` | `notify_phone_connected` | |
| `ui.live_panel {...}` | `show_live_panel` | |
| `ui.briefing {action, items}` | `show/hide_briefing_news`, `open_latest_holo_news` | |
| `ui.camera {on}` | `start/stop_camera_stream` | preview ownership decided in P1-M4 |
| `ui.confirm_hide {action_id}` | `hide_confirm` | |
| `ui.close` | `request_close` | |
| `ui.provider`, `ui.jobs`, `ui.task_flow`, `ui.shape`, `ui.memory_status` | existing web events | same validation as `contract.py` |
| `security.state {locked, needs_pin, silent, guest}` | gates calling `security.get_auth_manager()` in-process | new; host gates fail closed ("unavailable") when the snapshot is older than 2 s or the engine is down |

**Engine → host, requests that need a reply**

| Method | Replaces | Notes |
|---|---|---|
| `host.prompt_pin → {pin \| null}` | `prompt_pin` | Security V2. Native dialog; the PIN crosses the pipe once and is never logged. |
| `host.confirm {action_id, prompt, tier} → {approved}` | `show_confirm`, `qt_prompt`, agent approvals | Security V2 |
| `host.reconfigure` | `prompt_reconfig` | |
| `host.hud_video_active → bool` | `hud_video_is_active` | |
| `host.current_file → str \| null` | `current_file` | |
| (moves to engine) | `get_plugins`, `get_plugin_settings` | plugin state belongs with plugins |

**Host → engine, commands**

| Method | Replaces |
|---|---|
| `engine.text_command {text}` | `on_text_command`, CommandGate sink |
| `engine.interrupt` | `on_interrupt` |
| `engine.set_muted {muted}` | the engine reading `ui.muted` (×11): the engine now owns the muted state |
| `engine.ptt {held}`, `engine.push_to_talk {enabled}` | `ptt_hold`, `on_push_to_talk` |
| `engine.voice {kind, settings}` | `on_voice_change`, `on_audio_device_change`, `on_voice_personality_change`, `on_voice_preview` |
| `engine.voice_id {action}` | `on_voice_id_action` (Security V2) |
| `engine.remote {action}` | `on_remote_clicked` |
| `engine.wake {action}`, `engine.wake_state → state` | `on_wake_toggle/manual/install`, `wake_is_ready`, `wake_get_state` |
| `engine.say {text}` | `request_say` |
| `engine.job_cancel {id}` | JobGate |
| `engine.shutdown` | `request_shutdown` |

**Lifecycle:** `sys.hello` / `sys.welcome` (handshake), `sys.ping` / `sys.pong {n, rss_mb, cpu}` every second,
and engine stderr captured by the host into a rotating log file. `wait_for_api_key` moves to the host: it makes sure
a key exists before it starts the engine, as the UI does today.

### 3.6 Security V2 across the split (root of trust, Q4)

Recommendation: the engine stays the single owner of auth state (it already verifies PINs and runs Voice ID).
The host keeps the native PIN and confirm dialogs and reads a pushed `security.state` snapshot, failing closed when
it is stale. No auth decision is made in two places. This touches root-of-trust code, so it needs your explicit yes.

---

## 4. Baselines

### 4.1 Measured here (Linux container, Python 3.12, software GL)

| Metric | Value | How |
|---|---|---|
| Web UI host: QApplication → page "ready" | 0.30–0.42 s warm, 0.91 s first run | `QApplication` + `WebUIHost` offscreen until the `ready` signal |
| Web UI host idle RSS | host 261 MB, **tree 533 MB** (incl. QtWebEngineProcess) | psutil, 3 s after ready; WebGL2 is blocklisted here, so the Windows GPU path will differ |
| `import jarvis.main` today (engine + Qt UI, one process) | 0.66 s, 118.6 MB | fresh interpreter, 3 runs |
| Engine imports with PyQt6 blocked | 0.64 s, 85.4 MB | same, Qt made unimportable: **imports cleanly** |
| Host-only imports | 67.4 MB (web UI) / 81.4 MB (+ legacy HUD, which pulls numpy) | same |
| **Split cost (est.)** | about +30–50 MB (second interpreter, numpy, shared core modules) ≈ **+6–9 % of the idle tree** | from the rows above; to be confirmed on Windows |
| Live session RSS | not measurable here (no Gemini key, no audio device) | owner, see 4.2 |
| Mic → first audio byte | **no instrumentation exists** | P1-M0 adds it |
| Eval (`run_eval.py`) | recall@5 **1.000**, MRR **1.000**, wrong recall 0.000, abstention 1.000, 40 cases, 4.9 ms avg | committed `baseline.json` is older and worse (MRR 0.970, wrong recall 0.057); refresh it in P1-M0 with your OK |
| Python tests | **2,106 tests**: 2,096 passed, 9 skipped, 1 environment failure; 233 subtests; 172 files; **153 s** wall | `pytest -q`, offscreen. The failure is the `OFFLINE=1` proxy gap (section 0, item 8); it passes with the proxy variables unset. |
| Frontend tests | **201 tests in 33 files, all passed**, about 11 s | `npx vitest run` |
| Ruff | 0 findings | `ruff check jarvis` |
| Windows CI | 23 test files on `windows-latest` | `python-checks.yml` |

### 4.2 Owner measurements on Windows (needed before P1-M4 flips the default)

Idle and Live RSS: start JARVIS, find the PID, then run
`python jarvis/tools/profile_ram.py --pid <PID> --duration 120 --label idle` and again with `--label voice` during a
Live conversation. Voice latency: after P1-M0 lands, set `JARVIS_LATENCY_TRACE=1`, say ten short phrases, and send me
the summary line it prints. Same steps after the split. All of this is added to `docs/WINDOWS_SMOKE_TEST_CHECKLIST.md`
in P1-M0.

Budget question (Q9): `profile_ram.py`'s docstring says the target laptop has **4 GB of RAM**. I propose measuring the
+15 % rule against total process-tree RSS (what Task Manager shows). On that base the split is about +6–9 %.

---

## 5. Phase plan

Milestones are named `P1-M<n>` so they don't collide with phase "P1.5". ★ marks root-of-trust PRs, which wait for
your explicit "merge". Every PR: CI green on Linux and Windows, plus the section 7 report.

### P1: engine isolation

| PR | Content | Notes |
|---|---|---|
| P1-M0a | Latency trace (`JARVIS_LATENCY_TRACE=1`: end of user speech → first server audio chunk → first chunk written to the device; local file only); `jarvis/tools/baseline.py` wrapping `profile_ram` and `run_eval`; Windows checklist items | measuring only |
| P1-M0b | One `jarvis/core/redaction.py` with profiles (`secrets`, `secrets+pii`, `display`); the six old functions become thin wrappers so no caller or test changes | rule 7 |
| P1-M0c | Declare `pydantic`; add Hypothesis and pytest-qt to dev requirements; hashed lockfile + CI `--require-hashes` check | dependency change |
| P1-M0d | `NETWORK.md` line for the `1.1.1.1` probe; `OFFLINE=1` also ignores proxy environment variables; regression test | privacy |
| P1-M1 | `python -m jarvis.engine`; `RemoteUI`; Qt-blocked import test in CI | |
| P1-M2 ★ | `jarvis/ipc/`: framing, JSON-RPC envelope, pydantic models, handshake, size and rate limits, Hypothesis tests | trust boundary |
| P1-M3 ★ | Supervisor: spawn, heartbeat, psutil soft/hard limits, backoff, crash-loop counter (≥3 in 5 min → safe mode + rollback offer), orphan guard | watchdog |
| P1-M4 | `EngineUIProxy`; gates forward over IPC; `JARVIS_ENGINE=inproc\|subprocess`, default `inproc` until your Windows smoke test passes, then flipped in its own PR | rollback = flag |
| P1-M5 | Audio proof: engine owns sounddevice; level/viseme events rate-limited; latency before/after | +50 ms budget |
| P1-M6 ★ | Bridge contract → pydantic: same closed set, extras forbidden, sizes kept; token-bucket rate limit on every kind; Hypothesis fuzz; a test that the Python and TS kind lists match | bridge/contract |
| P1-M7 ★ | One approval path over IPC (`host.confirm`) for `qt_prompt`, `confirm.py` and agent policy; Security V2 semantics unchanged; LangGraph "skip" recorded | Security V2 |
| P1-M8 | Hard per-task and per-day caps: `usage_meter` turns from alert into gate, checked before every router call | no LiteLLM |
| P1-M9 | Opt-in local JSONL trace (redacted, user data folder) from `plan_trace` / `action_log` | no Langfuse |

Acceptance (from the brief): kill the engine → host stays up, UI shows "reconnecting", engine restarts; kill the host → engine exits in ≤5 s; all existing tests green; Windows CI green; `OFFLINE=1` boots.

### P1.5: release pipeline

| PR | Content |
|---|---|
| P1.5-M0 | **State root (data migration, Q3):** `jarvis/core/paths.py` (code root vs state root vs cache root); move the ~35 modules; one-time copy-then-switch migration with a marker file; originals kept for one release; rollback = delete the marker |
| P1.5-M1 | Freeze spike: PyInstaller onedir host on a Windows runner (unsigned artifact). Measure size, cold start and a local Defender scan. Nuitka in the same job only if PyInstaller misses budget. No VirusTotal upload without your yes (it sends the binary to a third party). |
| P1.5-M2 ★ | Pack store `%LOCALAPPDATA%\jarvis\packs\<ver>\{ui,engine}` (same folder as `user_data_dir`; Windows paths are case-insensitive, so this equals the brief's `JARVIS`). `current.json` / `previous.json` pointers swapped with `os.replace` (atomic on NTFS within one volume; no symlinks or junctions); engine restart; rollback button + CLI; drill <60 s. Host loads the UI pack instead of `jarvis/webui/dist`, so `navigation.py` changes too. |
| P1.5-M3 ★ | Manifest verification: canonical JSON (sorted keys, `(",", ":")` separators, UTF-8, `sig` excluded from the signed bytes), Ed25519 via `cryptography`, per-artifact sha256, `min_host`, channel, anti-downgrade (highest version seen is kept in state) with the explicit rollback-to-`previous` exception; tamper tests |
| P1.5-M4 ★ | Release workflow: UI pack zip + engine wheel + host build; signing in protected environments (Q7) |
| P1.5-M5 | WinSparkle: appcast on GitHub Releases, manual check by default, `NETWORK.md` line |
| P1.5-M6 | sentry-sdk: opt-in toggle in System Control Center, offline queue, `before_send` through the shared redaction module, no audio/screens/files/PII, `NETWORK.md` line |
| P1.5-M7 | CI matrix: grow the Windows job from 23 files toward the full suite; pytest-qt; Playwright + axe; Hypothesis for manifest/bridge/IPC; monthly drill workflow skeleton |

Packaging consequence to accept: the host freezes the Python runtime and every third-party dependency (forced in,
because PyInstaller's analysis only sees what host code imports). The engine wheel is JARVIS code only and runs as
`jarvis.exe --engine` with `packs\current\engine` first on `sys.path`. Host and engine both carry a few shared modules
(e.g. `contract.py` imports `core/brain_shapes.py`), so `protocol_version` and `min_host` guard version skew.

Signing (Q7): one key cannot satisfy both "owner is required reviewer for signing" and "ring 1 becomes automatic".
Proposal: two Ed25519 keys. A **canary key** lives in a `canary-release` environment restricted to `main` and signs
automatically. A **stable key** lives in `release`, with you as required reviewer. The host pins both public keys and
accepts canary-signed manifests only when `channel=canary` and you have opted into canary locally. Required reviewers
work here because the repo is public. If it ever goes private on a personal plan, that rule disappears, and offline
stable signing becomes the fallback.

### P2: self-heal (design depends on Q1)

- **Intake:** install the existing global exception hooks in the engine (they are currently unused), and have the supervisor record engine exit codes plus the stderr tail for crashes Python never sees (native audio or Qt libraries). Then extend `self_repair.record_error`. The fingerprint uses the exception type plus normalized in-repo frames (not the message), with 30-day dedupe and caps of 3 open per fingerprint and 10 per day. The journal lives in the **state folder**, never in the repo (the repo is public).
- **Journal:** append-only, hash-chained JSONL plus a verifier.
- **Repro:** the repro test is written next to the crash data. Under the recommended Q1 option that means on your laptop, in a separate git worktree, with Aider (already installed). Windows-native repro matches the real target. CI (Linux + Windows, free for public repos) then verifies. Hardware-dependent bugs go to HUMAN_QUEUE. No E2B.
- **Patch:** Aider with `--test-cmd <frozen repro>`, `--no-suggest-shell-commands`, `--analytics-disable`, `--no-check-update`.
- **Test freeze:** a CI check (root of trust) compares the repro test's hash with the journal entry and rejects any added skip, xfail or deleted test.
- **Gates, PR, CI pack build, rings, watch and auto-revert:** as in Appendix A of the brief. `jarvis/selfheal/AGENT_PROMPT.md` and the `docs/AI_SELF_HEALING_REPAIR.md` update land in the same PR that changes behaviour.
- **Kill switch:** `JARVIS_SELFHEAL` stays off until you turn it on.
- **Name clash:** the existing `self_heal` voice action (health check) and the new `jarvis/selfheal/` package. I propose renaming the action's description to "health check" and keeping its tool name for compatibility.

### P3: adaptive memory

- Add a recall benchmark to `jarvis/eval/` first (paraphrase, temporal and multi-hop cases). Adapters behind `memory_controller` land only if they beat it.
- E2E encryption with AES-GCM via `cryptography`, key in the OS keyring. This needs: validation moved into Python (`redact_sensitive_content` already covers most of it), a Supabase schema migration so the server stores ciphertext and validates only sizes and format (Q13), and a decision on key backup (Q12).
- A test that guest turns never reach session summaries or personal-fact capture.

### P4: guardrails and drills

As in the brief. Concrete additions:
- The root-of-trust guard is a required CI job that fails when a PR touches a path in section 6. It passes only after your approval of a `root-of-trust` environment job; a label would not work, because an agent could add the label.
- The monthly drill uses the P1.5-M2 rollback CLI.
- Injection tests reuse `test_computer_control_injection.py` patterns with poisoned crash events and poisoned repo text.

---

## 6. Proposed root-of-trust paths

Updater and keys: `jarvis/host/updater/**`, `jarvis/host/manifest.py`, `jarvis/host/keys/**`.
Watchdog: `jarvis/host/supervisor.py`.
Bridge and IPC: `jarvis/webui/bridge.py`, `jarvis/webui/contract.py`, `frontend/src/bridge/contract.ts`, `jarvis/webui/navigation.py`, `jarvis/ipc/**`.
Security V2: `jarvis/core/{security,owner_registry,owner_store,voice_id,guest_session,guest_audit,identity,full_access,confirm,injection_guard,path_guard,security_settings}.py`, `jarvis/security/**`.
Self-heal: `jarvis/selfheal/AGENT_PROMPT.md`, `jarvis/selfheal/policy*`, `jarvis/selfheal/gates*`.
CI: `.github/workflows/release*.yml`, `.github/workflows/root-of-trust-guard.yml`, signing scripts.
Existing update/repair paths: `jarvis/actions/self_update.py`, `jarvis/actions/self_heal.py`.
Dependencies (L3, human only): `requirements*.txt`, the lockfile.

---

## 7. Risks and rollback per phase

| Phase | Main risks | Mitigation | Rollback |
|---|---|---|---|
| P1 | Security state out of sync between host and engine; hidden synchronous UI calls on the Qt thread; stray prints corrupting the pipe; RAM on a 4 GB laptop; Windows console windows or Defender reacting to the child process | Fail-closed `security.state`; every reply-type call has a timeout; fd 1 moved to stderr; budgets measured on your laptop; `CREATE_NO_WINDOW` | `JARVIS_ENGINE=inproc` stays available for at least one release after the flip; revert PRs |
| P1.5 | Antivirus false positives; SmartScreen; frozen builds missing rarely used imports; state migration losing data; pointer swap while the engine runs | Defender scan in CI; force-collect every requirement; copy-then-switch migration that keeps originals; swap only while the engine is stopped | `previous` pointer; keep the previous host installer; delete the migration marker |
| P2 | Prompt injection through crash text; cost overrun; flaky repro tests; private data reaching the public repo | Tool allowlist; caps of $1.50 per issue / $5.00 per day; repro must fail 3/3 before freezing; journal outside the repo, redaction before any push | Kill switch; pack pointer revert; `git revert` |
| P3 | Lost key means lost cloud memory; benchmark overfitting; migration | Key backup decision; held-out cases; staged migration | Encryption behind a flag; plaintext local DB is untouched |
| P4 | Guard false positives blocking normal PRs | Exact path list, reviewed once | Revert the workflow |

---

## 8. Open questions

Blocking P1:
- **Q2 IPC transport:** stdio pipes (recommended), named pipe, or loopback TCP?
- **Q4 Security V2 across the split:** the engine owns auth state, the host shows native dialogs, and the PIN crosses the pipe once. Yes or no? (root of trust)
- **Q9 RSS budget base:** total process tree (recommended; split ≈ +6–9 %) or host process only?
- **Q15 Branch names:** this cloud session can only push to `ccr-e8facd3a-frxj40`. Should later milestones use `upgrade/prod-arch-<phase>-<milestone>` as the brief says? That needs your permission for each new branch.

Before P1.5:
- **Q3 State-root migration:** approve moving `config/`, memory, logs and Security V2 state into `%LOCALAPPDATA%\jarvis\`, with copy-then-switch and the originals kept for one release?
- **Q5 Legacy HUD:** freeze it into the host (recommended; HUD fixes then need a host release) or let the host load HUD code from a pack (pack code would then run inside the host process)?
- **Q6 Update checks:** manual "Check for updates" only (recommended, matches `Claude.md`) or an opt-in daily check?
- **Q7 Signing:** two keys, canary automatic and stable owner-approved (recommended), one key with you as reviewer (ring 1 can never be automatic), or offline signing?
- **Q10 Existing updaters:** keep `self_update.py` for git checkouts only, disable `self_heal.py`'s pip path in frozen builds, and add both to the root of trust?
- **Q11 Code-signing certificate:** buy one, or accept SmartScreen warnings?

Before P2:
- **Q1 Where self-heal runs, given the public repo:**
  (a) repro and patching on your laptop in a separate worktree; only the patch and repro test go to GitHub, after redaction and (for the first 10) your review. Recommended.
  (b) a private companion repo for self-heal runs.
  (c) make the main repo private, which removes required reviewers on a personal plan, so signing goes offline.
- **Q8 Eval scope:** add offline routing, planner and tool-choice cases so the "eval −2 %" gate means something?
- **Q14 Spend reporting:** I cannot see this session's token spend from inside it. Is your usage page enough for "report spend per PR"?

Before P3:
- **Q12 Key backup:** none, a printed recovery code, or a passphrase-wrapped key stored in Supabase?
- **Q13 E2E encryption:** OK to move fact validation client-side and migrate the Supabase table to ciphertext?

---

## 9. Conflicts found in the brief

| Conflict | Proposed resolution |
|---|---|
| "1.5 Bridge" milestone vs "P1.5" phase | Milestones renamed `P1-M<n>` |
| Ring 1 automatic vs owner-approved signing | Two keys (Q7) |
| `issues/journal/<fp>.md` in a public repo | Journal in the state folder |
| Self-heal "no host changes" vs legacy HUD in the host | HUD frozen into the host, outside self-heal's reach (Q5) |
| `Claude.md` "assume yes" vs the brief's ASK BEFORE | The brief wins for this upgrade |
| `Claude.md` "no update checks" vs updater | Manual by default (Q6) |
| "No Windows runner" | One exists; it grows instead of being added |
| "Merge two redaction modules" | Six exist; one module with profiles |
| "Eval −2 %" as a safety gate | Only covers memory retrieval today (Q8) |
| E2B as repro sandbox | Third-party data flow; free Actions runners and a local worktree instead |
