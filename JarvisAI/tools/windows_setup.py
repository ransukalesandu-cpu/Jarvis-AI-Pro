"""Setup, verification and launch logic for the Windows installer.

The batch files (`Jarvis_Setup.bat`, `Run_Jarvis.bat`) are deliberately thin:
they resolve their own folder, show a menu, and hand every decision to this
module. Batch is excellent at starting things and terrible at logic — version
comparisons, quoting and error handling all become `if errorlevel` puzzles.
Everything that can be reasoned about lives here instead, where it can be unit
tested on any OS.

What this module knows about the project (verified, not assumed):

* the app's entry point is ``JarvisAI/main.py`` and the launcher passes
  ``--hologram-hud`` so the Hologram HUD is used;
* ``JarvisAI/setup.py`` is the existing installer — it installs
  ``requirements.txt`` (OS-filtered through pip markers) and then tries to fetch
  the Playwright browsers, which is explicitly non-fatal there;
* ``pyproject.toml`` declares ``requires-python = ">=3.11"`` with classifiers for
  3.11, 3.12 and 3.13, and ``setup.py``'s ``MIN_PY``/``MAX_PY`` agree. 3.12 is
  the version the project recommends (and the one the optional SpeechBrain
  packages want), so 3.12 is preferred — never "the newest one installed";
* ``requirements-voice-id.txt`` is optional and heavy (torch/torchaudio), so it
  is offered separately and never installed silently.

Commands (used by the batch menu)::

    python tools/windows_setup.py install [--with-voice-id] [--yes]
    python tools/windows_setup.py verify [--tests] [--json]
    python tools/windows_setup.py launch
    python tools/windows_setup.py status        (exit 0 = ready to launch)

Nothing here deletes user data. A virtual environment that cannot be used is
renamed to ``.venv.broken-<timestamp>`` so it can be inspected and restored.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

__all__ = [
    "MIN_PY",
    "MAX_PY",
    "PREFERRED_PY",
    "SUPPORTED",
    "Check",
    "Interpreter",
    "SetupError",
    "backup_venv",
    "build_parser",
    "create_venv",
    "ensure_venv",
    "find_interpreters",
    "interpreter_from_path",
    "install",
    "launch",
    "main",
    "parse_py_launcher_list",
    "project_dir",
    "select_interpreter",
    "venv_python",
    "venv_problem",
    "verify",
]

# ── project facts ────────────────────────────────────────────────────────────

MIN_PY = (3, 11)          # pyproject: requires-python >= 3.11
MAX_PY = (3, 13)          # highest version with a classifier and a CI job
PREFERRED_PY = (3, 12)    # recommended by README + optional SpeechBrain packages
SUPPORTED = "3.11–3.13"

#: One flag for "this is Windows", so tests can exercise the Windows code paths
#: (the ``py`` launcher, ``Scripts/python.exe``) on any OS.
_IS_WINDOWS = os.name == "nt"

ENTRY_SCRIPT = "main.py"
ENTRY_ARGS = ("--hologram-hud",)
SETUP_SCRIPT = "setup.py"
REQUIREMENTS = "requirements.txt"
OPTIONAL_VOICE_ID = "requirements-voice-id.txt"
CONFIG_FILE = Path("config") / "api_keys.json"
LOG_DIR = Path("logs")

#: Imports that must work for the app to start at all. Each entry is
#: (label, module) — the label is what the user sees.
CORE_IMPORTS: tuple[tuple[str, str], ...] = (
    ("PyQt6 (desktop UI)", "PyQt6.QtWidgets"),
    ("numpy (hologram geometry)", "numpy"),
    ("sounddevice (audio devices)", "sounddevice"),
    ("google-genai (Gemini Live)", "google.genai"),
    ("Pillow (image encoding)", "PIL.Image"),
    ("mss (screen capture)", "mss"),
)

#: Project modules that must import for the HUD to come up.
APP_IMPORTS: tuple[tuple[str, str], ...] = (
    ("core package", "core"),
    ("memory store", "memory.memory_manager"),
    ("live audio pipeline", "core.live_audio"),
    ("hologram HUD", "ui.hud_main"),
)

#: Feature packages. The first three are listed in requirements.txt (so a normal
#: install has them) but the app imports each one inside a try/except and simply
#: disables that feature, so a missing one is a report, never an install
#: failure. The last three are *not* installed by requirements.txt at all
#: (torch/speechbrain live in requirements-voice-id.txt, openwakeword is opt-in).
OPTIONAL_IMPORTS: tuple[tuple[str, str], ...] = (
    ("web automation (playwright)", "playwright"),
    ("camera (opencv)", "cv2"),
    ("OCR bridge (pytesseract)", "pytesseract"),
    ("local Voice ID (torch)", "torch"),
    ("local Voice ID (speechbrain)", "speechbrain"),
    ("wake word (openwakeword)", "openwakeword"),
)


class SetupError(RuntimeError):
    """A step failed and the installer must stop rather than pretend success."""


@dataclass
class Check:
    """One verification result, with the three honest states."""

    name: str
    status: str          # "pass" | "fail" | "skip"
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class Interpreter:
    """A Python found on this machine: the command to run and its version."""

    command: list[str]
    version: tuple[int, int]

    def label(self) -> str:
        return "%d.%d" % self.version

    def as_dict(self) -> dict[str, object]:
        return {"command": self.command, "version": list(self.version)}


Runner = Callable[..., "subprocess.CompletedProcess"]


def _run(args: Sequence[str], *, cwd: Path | None = None, timeout: float | None = None,
         capture: bool = True) -> subprocess.CompletedProcess:
    """Default runner. Kept thin so tests can replace it entirely."""
    kwargs: dict[str, object] = {}
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    if timeout is not None:
        kwargs["timeout"] = timeout
    return subprocess.run(list(args), **kwargs)  # noqa: S603 - fixed arg lists only


# ── paths ────────────────────────────────────────────────────────────────────


def project_dir() -> Path:
    """The folder that holds main.py — ``JarvisAI/``.

    ``tools/windows_setup.py`` lives one level below it; when the module is
    imported by a test instead, the parent of ``tools`` is still correct.
    """
    return Path(__file__).resolve().parent.parent


def venv_dir(project: Path | None = None) -> Path:
    return (project or project_dir()) / ".venv"


def venv_python(project: Path | None = None) -> Path:
    """Path to the interpreter inside the project venv (Windows layout)."""
    base = venv_dir(project)
    return base / ("Scripts/python.exe" if _IS_WINDOWS else "bin/python")


# ── interpreter discovery ────────────────────────────────────────────────────


def parse_py_launcher_list(output: str) -> list[tuple[str, tuple[int, int]]]:
    """Parse ``py -0p`` output into ``[(path, (major, minor)), …]``.

    Sample line::

        -V:3.12 *        C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python312\\python.exe
    """
    found: list[tuple[str, tuple[int, int]]] = []
    for line in (output or "").splitlines():
        match = re.search(r"-V:(\d+)\.(\d+)", line)
        if not match:
            continue
        path = line.split("*")[-1].strip().strip('"') if "*" in line else line[match.end():].strip().strip('"')
        if not path:
            continue
        found.append((path, (int(match.group(1)), int(match.group(2)))))
    return found


def _version_of(command: Sequence[str], run: Runner) -> tuple[int, int] | None:
    """Ask an interpreter for its version; ``None`` when it cannot run."""
    try:
        result = run([*command, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                     timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    text = (getattr(result, "stdout", "") or "").strip().splitlines()
    if not text:
        return None
    try:
        major, minor = text[-1].strip().split(".")[:2]
        return int(major), int(minor)
    except (ValueError, IndexError):
        return None


def interpreter_from_path(path: str, run: Runner = _run) -> Interpreter:
    """Turn a user-supplied ``--python`` path into an :class:`Interpreter`.

    Nothing is installed or removed: an explicit path is respected even when it
    is outside the supported range, because the user asked for it by name. The
    version still has to be readable, otherwise the path is not usable.
    """
    version = _version_of([path], run)
    if version is None:
        raise SetupError(f"'{path}' did not answer as a Python interpreter (try `py -0p` to list them).")
    return Interpreter([path], version)


def is_supported(version: tuple[int, int] | None) -> bool:
    """True for the range the project actually declares support for."""
    return version is not None and MIN_PY <= version <= MAX_PY


def find_interpreters(run: Runner = _run) -> list[Interpreter]:
    """Every Python we can find, de-duplicated, newest-supported first.

    Sources, in order of reliability: the Windows ``py`` launcher's own list,
    then the per-version launcher flags, then plain ``python`` on PATH. The
    newest *installed* interpreter is deliberately not preferred — see
    :func:`select_interpreter`.
    """
    candidates: list[Interpreter] = []

    if _IS_WINDOWS:
        try:
            listed = run(["py", "-0p"], timeout=20)
            for path, version in parse_py_launcher_list(getattr(listed, "stdout", "") or ""):
                # The launcher can list a path that no longer runs (uninstalled or
                # moved Python), so every entry is confirmed before it is offered.
                confirmed = _version_of([path], run)
                if confirmed is not None:
                    candidates.append(Interpreter([path], confirmed))
        except (OSError, subprocess.SubprocessError):
            pass

        for minor in (12, 13, 11, 14):
            command = ["py", f"-3.{minor}"]
            version = _version_of(command, run)
            if version is not None:
                candidates.append(Interpreter(command, version))

    for command in (["python"], ["python3"], [sys.executable]):
        version = _version_of(command, run)
        if version is not None:
            candidates.append(Interpreter(command, version))

    unique: dict[tuple[int, int, str], Interpreter] = {}
    for item in candidates:
        # A version that failed to answer is not a candidate at all.
        if item.version is None:
            continue
        key = (item.version[0], item.version[1], item.command[-1].lower())
        unique.setdefault(key, item)
    return list(unique.values())


def select_interpreter(candidates: Iterable[Interpreter]) -> Interpreter | None:
    """Pick the interpreter to build the environment with.

    Order: the project's recommended version, then the supported versions from
    oldest to newest, and only then anything newer (which ``setup.py`` warns
    about but tolerates). Unsupported old versions are never chosen.
    """
    supported = [c for c in candidates if is_supported(c.version)]
    if not supported:
        newer = [c for c in candidates if c.version > MAX_PY]
        if newer:
            # Newer-than-tested is a warning in setup.py, not a wall — but only
            # when nothing supported exists.
            return sorted(newer, key=lambda c: c.version)[0]
        return None
    preferred = [c for c in supported if c.version == PREFERRED_PY]
    if preferred:
        return preferred[0]
    return sorted(supported, key=lambda c: c.version)[0]


# ── virtual environment ──────────────────────────────────────────────────────


def venv_problem(project: Path | None = None, run: Runner = _run) -> str | None:
    """Why the existing venv cannot be used, or ``None`` when it is healthy.

    A venv is only "healthy" when its interpreter runs, its version is inside
    the supported range, and pip is importable. Everything else is a reason to
    rebuild — but never to delete silently: :func:`backup_venv` moves it aside.
    """
    python = venv_python(project)
    if not python.exists():
        return "missing"
    version = _version_of([str(python)], run)
    if version is None:
        return "its interpreter does not run"
    if version < MIN_PY:
        return f"it uses Python {version[0]}.{version[1]}, older than {SUPPORTED}"
    if version > MAX_PY:
        return f"it uses Python {version[0]}.{version[1]}, newer than tested {SUPPORTED}"
    pip_ok = run([str(python), "-m", "pip", "--version"], timeout=60)
    if getattr(pip_ok, "returncode", 1) != 0:
        return "pip is broken or missing inside it"
    return None


def backup_venv(project: Path | None = None, *, now: str | None = None) -> Path | None:
    """Move a broken venv aside instead of deleting it.

    The user may have installed optional packages into it, and a half-installed
    environment is still evidence of what went wrong, so nothing is deleted.
    The new name matches ``.venv.broken-*/`` in both .gitignore files, which
    keeps it out of git while leaving it on disk for inspection.
    """
    target = venv_dir(project)
    if not target.exists():
        return None
    stamp = now or time.strftime("%Y%m%d-%H%M%S")
    destination = target.with_name(f".venv.broken-{stamp}")
    suffix = 1
    while destination.exists():
        destination = target.with_name(f".venv.broken-{stamp}-{suffix}")
        suffix += 1
    target.rename(destination)
    return destination


def create_venv(project: Path | None, interpreter: Interpreter, run: Runner = _run) -> Path:
    """Create ``.venv`` with the chosen interpreter and return its python path."""
    base = project or project_dir()
    result = run([*interpreter.command, "-m", "venv", str(venv_dir(base))], timeout=600)
    if getattr(result, "returncode", 1) != 0:
        output = (getattr(result, "stdout", "") or "").strip()
        raise SetupError(f"Creating the virtual environment failed.\n{output}")
    python = venv_python(base)
    if not python.exists():
        raise SetupError("The virtual environment was created but has no python.exe.")
    return python


def ensure_venv(
    project: Path | None = None,
    *,
    run: Runner = _run,
    interpreter: Interpreter | None = None,
    allow_recreate: bool = True,
) -> tuple[Path, list[str]]:
    """Make sure a usable venv exists. Returns (python, notes).

    The notes are what the installer prints, so a rebuilt environment never
    happens silently.
    """
    base = project or project_dir()
    notes: list[str] = []
    problem = venv_problem(base, run)

    if problem == "missing":
        notes.append("No .venv yet — creating one.")
    elif problem is not None:
        notes.append(f"The existing .venv cannot be used ({problem}).")
        if not allow_recreate:
            raise SetupError(
                f"The existing .venv cannot be used ({problem}). "
                "Run 'Install / Repair JARVIS' to rebuild it."
            )
        moved = backup_venv(base)
        if moved is not None:
            notes.append(f"It was moved to {moved.name} (nothing was deleted).")
    else:
        notes.append("Using the existing .venv.")
        return venv_python(base), notes

    chosen = interpreter or select_interpreter(find_interpreters(run))
    if chosen is None:
        raise SetupError(
            f"No supported Python ({SUPPORTED}) was found. Install Python "
            f"{PREFERRED_PY[0]}.{PREFERRED_PY[1]} from python.org (tick 'Python "
            "Launcher'), then run the installer again."
        )
    notes.append(f"Building .venv with Python {chosen.label()} ({' '.join(chosen.command)}).")
    python = create_venv(base, chosen, run)
    return python, notes


# ── dependencies ─────────────────────────────────────────────────────────────


def _which(name: str) -> str | None:
    """Shutil lookup, wrapped so tests never have to patch a global module."""
    return shutil.which(name)


def _spawn(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    """Start the app with the console attached (no capture: tracebacks belong to
    the user). Separate from the injected ``run`` used for probing."""
    return subprocess.run(list(command), cwd=str(cwd))  # noqa: S603 - fixed arg list


def _short(output: str, limit: int = 1200) -> str:
    text = (output or "").strip()
    return text if len(text) <= limit else text[:limit] + "\n…"


def pip_install(
    python: Path,
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    run: Runner = _run,
    attempts: int = 2,
    failures: list[str] | None = None,
) -> bool:
    """Run a pip command with at most ``attempts`` tries.

    A second attempt covers the common transient index/CDN failure on a flaky
    connection. It never retries a resolver conflict, because that cannot fix
    itself, and it never retries more than twice — a broken wheel must not turn
    into an infinite install loop.
    """
    command = [str(python), "-m", "pip", *args, "--disable-pip-version-check"]
    last = ""
    for attempt in range(1, max(1, attempts) + 1):
        result = run(command, cwd=cwd, timeout=3600)
        code = getattr(result, "returncode", 1)
        last = getattr(result, "stdout", "") or ""
        if code == 0:
            return True
        if failures is not None:
            failures.append(_short(last))
        lowered = last.lower()
        transient = any(
            marker in lowered
            for marker in ("connection", "timed out", "timeout", "temporary failure",
                           "ssl", "proxy", "readtimeout", "network is unreachable")
        )
        if attempt >= attempts or not transient:
            break
        print(f"   ... network problem on attempt {attempt}; retrying once.")
    print(_short(last))
    return False


def install_dependencies(
    python: Path,
    project: Path | None = None,
    *,
    run: Runner = _run,
) -> None:
    """Install everything ``JarvisAI/setup.py`` installs, via that script.

    Reusing setup.py keeps one source of truth: it already filters OS-specific
    requirements through pip markers, treats the Playwright browser download as
    non-fatal, and checks the avatar asset. Duplicating that here would drift.
    """
    base = project or project_dir()
    setup = base / SETUP_SCRIPT
    if not setup.exists():
        raise SetupError(f"{SETUP_SCRIPT} is missing from {base}.")
    result = run([str(python), str(setup)], cwd=base, timeout=5400)
    code = getattr(result, "returncode", 1)
    output = getattr(result, "stdout", "") or ""
    print(_short(output, 4000))
    if code != 0:
        raise SetupError(
            "Dependency installation failed (pip returned an error). Nothing was "
            "launched. Scroll up for the first pip error — it names the package."
        )


def install_optional_voice_id(python: Path, project: Path | None = None,
                              *, run: Runner = _run) -> bool:
    """Install the optional local Voice ID stack. Never fatal."""
    base = project or project_dir()
    manifest = base / OPTIONAL_VOICE_ID
    if not manifest.exists():
        print(f"   {OPTIONAL_VOICE_ID} is not present; skipping.")
        return False
    print("   Installing optional Voice ID packages (torch is large; this can take a while).")
    ok = pip_install(python, ["install", "-r", str(manifest)], cwd=base, run=run)
    if not ok:
        print("   [!] Optional Voice ID packages did not install. The app still works;")
        print("       Voice ID will report itself unavailable until they are installed.")
    return ok


# ── verification ─────────────────────────────────────────────────────────────


def _import_check(python: Path, module: str, *, cwd: Path, run: Runner) -> tuple[bool, str]:
    result = run([str(python), "-c", f"import {module}"], cwd=cwd, timeout=180)
    if getattr(result, "returncode", 1) == 0:
        return True, ""
    output = getattr(result, "stdout", "") or ""
    last = [line for line in output.strip().splitlines() if line.strip()]
    return False, _short(last[-1] if last else "import failed", 240)


def _required_imports_ok(python: Path, project: Path, run: Runner) -> bool:
    """True when every startup-critical import already works in this venv."""
    return all(_import_check(python, module, cwd=project, run=run)[0]
               for _label, module in CORE_IMPORTS)


def _config_summary(project: Path) -> tuple[bool, str]:
    """Report which configuration exists — never the values."""
    path = project / CONFIG_FILE
    if not path.exists():
        return False, f"{CONFIG_FILE.as_posix()} is missing (the app asks for keys on first launch)"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"{CONFIG_FILE.as_posix()} is not readable JSON ({type(exc).__name__})"
    if not isinstance(data, dict):
        return False, f"{CONFIG_FILE.as_posix()} does not contain an object"
    gemini = data.get("gemini_api_key") or data.get("gemini")
    has_gemini = isinstance(gemini, str) and bool(gemini.strip())
    others = sum(
        1 for key in ("openai_api_key", "anthropic_api_key", "groq_api_key", "supabase_url")
        if isinstance(data.get(key), str) and data.get(key, "").strip()
    )
    if has_gemini:
        return True, f"Gemini key present; {others} other provider/cloud setting(s) configured"
    return False, (
        "no Gemini key yet — Live voice needs one (set it in the app's setup screen "
        "or ⚙ → API KEYS). No secret values are printed here."
    )


def verify(
    project: Path | None = None,
    *,
    run: Runner = _run,
    run_tests: bool = False,
) -> list[Check]:
    """Check the installation as far as is possible without the app's services.

    Deliberately more than ``pip check``: a missing module or a broken entry
    point passes pip and fails the user, so each is tested directly.
    """
    base = project or project_dir()
    checks: list[Check] = []

    # 1. interpreter + venv
    python = venv_python(base)
    problem = venv_problem(base, run)
    if problem is None:
        version = _version_of([str(python)], run)
        checks.append(Check("Interpreter", "pass",
                            f"Python {version[0]}.{version[1]} in .venv" if version else ".venv"))
    elif problem == "missing":
        checks.append(Check("Interpreter", "fail", "no .venv — run Install / Repair first"))
    else:
        checks.append(Check("Interpreter", "fail", problem))

    if problem is not None:
        # Everything below needs a working interpreter; report rather than lie.
        checks.append(Check("Dependencies", "skip", "no usable .venv"))
        checks.append(Check("Application imports", "skip", "no usable .venv"))
        checks.append(Check("Entry point", "pass" if (base / ENTRY_SCRIPT).exists() else "fail",
                            ENTRY_SCRIPT))
        ok, detail = _config_summary(base)
        checks.append(Check("Configuration", "pass" if ok else "skip", detail))
        return checks

    # 2. dependency consistency
    pip_check = run([str(python), "-m", "pip", "check"], cwd=base, timeout=300)
    if getattr(pip_check, "returncode", 1) == 0:
        checks.append(Check("Dependencies", "pass", "pip check: no broken requirements"))
    else:
        checks.append(Check("Dependencies", "fail",
                            _short(getattr(pip_check, "stdout", "") or "pip check failed", 300)))

    # 3. required imports
    missing: list[str] = []
    for label, module in CORE_IMPORTS:
        ok, detail = _import_check(python, module, cwd=base, run=run)
        if not ok:
            missing.append(f"{label}: {detail or 'missing'}")
    checks.append(
        Check("Required packages", "fail" if missing else "pass",
              "; ".join(missing) if missing else f"{len(CORE_IMPORTS)} imports OK")
    )

    # 4. the app's own modules — a package can import and the app still fail
    app_missing: list[str] = []
    for label, module in APP_IMPORTS:
        ok, detail = _import_check(python, module, cwd=base, run=run)
        if not ok:
            app_missing.append(f"{label}: {detail or 'import failed'}")
    checks.append(
        Check("Application imports", "fail" if app_missing else "pass",
              "; ".join(app_missing) if app_missing else f"{len(APP_IMPORTS)} modules OK")
    )

    # 5. entry point present and syntactically valid
    entry = base / ENTRY_SCRIPT
    if not entry.exists():
        checks.append(Check("Entry point", "fail", f"{ENTRY_SCRIPT} is missing"))
    else:
        compiled = run([str(python), "-m", "py_compile", str(entry)], cwd=base, timeout=120)
        checks.append(Check("Entry point",
                            "pass" if getattr(compiled, "returncode", 1) == 0 else "fail",
                            f"{ENTRY_SCRIPT} compiles" if getattr(compiled, "returncode", 1) == 0
                            else _short(getattr(compiled, "stdout", "") or "does not compile")))

    # 6. configuration presence (never the values)
    ok, detail = _config_summary(base)
    checks.append(Check("Configuration", "pass" if ok else "skip", detail))

    # 7. optional features
    unavailable: list[str] = []
    available: list[str] = []
    for label, module in OPTIONAL_IMPORTS:
        ok, _detail = _import_check(python, module, cwd=base, run=run)
        (available if ok else unavailable).append(label)
    if "OCR bridge (pytesseract)" in available and _which("tesseract") is None:
        # The Python package is only a bridge; without the engine OCR still fails.
        available.remove("OCR bridge (pytesseract)")
        unavailable.append("OCR bridge (pytesseract installed, but the Tesseract engine "
                           "is not on PATH)")
    checks.append(Check("Optional features", "pass" if available else "skip",
                        (("available: " + ", ".join(available) +
                          ("; unavailable: " + ", ".join(unavailable) if unavailable else ""))
                         if available else
                         "none installed — this is allowed"
                         + (" (missing: " + ", ".join(unavailable) + ")" if unavailable else ""))))

    # 8. project tests (opt-in; they need the dev requirements)
    if run_tests:
        pytest_ok = run([str(python), "-m", "pytest", "--version"], cwd=base, timeout=120)
        if getattr(pytest_ok, "returncode", 1) != 0:
            checks.append(Check("Project tests", "skip", "pytest is not installed in .venv"))
        else:
            tests = run([str(python), "-m", "pytest", "-q", "tests/test_project_health.py"],
                        cwd=base, timeout=1800)
            checks.append(Check("Project tests",
                                "pass" if getattr(tests, "returncode", 1) == 0 else "fail",
                                "fast health subset" if getattr(tests, "returncode", 1) == 0
                                else _short(getattr(tests, "stdout", "") or "tests failed", 400)))
    else:
        checks.append(Check("Project tests", "skip", "not requested (use --tests)"))

    # 9. things only the user can confirm
    checks.append(Check("Gemini Live / Supabase", "skip",
                        "needs network, real keys and a microphone — not testable here"))
    return checks


def format_checks(checks: Sequence[Check]) -> str:
    icons = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}
    lines = ["", "  Verification", "  " + "-" * 58]
    for check in checks:
        lines.append(f"  [{icons.get(check.status, check.status)}] {check.name}"
                     f"{(' — ' + check.detail) if check.detail else ''}")
    failed = sum(1 for c in checks if c.status == "fail")
    skipped = sum(1 for c in checks if c.status == "skip")
    lines.append("  " + "-" * 58)
    lines.append(f"  {sum(1 for c in checks if c.passed)} passed, {failed} failed, {skipped} skipped")
    return "\n".join(lines)


# ── commands ─────────────────────────────────────────────────────────────────


def install(
    project: Path | None = None,
    *,
    run: Runner = _run,
    interpreter: Interpreter | None = None,
    with_voice_id: bool = False,
    run_tests: bool = False,
    force: bool = False,
) -> int:
    """Install or repair: venv → pip → dependencies → verify.

    Repair means "make it work again", never "start over": an existing healthy
    ``.venv`` is reused, and when its dependencies already import there is
    nothing to download, so the pip step is skipped (``force=True`` overrides
    that for the case where a package is present but the wrong version).
    """
    base = project or project_dir()
    print(f"  Project folder : {base}")
    print(f"  Supported Python: {SUPPORTED} (recommended "
          f"{PREFERRED_PY[0]}.{PREFERRED_PY[1]})\n")

    python, notes = ensure_venv(base, run=run, interpreter=interpreter)
    for note in notes:
        print(f"  - {note}")
    reused = any(note.startswith("Using the existing .venv") for note in notes)

    if reused and not force and _required_imports_ok(python, base, run):
        print("\n  Dependencies already satisfied in .venv - skipping pip.")
    else:
        print("\n  Upgrading pip (inside .venv only)...")
        if not pip_install(python, ["install", "--upgrade", "pip", "setuptools", "wheel"],
                           cwd=base, run=run):
            raise SetupError(
                "Could not upgrade pip. Check the internet connection or the proxy "
                "settings, then run Install / Repair again."
            )

        print("\n  Installing JARVIS dependencies (this can take several minutes)...")
        install_dependencies(python, base, run=run)

    if with_voice_id:
        install_optional_voice_id(python, base, run=run)

    checks = verify(base, run=run, run_tests=run_tests)
    print(format_checks(checks))
    failures = [c for c in checks if c.status == "fail"]
    if failures:
        print("\n  [X] Installation finished but verification failed. Do not launch yet.")
        return 1
    print("\n  [OK] Environment ready. Choose 'Launch JARVIS' (or run Run_Jarvis.bat).")
    return 0


def launch(
    project: Path | None = None,
    *,
    run: Runner = _run,
    extra_args: Sequence[str] = (),
    capture: bool = False,
    spawn: Callable[[Sequence[str], Path], object] | None = None,
) -> int:
    """Start the real entry point and propagate its exit code.

    Uses ``.venv``'s interpreter explicitly (no activation dance), the correct
    working directory, and the same ``--hologram-hud`` flag the old launcher
    passed. Output is inherited so the user sees Python's traceback in this
    window; that is the "useful startup diagnostics" case, not a silent crash.
    """
    base = project or project_dir()
    python = venv_python(base)
    problem = venv_problem(base, run)
    if problem is not None:
        print("  [X] JARVIS is not ready to launch:")
        print(f"     {problem}")
        print("     Choose 'Install / Repair JARVIS' first.")
        return 2

    entry = base / ENTRY_SCRIPT
    if not entry.exists():
        print(f"  [X] {ENTRY_SCRIPT} was not found in {base}.")
        print("     Extract the whole archive; Run_Jarvis.bat and main.py must stay side by side.")
        return 2

    command = [str(python), str(entry), *ENTRY_ARGS, *extra_args]
    print("  Launching: " + " ".join(f'"{part}"' if " " in part else part for part in command))
    print("  Keep this window open while JARVIS runs.\n")
    if capture:
        result = run(command, cwd=base)
        return int(getattr(result, "returncode", 1))
    # No capture: stdout/stderr belong to the user's console, tracebacks included.
    start = spawn or _spawn
    try:
        completed = start(command, base)
    except OSError as exc:
        print(f"  [X] Could not start Python: {exc}")
        return 2
    return int(completed.returncode)


def _configure_console() -> None:
    """Never crash on a project path that the console encoding cannot represent."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):  # detached console / closed pipe
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    project = Path(args.project).resolve() if args.project else project_dir()

    try:
        if args.command == "install":
            chosen = interpreter_from_path(args.python) if args.python else None
            return install(project, interpreter=chosen, with_voice_id=args.with_voice_id,
                           run_tests=args.tests, force=args.force)
        if args.command == "verify":
            checks = verify(project, run_tests=args.tests)
            if args.json:
                print(json.dumps([c.as_dict() for c in checks], indent=2))
            else:
                print(format_checks(checks))
            return 0 if not any(c.status == "fail" for c in checks) else 1
        if args.command == "launch":
            return launch(project)
        if args.command == "status":
            problem = venv_problem(project)
            if problem is None:
                print("ready")
                return 0
            print(problem)
            return 1
        if args.command == "interpreters":
            for item in find_interpreters():
                print(f"{item.label():>4}  {' '.join(item.command)}")
            chosen = select_interpreter(find_interpreters())
            print("selected:", f"{chosen.label()} ({' '.join(chosen.command)})" if chosen else "none")
            return 0 if chosen else 1
    except SetupError as exc:
        print(f"\n  [X] {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        return 130
    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="windows_setup.py",
        description="Install, verify and launch JARVIS AI on Windows.",
    )
    parser.add_argument("--project", help="project folder to operate on (default: the folder above tools/)")
    sub = parser.add_subparsers(dest="command", required=True)

    install_parser = sub.add_parser("install", help="install or repair the environment")
    install_parser.add_argument("--with-voice-id", action="store_true",
                                help="also install the optional local Voice ID packages (large)")
    install_parser.add_argument("--python", metavar="PATH",
                                help="build .venv with this interpreter instead of auto-selecting")
    install_parser.add_argument("--force", action="store_true",
                                help="reinstall dependencies even when the existing .venv already works")
    install_parser.add_argument("--yes", action="store_true",
                                help="accepted for scripted use; no prompts are issued here")
    install_parser.add_argument("--tests", action="store_true",
                                help="run the fast health test subset at the end")

    verify_parser = sub.add_parser("verify", help="check the installation")
    verify_parser.add_argument("--tests", action="store_true", help="also run the fast health tests")
    verify_parser.add_argument("--json", action="store_true", help="machine-readable output")

    sub.add_parser("launch", help="start JARVIS with the project .venv")
    sub.add_parser("status", help="exit 0 when .venv is ready to launch")
    sub.add_parser("interpreters", help="list the Python interpreters found")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
