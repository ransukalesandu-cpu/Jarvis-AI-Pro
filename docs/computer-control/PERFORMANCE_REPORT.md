# Computer Control — Performance Report

Every number here was measured with `python -m jarvis.computer_control.bench baseline`
(psutil, fresh interpreter per import scenario). Target: Windows 10/11, 16 GB RAM, SSD
(owner decision 2). Numbers from the Linux CI-like sandbox are labelled as such; the
same command must be run on the owner's PC (see "Owner measurement" below).

## Phase 0 baseline — before any integration

Host: Linux x86_64 sandbox, Python 3.13, 4 CPUs, 15.7 GB RAM. Measured 2026-11-05.

| scenario | RSS before (MB) | RSS after (MB) | import (s) | idle CPU % | threads |
|---|---|---|---|---|---|
| python_bare | 14.8 | 14.8 | 0.0 | 0.0 | 1 |
| jarvis_app_modules (`import jarvis.main`, no window, no Gemini session) | 14.7 | 130.6 | 1.15 | 0.0 | 5 |
| jarvis_app_plus_engine (app modules + engine + registration) | 14.7 | 131.1 | 0.91 | 0.0 | 5 |
| engine_only | 14.7 | 18.6 | 0.04 | 0.0 | 1 |

* **Engine RAM cost on top of the app: +0.5 MB RSS** (131.1 − 130.6), no extra
  threads at import (the worker pool starts lazily on the first action).
* Engine alone: +3.9 MB over a bare interpreter.
* Idle CPU with the engine loaded: 0.0 %.
* Runner overhead (500 no-op LOW actions through flag→stop→policy→audit→pool→verify):
  p50 **0.235 ms**, p95 0.407 ms, max 10.8 ms. (CPU 96 % during that tight loop is the
  benchmark itself spinning, not idle cost.) RSS peak 22.5 MB.
* Emergency-stop latency (20 trials, action blocked in `ctx.wait`): p50 **0.67 ms**,
  p95 0.86 ms, max 5.2 ms. With a per-job `cancel_event` the worst case is bounded by
  `estop.POLL_S` = 20 ms plus the duration of the current primitive input call.

## Windows measurement (windows-latest CI runner, 2026-11-05)

Host: Windows Server 2025 (10.0.26100), Python 3.12.10, 4 CPUs, **16.0 GB RAM** — the same
RAM class as the owner's target. Recorded by the `windows-ui-smoke` job (artifact
`cc-baseline-windows`).

| scenario | RSS before (MB) | RSS after (MB) | import (s) | idle CPU % | threads |
|---|---|---|---|---|---|
| python_bare | 16.9 | 16.9 | 0.0 | 0.0 | 4 |
| jarvis_app_modules | 16.9 | 104.6 | 1.015 | 0.0 | 12 |
| jarvis_app_plus_engine | 16.9 | 105.5 | 1.035 | 0.0 | 12 |
| engine_only | 16.9 | 21.1 | 0.04 | 0.0 | 4 |
| engine_plus_uia_backend (pywinauto + comtypes) | 17.0 | 46.2 | 0.243 | 0.0 | 8 |

* Engine on top of the app modules: **+0.9 MB** RSS, 0 % idle CPU.
* The UI Automation backend costs **+25.1 MB** (46.2 − 21.1) and is imported only the first time a
  Windows control tool runs (lazy), never at startup.
* Runner overhead: p50 0.591 ms, p95 0.672 ms. Emergency-stop latency (20 trials, 0 failed):
  p50 **0.58 ms**, p95 0.63 ms, max 0.67 ms.

## Owner measurement (pending manual validation on Windows)

1. Start JARVIS normally (`Run_Jarvis.bat`), wait until it is listening.
2. Find its PID (Task Manager → Details → `python.exe`/`pythonw.exe`).
3. Run, with the JARVIS venv:

   ```
   python -m jarvis.computer_control.bench baseline --pid <PID> --seconds 60 --json before.json
   ```

4. Set `JARVIS_COMPUTER_CONTROL=1`, restart, repeat with `--json after.json`.

Also run `python -m jarvis.computer_control.bench baseline` once on Windows for the
import table. Results go into the table below.

| measurement (Windows, owner PC) | before | after | status |
|---|---|---|---|
| live app RSS avg / peak (MB) | — | — | pending manual validation by the owner |
| live app CPU avg (%) idle | — | — | pending manual validation by the owner |

## Per-project deltas

Filled in as each project merges (same commands, same host).

| project | RSS delta vs baseline | idle CPU | notes |
|---|---|---|---|
| Phase 0 | +0.5 MB Linux / +0.9 MB Windows (app modules) | 0.0 % | lazy pool, no import-time threads |
| Project 1 | +25.1 MB when the UIA backend is first used (Windows) | 0.0 % | pywinauto/comtypes lazy-imported |
| Project 2 | +4.2 MB (orchestrator import, Linux) | 0.0 % | planner calls the cloud model only when the local planner cannot |
| Project 3 | +4.2 MB (controller import, Linux); browser itself not measured | 0.0 % | Playwright and the browser start only on the first `cc_browser` call; pending manual validation by the owner |
| Project 4 | +3.7 MB (perception import, Linux) | 0.0 % | no capture, OCR or vision until asked; no local model |
| Project 5 | +5.2 MB (workflows import, Linux) | 0.0 % | store read on demand |
| Project 7 | +3.6 MB (files + MCP adapter import, Linux) | 0.0 % | adapter is listing/export only |
| Project 8 | +6.9 MB (bench suite import, Linux) | 0.0 % | only loaded by `python -m jarvis.computer_control.bench` |

## Projects 2–8 import cost (Linux dev container, 2026-11-09)

Each row is measured in a fresh interpreter (median of 3) after importing the
`jarvis.computer_control` package root. The rows overlap: each one includes the
shared contract/policy/runner modules. Host: Linux x86_64, 4 vCPU, 16 GB.

| subsystem | RSS before (MB) | RSS after (MB) | delta (MB) | import (s) | idle CPU % | threads |
|---|---|---|---|---|---|---|
| engine (tools registry, all 11 specs built) | 15.3 | 22.6 | +7.3 | 0.049 | 0.0 | 1 |
| orchestrator (plan/planner/host/jobs) | 15.3 | 19.5 | +4.2 | 0.027 | 0.0 | 1 |
| browser controller (Playwright not started) | 15.4 | 19.6 | +4.2 | 0.025 | 0.0 | 1 |
| visual perception (no capture) | 15.4 | 19.1 | +3.7 | 0.023 | 0.0 | 1 |
| workflows | 15.3 | 20.5 | +5.2 | 0.031 | 0.0 | 1 |
| files + MCP adapter | 15.3 | 18.9 | +3.6 | 0.021 | 0.0 | 1 |
| bench suite | 15.3 | 22.2 | +6.9 | 0.054 | 0.0 | 1 |

The whole engine (all 11 tools) adds **+7.3 MB and 0.05 s** to the process, starts
**no thread** and uses **no CPU while idle**. A real browser, UIA on a large window,
OCR and hosted vision cost more when they are used; those are pending manual
validation by the owner on Windows.

## Benchmark suite (Project 8)

`python -m jarvis.computer_control.bench suite`: 13 synthetic, non-destructive
scenarios on the fake desktop and fake browser, each checked against the resulting
state, not against what the agent reports. Run on the Linux dev container, 2026-11-09:

| metric | value |
|---|---|
| scenarios | 13 (13 pass) |
| task_completion_rate | 1.0 |
| verified_success_rate | 0.429 (see below) |
| failure_rate | 0.0 |
| recovery_rate | 1.0 (1 of 1) |
| avg_execution_s | 0.03 |
| tool_executions | 47 |
| cloud_requests | 0 |
| RSS start / peak / end (MB) | 22.3 / 39.4 / 39.4 |
| cancellation latency | 0.6 ms |

`verified_success_rate` is strict: among the 7 multi-step tasks that succeeded,
the share in which **every** step was independently verified. The other 4 each
contain a step that is unverified by design: typing through the keyboard,
password entry (never read back), or a dialog that is reported and not
auto-answered. These scenarios measure the engine's control logic on fakes. They
are not OSWorld/WindowsAgentArena results on real applications, which would need
local VMs (not used, owner decision 2).
