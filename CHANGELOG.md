# Changelog

All notable changes to JARVIS AI are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
use [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
  coming back, against the two `requirements.txt` copies drifting apart, and
  against dev-only packages leaking into the runtime dependency list.
- CI: a dedicated fast `lint` job, broader path filters (root launchers,
  packaging files, `voice/`, `scripts/`), dependency caching across both
  requirement files, and cancellation of superseded runs.

### Fixed

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

- `pyproject.toml` gained project metadata (keywords, classifiers, project URLs)
  so the package describes itself on PyPI-style indexes.
- CI installs test dependencies from `requirements-dev.txt` instead of pinning a
  bare `pytest`.

## [1.0.0] - 2025

- First tagged release of the holographic JARVIS assistant: Gemini Live voice
  loop, provider fallback, long-term memory, owner authentication, phone
  dashboard, and the plugin/action system.
