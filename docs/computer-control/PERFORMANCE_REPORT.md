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
| Phase 0 | +0.5 MB (app modules) | 0.0 % | lazy pool, no import-time threads |
