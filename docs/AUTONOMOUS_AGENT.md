# Autonomous Agent, Screen Vision and Computer Use

JARVIS can now carry a multi-step objective to completion from a single
instruction: **understand → plan → observe → act → verify → recover → continue →
report**. This document describes what is implemented, how to configure it, the
security model, and the known limitations. Everything here is backed by tests in
`JarvisAI/tests/test_agent_*.py` and can be inspected in `JarvisAI/agent/`.

```
voice / HUD text
      │
      ▼
actions/autonomous_task.py ──► agent/integration.py (AgentService)
                                      │
        ┌─────────────────────────────┼───────────────────────────┐
        ▼                             ▼                           ▼
  agent/planner.py            agent/runner.py                agent/events.py
  (model or heuristic)   (states, retries, budgets,     (thread-safe progress
        │                  pause/cancel, checkpoints)     bus for UI + voice)
        ▼                             │
  agent/policy.py ─────────────► agent/executor.py
  (READ/WRITE/CONSEQUENTIAL)          │
                          ┌───────────┼──────────────┬───────────────┐
                          ▼           ▼              ▼               ▼
                   shell/tests   files          screen vision   computer use
                                  (inside repo)  (Gemini/OCR)    (pyautogui)
```

## 1. What it can do

| Capability | Where | Notes |
| --- | --- | --- |
| Plan an objective | `agent/planner.py` | The configured text model (`core/hybrid_llm_router.py`) produces a validated JSON plan; without a model a deterministic engineering plan is used and any step that genuinely needs a model is reported as blocked. |
| Run steps with recovery | `agent/runner.py` | Retries only transient failures, exponential backoff, per-step and per-task retry budgets, wall-clock deadline, loop detection. |
| Persist and resume | `agent/store.py` | Atomic JSON snapshot + fsynced JSONL journal per task; a crash or restart resumes at the step cursor. |
| Pause / resume / stop | runner + HUD + Dynamic Island | Stop is immediate and is classified `SAFE`, so it is never gated. |
| Read the screen | `agent/screen_capture.py`, `agent/screen_vision.py` | On-demand capture (mss, Pillow fallback), downscaled JPEG, mouse/keyboard-free OCR (Tesseract), Gemini/OpenAI vision, accessibility tree lookup. |
| Act on the desktop | `agent/computer_use.py`, `agent/accessibility.py` | Click/type/keys/scroll/focus by *named target*; validated bounds and confidence; re-observation after every action; dry-run mode. |
| Speak progress | `agent/voice.py` | Milestones only (plan, blocker, pause, completion), throttled to at most one sentence every ten seconds; step chatter stays silent. |
| Show progress | `ui/panels/autonomous_panel.py`, `ui/dynamic_island.py` | Bento card on the existing dashboard page; compact island when the HUD is minimised. |

### Triggering it

* **Voice / typed command** — “JARVIS, inspect my project, fix the errors, run all
  relevant tests and continue until the task is completed.” The Gemini Live tool
  call `autonomous_task(action="run", objective=...)` starts it, and
  `actions/autonomous_task.py` returns immediately (the tool is declared
  `NON_BLOCKING`), so conversation continues while the worker runs.
* **Steering** — “stop”, “pause”, “resume”, “status”, “report”:
  * spoken through the model → `autonomous_task(action=...)`;
  * typed or spoken while Live is busy/disconnected → intercepted locally in
    `JarvisLive._route_agent_text` so `stop` never depends on a network round trip.
* **HUD** — ▦ dashboard → `◉` in the left rail, or the ⋮ menu → “AUTONOMOUS TASKS”.
  The card has PAUSE/RESUME, STOP, REPORT and REFRESH.
* **Minimised** — the Dynamic Island shows state and (expanded) progress with pause
  and stop; clicking it restores the HUD.

## 2. Configuration

All settings live in `JarvisAI/config/api_keys.json` (git-ignored, written
atomically with `0600`), and every one can be overridden by an environment
variable where noted.

| Key | Default | Meaning |
| --- | --- | --- |
| `autonomous_enabled` | `true` (`JARVIS_AUTONOMOUS=0` disables) | Master switch. |
| `autonomous_allow_shell` | `true` | Allow commands/tests. When `false`, only vision steps run. |
| `autonomous_allow_files` | `true` | Allow writing files, restricted to the repository workspace. |
| `autonomous_allow_desktop` | `true` | Allow mouse/keyboard control. |
| `autonomous_dry_run` | `false` (`JARVIS_AGENT_DRY_RUN=1`) | Resolve targets but never move the pointer. |
| `autonomous_screen_paused` | `false` | Owner turned screen access off; every capture raises. |
| `autonomous_max_runtime_s` | `1800` (`JARVIS_AGENT_MAX_RUNTIME`) | Hard wall-clock budget per task (30 s – 4 h). |
| `autonomous_retry_budget` | `12` | Retries across a whole task. |
| `autonomous_max_steps` | `12` | Plan size cap (3 – 16). |
| `autonomous_voice_updates` | `true` | Spoken milestone announcements. |
| `autonomous_ui_enabled` | `false` (`JARVIS_AUTONOMOUS_UI=1`) | Draw the autonomous HUD surfaces (card, rail button, menu entries). Off by default so the HUD keeps its clean composition. |
| `vision_model` | `gemini-2.5-flash` (`JARVIS_VISION_MODEL`) | Gemini vision model id. |

Task state is written to `JarvisAI/memory/agent/` (git-ignored). Override with
`JARVIS_AGENT_DIR` — the test suite uses this to stay out of the checkout.

### The HUD surfaces are opt-in

The engine, the `autonomous_task` voice tool, the report and the CLI work with
no UI at all. Drawing the extra surfaces — the dashboard card, the `◉` rail
button and the two menu entries — changes the composition of a HUD that is
deliberately clean, so it is off unless asked for:

```
JARVIS_AUTONOMOUS_UI=1 python main.py        # or autonomous_ui_enabled: true
```

With the flag off, `HUDMainWindow` has no extra card, keeps its two rail
buttons and adds no menu entries; `test_hud_stays_clean_while_the_ui_flag_is_off`
enforces exactly that. The minimised island is independent of this flag — it is
a shared battery, health and hologram surface as well.

### API keys, network and paid usage

| Feature | Needs | Without it |
| --- | --- | --- |
| Screen understanding (layout, dialogs, errors) | `gemini_api_key` (or `GEMINI_API_KEY`) and internet. Gemini vision is a paid API call, roughly one small JPEG per observation. | OCR-only descriptions that explicitly say layout was not analysed, or a clear “I cannot see the screen” error. |
| Second vision opinion | `openai_api_key` / `OPENAI_API_KEY` (optional) | Not used. |
| Model-quality planning and code fixes | any configured text provider (`gemini`, `openai`, `anthropic`, `groq`) or local Ollama | Deterministic inspection + test plan; “fix the code” steps are reported **blocked** with the exact reason instead of guessing. |
| Local OCR | `pytesseract` (already in `requirements.txt`) **plus the Tesseract desktop engine** | OCR disabled; vision-only, or an actionable error. |
| Screen capture | `mss` (already in requirements), Pillow fallback | Capture error that names the missing package. |
| Desktop control | `pyautogui` (already in requirements), plus macOS Accessibility permission | Actions blocked; the runner re-plans or reports the blocker. |

No key is required to *test* the engine: the test suite injects every external
dependency.

## 3. Security model

Autonomy does not bypass any existing protection. Five gates apply, in order:

1. **Tool tiering** (`core/security.py`): `autonomous_task` is `SENSITIVE` for
   `status/report/pause/resume`, `DANGEROUS` for `run`, and `SAFE` for `stop` so
   the emergency brake always works.
2. **Owner authentication** (`security/auth_manager.py`, unchanged): `AgentService.start`
   refuses unless the owner is verified and Privacy Lock is off.
3. **Per-step classification** (`agent/policy.py`): every step is independently
   labeled `READ`, `WRITE` or `CONSEQUENTIAL` from its command text — not from the
   model’s claim. Delete/force-push/install/publish/shutdown/credential/payment
   patterns fail closed. File writes are confined to the repository.
4. **Human approval for consequential steps** (`core/confirm.py`, unchanged):
   the runner parks in `WAITING`, shows the normal banner, and continues only after
   CONFIRM. Headless runs deny (`confirm.is_bound()` is false).
5. **Audit and provenance**: the existing SHA-256/HMAC ledger and untrusted-content
   guard still wrap every dispatch; the engine adds a per-task journal (also
   redacted) under `memory/agent/`.

Additional behaviour worth knowing:

* Output, errors and journal entries pass through `core.self_repair.redact_secrets`
  plus an engine-local pass for `api_key=`, `token=`, `password=` shapes.
* Screenshots are never written to disk; buffers are released after each use.
* `stop` sets a cancellation event checked before every action, inside the
  subprocess polling loop (which terminates, then kills), and during retry backoff.
  A step cut short by `stop` is recorded as **skipped** ("Stopped by the owner."),
  not failed, and every step that never ran is marked skipped too — so a stopped
  task never reports fake failures.
* Spawned commands run with a scrubbed environment: `JARVIS_AGENT_*`,
  `JARVIS_AUTONOMOUS` and `JARVIS_VISION_*` are removed and only
  `JARVIS_AGENT_CHILD=1`, `PYTHONUNBUFFERED=1` and `NO_COLOR=1` are added. A test
  run started by the agent therefore sees the same configuration a human running
  `pytest` would, instead of inheriting the agent's dry-run/runtime/task-directory
  switches.
* Command output is capped at 6 000 characters by keeping the **first 1 500 and
  the last ~4 300**, with an explicit "… [N characters clipped] …" marker. The head
  alone used to be kept, which silently dropped pytest's trailing "N passed" line
  and left the verification step unable to tell a green suite from a red one.

### Runtime authorization revalidation

Starting a task is not a permanent authorization grant. JARVIS rechecks the current
owner-access state and Privacy Lock before every step and retry. Resuming a paused
or persisted task also requires current owner access, an enabled autonomy setting,
and an unlocked privacy state. If the security state cannot be read, the task is
blocked rather than treated as unlocked.

Privacy Lock also pauses the agent's screen-capture source. The manual screen-pause
preference remains independent, so unlocking Privacy Lock does not silently undo
a user-requested screen pause. Desktop input rechecks owner access and Privacy Lock
at action time; dry-run does not override Privacy Lock.

## 4. Step kinds

| Kind | Effect | Policy tier |
| --- | --- | --- |
| `inspect` | read-only command | READ (from command) |
| `run_command` | policy-checked subprocess in the repo, merged output, timeout | READ/WRITE/CONSEQUENTIAL |
| `run_tests` | test command + pass/fail parsing into evidence | as above |
| `read_file` / `write_file` | inside the workspace only | READ / WRITE |
| `observe_screen` | capture + vision/OCR observation | READ |
| `screen_action` | click/type a named target, then re-observe | CONSEQUENTIAL (approval) |
| `verify` | checks `test_failures`, `contains`, `not_contains`, `file_exists`, `vision` | READ |
| `note` | records a decision/blocker | READ |

## 5. Tests

```
python -m pytest JarvisAI/tests -q
```

The agent-specific files:

* `test_agent_core.py` — state machine, serialisation, store atomicity/journal,
  redaction, policy classification, planner validation, presentation helpers.
* `test_agent_runner.py` — success, retries/backoff, budgets, blocked steps,
  loop detection, cancel (before/during/after), pause/resume, deadline, crash
  resume, background worker, executor file/verify/approval paths.
* `test_agent_screen.py` — capture + coordinate mapping, caching, pause, backend
  failure, provider/OCR fallbacks, uncertainty, find/verify, computer-use
  validation, dry-run, budget, authorization, continuous observer.
* `test_agent_voice.py` — command routing, announcer throttling, security tiers,
  action discovery, service start/permissions/tool facade/voice round trip,
  settings bounds.
* `test_agent_integration.py` — real subprocess execution (`git status`, a real
  pytest run, a failing command, an unknown binary) through the real executor.
* `test_agent_ui.py` — panel rendering and controls, island rendering/expand/
  clamping, dashboard extra card, HUD minimise→island→restore, and the
  `main.py` local command router. Skipped where Qt cannot load.

## 6. Known limitations

* **Linux desktop control** uses `pyautogui` (X11 via `python-xlib`); Wayland
  sessions may refuse synthetic input. Screen *capture* works through mss’s
  portal support where the desktop provides it.
* **Accessibility lookup** is implemented for Windows (UI Automation via
  `pywinauto`), Linux (AT-SPI when `pyatspi` is installed) and macOS (AX API with
  Accessibility permission). Elsewhere the agent falls back to OCR then vision.
* **macOS** additionally needs Screen Recording permission for capture and
  Accessibility permission for control; without them the agent reports the
  blocker rather than pretending to act.
* **Code repair quality** depends on the configured planning model. The
  deterministic planner deliberately refuses to rewrite source it does not
  understand.
* Continuous observation (`ContinuousObserver`) is implemented but intentionally
  not exposed as a voice command yet; wire it from a settings toggle if needed.
* The vision provider uploads a downscaled JPEG of the selected monitor to the
  configured cloud provider — this is disclosed here and can be disabled with
  `autonomous_screen_paused` / by removing the API key.
