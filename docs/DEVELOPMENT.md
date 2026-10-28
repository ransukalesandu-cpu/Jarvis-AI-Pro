# Developing JARVIS AI

Everything a contributor needs to change the code with confidence: how to set up
a working environment, what the test suite covers, which checks run in CI, and
the conventions the codebase follows.

---

## 1. Set up a development environment

JARVIS needs **Python 3.11 or newer** (3.12 is what CI runs).

```bash
git clone https://github.com/ransukalesandu-cpu/Jarvis-AI-Pro.git
cd Jarvis-AI-Pro

python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` is everything needed to *run* JARVIS and is what end users
install. `requirements-dev.txt` adds the tools you need while *working on* it
(pytest, coverage, ruff, pre-commit) and is never pulled into a user install.

> **Linux desktop users:** PyQt6 needs `libgl1` and `libegl1`
> (`sudo apt-get install libgl1 libegl1 libportaudio2`). Without them, importing
> PyQt6 fails with `libGL.so.1: cannot open shared object file`. The test suite
> detects this and skips the four GUI modules instead of failing collection, but
> the app itself will not start.

Install the git hooks once per clone:

```bash
pre-commit install
```

Then launch the app the same way a user would:

```bash
python main.py
```

On Windows the supported path is the setup BAT: `JarvisAI\Jarvis_Setup.bat`
(menu: Install / Repair, Verify, Launch, Exit) wraps
`JarvisAI/tools/windows_setup.py`, which is where the logic lives and where it is
tested (`tests/test_windows_setup.py`). The same commands work by hand:

```bat
py -3.12 JarvisAI\tools\windows_setup.py interpreters
py -3.12 JarvisAI\tools\windows_setup.py install --yes
py -3.12 JarvisAI\tools\windows_setup.py verify --json
py -3.12 JarvisAI\tools\windows_setup.py launch
```

The batch files are kept deliberately thin so no decision depends on
`if errorlevel` branching; `tests/test_launchers.py` asserts that they resolve
their own folder, never delete `.venv`, and never embed a credential.

---

## 2. Running the tests

```bash
python -m pytest                 # whole suite, from the repository root
python -m pytest JarvisAI/tests/test_brain_engine.py   # one file
python -m pytest -k memory       # by name
```

The suite is importable from **any** working directory. That is arranged once in
`JarvisAI/conftest.py`, which puts `JarvisAI/`, the repository root and `voice/`
on `sys.path` — test files no longer need their own `sys.path` tweaks.

Notes:

* `JarvisAI/conftest.py` skips the GUI modules (`test_avatar`,
  `test_bihansa_integration`, `test_pr68_fixes`, `test_ui_hologram`) when Qt
  cannot load, and says so in the header line. On a desktop or in CI they run.
* `QT_QPA_PLATFORM=offscreen` is what the Windows CI job uses and is handy
  locally in a headless shell (e.g. WSL or over SSH).
* Tests must not need network access, an API key, a microphone, or a real
  camera. Patch the hardware and HTTP boundaries; `tests/test_security_end_to_end.py`
  and `tests/test_audio_playback.py` are good models.

Two tests guard the codebase's *shape* rather than a feature:

* `tests/test_project_health.py` walks the internal import graph statically and
  fails if a module imports a name its target no longer defines — the failure
  mode that cleanup commits create and that only shows up at runtime, often on a
  screen nobody tests.
* `tests/test_ui_import_smoke.py` imports every module in `JarvisAI/ui/` once
  (skipped where Qt cannot load), which is the only coverage the panels and
  dashboards get.

Coverage (optional):

```bash
python -m pip install -r requirements-dev.txt
python -m pytest --cov --cov-report=term-missing
```

---

## 3. Linting

```bash
ruff check JarvisAI          # the CI gate
ruff check --fix JarvisAI    # apply safe fixes
```

The gate in `[tool.ruff.lint]` (pyproject.toml) is a **ratchet**: it enforces the
rules that catch real runtime breakage — undefined names, unused imports,
shadowed redefinitions, invalid comparisons, broken `__all__` entries — and is
kept at zero findings. Every rule in it has already paid for itself:

* `F821` caught a `NameError` in `core/audio_playback.py`
  (`_output_write_is_unpaced` was called but never imported).
* `F401`/`F811` found 110 dead or stale imports, including two UI panels that
  called memory APIs that no longer exist (`get_memory_manager()`,
  `ProspectiveMemory()`) inside bare `try/except` blocks — so the memory and
  scheduler panels had been showing zeroes and "No upcoming tasks" for everyone.
* `S110`/`S112` (silent `except: pass` / `except: continue`) forced every one of
  the 202 swallowed-error sites through `core.failsoft.suppress()`, which is how
  the playback loop's broken viseme path was found (see below).

Wider families are not enabled yet. Current debt, for whoever picks up the next
ratchet step:

| Rule family | Findings | Why it is not on yet |
| --- | --- | --- |
| `BLE001` blind-except | ~770 | Broad `except Exception` is *intentional* here — optional features must fail soft. The rule cannot tell "failed, did the right thing" from "failed and hid a bug", so the work is per-site review, not a mass edit. New code should still narrow to the exception it actually expects. |
| `I001` import sorting | ~180 | Pure churn across 150+ files; do it as one isolated commit. |
| `UP`, `RUF`, `SIM` | ~250 | Mostly cosmetic modernisation (`X | None`, `datetime.UTC`). Safe but noisy. |

Turn on **one** family per pull request, fix or `noqa` it with a reason, and
update this table in the same commit.

When a name is imported only for its side effect (a re-export, a probe, or
`import main` in a test that is testing import-time setup) keep it and add
`# noqa: F401` **with a comment saying why**. Three such cases exist today:
`main.py` re-exports two `core.live_audio` helpers that tests import from
`main`, `core/security.py` re-exports `FULL_ACCESS_MODE`, and
`tests/test_launchers.py` imports `main` to trigger `sys.path` setup.

---

## 4. What CI runs

`.github/workflows/python-checks.yml`:

1. **lint** — `ruff check JarvisAI` on Python 3.12. Seconds, no dependencies.
2. **checks** — installs the runtime requirements plus the Qt system libraries,
   `compileall`, runs `diagnose.py` in CI mode, then the full `pytest` suite
   (including the UI import smoke test); also type-checks and tests the Deno
   Supabase function when it changed.
3. **windows-ui-smoke** — installs the Windows-only extras and runs the
   launch/hologram/auth/audio tests on `windows-latest`. This is the only job
   that can catch Windows-specific regressions in Qt, `pycaw`, `winrt`, or
   `comtypes`.

Everything must be green before a pull request is merged. The workflow also
cancels superseded runs on the same branch, so pushing twice in a minute does
not queue two identical test runs.

---

## 5. Project layout

```
main.py                  thin launcher: puts the roots on sys.path, calls JarvisAI/main.py
run.py / setup.py        one-time setup: OS-filtered pip install + Playwright browsers
voice/                   persona definitions loaded by the TTS layer
JarvisAI/
  main.py                the application: window, event loop, live session wiring
  core/                  engine room: LLM providers, Live API, audio, memory, security
  actions/               one file per capability the assistant can invoke
  memory/                episodic / semantic / procedural / prospective memory
  security/              owner PIN, face + voice auth, lockdown, device identity
  dashboard/             FastAPI server + static UI for phone control
  plugins/               heavier integrations (Gmail, Calendar, MCP hub, MQTT)
  services/              device bridges (ADB phone control, radar)
  tests/                 pytest suite
  conftest.py            sys.path setup + GUI skip logic
docs/                    design notes for individual subsystems
supabase/                Deno edge function + migrations for personal memory
```

Two rules that keep this layout honest:

* **Imports are top-level-flat on purpose** (`from core.x import y`,
  `from actions.x import y`) because `JarvisAI/` is on `sys.path`. That is why
  generic top-level module names are risky: see the `config` note below.
* **Nothing at import time may touch the network, the microphone, the camera or
  the filesystem outside the repo.** Tests import almost every module; a module
  that opens a device on import breaks the suite on a machine without it.

### Failing soft without failing silently

JARVIS must keep running when an optional dependency, device or network call
fails. The old idiom was:

```python
try:
    do_something_optional()
except Exception:
    pass          # ← nothing recorded, ever
```

Two shipped bugs hid behind exactly this: the memory and scheduler panels called
APIs that did not exist, swallowed the error, and showed zeroes forever. The
approved replacement is `core.failsoft.suppress()`:

```python
try:
    do_something_optional()
except Exception:
    failsoft.suppress("core.audio_playback:probe_device")
```

It changes no control flow, can never raise, and records the failure in a bounded
in-memory table (repeats are counted, not duplicated). Name the feature as
`"<module>:<operation>"` using a **literal** string — it is the grouping key.

Decide like this:

| Situation | What to do |
| --- | --- |
| Expected and boring (device absent, file missing, optional package not installed) | `failsoft.suppress("...")` |
| Feature still works degraded | log a warning, then `failsoft.suppress("...")` |
| The user must know (auth failure, destructive action refused) | do not swallow; propagate or surface it in the UI |

To see what is being swallowed right now:

```bash
JARVIS_FAILSOFT_REPORT=1 python -m pytest -q    # summary after the test run
JARVIS_FAILSOFT_LOG=1 python main.py            # WARNING line per suppression
```

```python
from core import failsoft
print(failsoft.report())     # sorted by frequency, with file:line of the handler
```

A suppression that appears hundreds of times, or with an `AttributeError` /
`ImportError` rather than an `OSError`, is usually a real bug — that is the
signal that would have caught both panel bugs on day one.

`ruff` enforces the idiom: `S110` and `S112` fail the build if a new bare
`pass`/`continue` handler appears.

### The `config` naming trap

`JarvisAI/config/` is a package *and* a data directory. Its name is also claimed
by `opencv-python`, which ships `cv2/config.py` and leaks its directory onto
`sys.path` while `cv2` imports. When that happens first, `from config import
is_windows` executes OpenCV's loader and the app dies with
`NameError: name 'LOADER_DIR' is not defined`.

The OS/key helpers therefore live in **`core/host_env.py`**, and new code must
import from there. `config/__init__.py` re-exports them for extensions written
against the old path, but that path is best-effort — treat `config` as a data
directory, not an API. `tests/test_project_health.py` fails if a first-party
module starts importing the bare `config` package again.

---

## 6. Conventions

* **Fail soft, report loudly.** A missing optional dependency disables one
  feature and prints why; it never crashes the app. Keep new integrations inside
  `try/except ImportError` at the point of use, and never leave a bare `pass` in
  a handler — route it through `core.failsoft.suppress()` so the failure is
  recorded (see § 5).
* **Patch surfaces, not internals.** Tests should fake `sounddevice`,
  `cv2.VideoCapture`, `requests.post` and the provider clients rather than
  reaching into module globals.
* **Secrets never land in git.** `config/api_keys.json`, `.env`, biometric
  embeddings, vaults and databases are git-ignored. `SECURITY.md` describes the
  threat model; read it before touching `JarvisAI/security/`.
* **Type hints where they help.** Public helpers in `core/` are annotated.
  Private helpers may stay unannotated rather than being annotated `Any`.
* **Changelog.** User-visible changes get an entry in `CHANGELOG.md` under
  `Unreleased`.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `ImportError: libGL.so.1` | Install `libgl1 libegl1`. GUI tests are skipped automatically. |
| `PortAudio library not found` | Install `libportaudio2`, then re-run. |
| `python -m pytest` collects nothing | You are outside the repo, or `testpaths` cannot resolve. Run from the repo root. |
| `pytest: error: unrecognized arguments: --cov` | `pytest-cov` is missing: `pip install -r requirements-dev.txt`. |
| ruff reports `F821 undefined name` | The CI gate found a genuine missing import — fix it, do not add `noqa`. |
| Tests pass locally, fail on Windows CI | A path, `pkill`-style assumption, or `\` separator leaked in. Guard with `core/host_env.is_windows()`. |
| `Jarvis_Setup.bat` says *No supported Python (3.11 - 3.13) was found* | Python is missing, is older than 3.11, or the `py` launcher is not installed. Run `py -0p` to list installed versions; install 3.12 from python.org (tick *Python Launcher*), or pass an interpreter explicitly: `python tools\windows_setup.py install --python "C:\Python312\python.exe"`. |
| `.venv` was renamed to `.venv.broken-<timestamp>` | Its Python was outside 3.11–3.13, or pip inside it was broken. Nothing was deleted: rename it back after installing a supported Python if you need the packages in it. |
| `pip` fails with `ConnectionError`, `ReadTimeoutError` or `SSL` errors | Network/proxy/index problem, not a JARVIS problem. The installer retries once automatically; check the proxy (`pip config list`) and run **Install / Repair** again. |
| `ERROR: ResolutionImpossible` / conflicting dependencies | Usually a leftover package pinned by hand inside `.venv`. The installer never guesses: inspect with `python -m pip check`, or move `.venv` aside (`Install / Repair` does this for you) and reinstall. |
| `Could not build wheels for ...` | That package has no wheel for your Python version. Stay on 3.11–3.13 (`tools\windows_setup.py interpreters` shows what is installed). |
| Installer says *Dependencies already satisfied in .venv - skipping pip* | Not an error: verification already proved every startup import works. Use `install --force` if you really want pip to run again. |
| JARVIS starts, then closes instantly | Launch it from `Run_Jarvis.bat` or `Jarvis_Setup.bat` → **3** so the console stays open with Python's traceback. The batch files never hide the exit code. |
| Verify passes but voice / Supabase do not work | Verification only proves packages and files. Keys, microphone, network and Supabase are external services — **Verify** reports them as `SKIP` (needs network / real keys), never as passed. |
