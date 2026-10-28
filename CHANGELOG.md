# Changelog

All notable changes to JARVIS AI are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
use [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Autonomous task engine** (`JarvisAI/agent/`): validated planning (model or
  deterministic), bounded execution with retries/backoff/deadlines/loop
  detection, resumable JSON persistence plus an fsynced journal, pause/resume/
  cancel, and a final report. New `autonomous_task` voice tool (NON_BLOCKING),
  per-step risk classification, and approval through the existing confirmation
  gate.
- **Screen vision and computer use**: on-demand capture with coordinate mapping
  and buffer release, local OCR, Gemini/OpenAI vision with explicit uncertainty,
  accessibility-tree lookup, and validated named-target desktop actions with
  dry-run and post-action re-observation.
- **UI**: live autonomous-task card on the Bento dashboard, HUD menu/rail entry
  with an always-available STOP, and a compact Dynamic-Island status widget shown
  when the HUD is minimised. The hologram home screen is unchanged.
- `docs/AUTONOMOUS_AGENT.md` — configuration, security model, step kinds,
  tests and known limitations.
- Six new test modules (`test_agent_core/runner/screen/voice/integration/ui.py`)
  covering state transitions, persistence/resume, retries and budgets,
  cancellation, policy boundaries, vision/OCR fallbacks, computer-use validation,
  voice routing and the Qt surfaces.
- `docs/DEVELOPMENT.md` — setup, test, lint and CI workflow for contributors,
  including the current lint-debt table and a ratchet plan.
- `requirements-dev.txt` — test/lint tooling separated from the runtime
  dependency set, so a user install never pulls pytest or ruff.
- `JarvisAI/conftest.py` — one place that puts the app's roots on `sys.path`, so
  the test suite runs from any working directory, plus graceful skipping of the
  four GUI test modules when Qt's system libraries (`libGL`, `libEGL`) are not
  installed.
- `pyproject.toml` — pytest configuration (test paths, markers), ruff
  configuration (the CI lint gate) and coverage configuration, so all tooling
  reads one file.
- `.pre-commit-config.yaml`, `.editorconfig`, `.gitattributes` — consistent
  whitespace, line endings and YAML/TOML/JSON validity before a commit lands,
  with Windows `.bat` files kept on CRLF.
- `tests/test_project_health.py` — guards against the `config` import collision
  coming back, against the two `requirements.txt` copies drifting apart, against
  dev-only packages leaking into the runtime dependency list, and (new) walks
  the internal import graph so a name removed from one module cannot silently
  break an importer.
- `tests/test_ui_import_smoke.py` — imports every `JarvisAI/ui/` module once
  (skipped where Qt cannot load) so a broken panel import fails CI.
- `memory.prospective_memory.pending_intentions()` — active intentions ordered
  soonest-first, for the scheduler panel and any future planner UI.
- CI: a dedicated fast `lint` job, broader path filters (root launchers,
  packaging files, `voice/`, `scripts/`), dependency caching across both
  requirement files, and cancellation of superseded runs.

### Fixed

- **Memory panel always showed zero facts.** `MemoryPanel.fetch_real_memory_state()`
  imported `get_memory_manager` and called `get_all_facts()` — neither exists in
  `memory.memory_manager` — inside a bare `try/except`, so the counters stayed at
  zero and nothing reported an error. It now uses `all_entries_for_ui()`.
- **Scheduler panel always showed "No upcoming tasks".** Same pattern:
  `ProspectiveMemory().get_pending_tasks()` was never a real API. A real
  `pending_intentions()` helper was added to `memory/prospective_memory.py`
  (active intentions, soonest time trigger first) and the panel now uses it.
- 110 dead, duplicate or stale imports removed across the app (`ruff F401`/
  `F811`), including an availability-probe block in `open_app.py` and
  `youtube_video.py` that imported `psutil`, `pyautogui` and `numpy` and then
  never read the flag it set.

- **Crash when `config` was resolved to OpenCV's module.** Three action modules
  (`flight_finder`, `game_updater`, `youtube_video`) imported their OS helpers
  from the generic top-level `config` package. `opencv-python` ships its own
  `cv2/config.py` and leaks the `cv2` directory onto `sys.path` while it loads —
  including when its native module fails to load. Once that happened, those
  modules raised `NameError: name 'LOADER_DIR' is not defined` and the app died
  on a message that pointed nowhere near the cause. The helpers now live in
  `core/host_env.py`, which no third-party wheel claims;
  `config/__init__.py` re-exports them so existing extensions keep working.
- **`NameError` in the playback fallback path.** `core/audio_playback.py` called
  `_output_write_is_unpaced()` without importing it, so the "endpoint is not
  pacing audio" recovery branch could crash instead of switching speakers. This
  is the first bug the new ruff gate would have caught.
- Test collection aborted entirely on Linux machines without `libGL`, hiding
  ~400 passing tests. Those four modules are now excluded with a notice in the
  pytest header, and the camera-failure test skips with an explanatory reason
  once OpenCV cannot load.

### Changed

- The lint gate now also enforces `F401` (unused import) and `F811` (shadowed
  redefinition) — zero findings across the codebase, with the three intentional
  re-exports marked `# noqa: F401` and explained in place.
- New `tests/test_ui_import_smoke.py` imports every UI module (skipped where Qt
  cannot load) so a broken import in a panel fails CI rather than a user's
  window. It runs in the Windows smoke job.
- `tests/test_project_health.py` gained a static import-graph check: every
  `from <internal module> import <name>` must resolve to something that module
  actually defines. It immediately found the two dead panel APIs above.
- CI's Ubuntu job installs `libgl1` alongside `libegl1`, so the Qt tests run
  there instead of being skipped.

- `pyproject.toml` gained project metadata (keywords, classifiers, project URLs)
  so the package describes itself on PyPI-style indexes.
- CI installs test dependencies from `requirements-dev.txt` instead of pinning a
  bare `pytest`.

## [1.0.0] - 2025

- First tagged release of the holographic JARVIS assistant: Gemini Live voice
  loop, provider fallback, long-term memory, owner authentication, phone
  dashboard, and the plugin/action system.
