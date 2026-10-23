"""
Voice-controlled JARVIS Auto Repair.
Safe by default: "open" and "diagnose" are read-only. "repair" only reinstalls
the project's declared Python dependencies and only on a supported 64-bit
Python version; it never edits source files or runs generated code.
"""
from __future__ import annotations

import importlib.util
import platform
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"

# Module name -> pip package name. Keep this list limited to startup-critical
# dependencies; optional plugins are intentionally not treated as fatal.
_CRITICAL_MODULES = {
    "PyQt6": "PyQt6",
    "numpy": "numpy",
    "sounddevice": "sounddevice",
    "google.genai": "google-genai",
    "psutil": "psutil",
    "mss": "mss",
}


def _module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _diagnose() -> str:
    lines = [
        "JARVIS AUTO REPAIR — DIAGNOSTICS",
        "=" * 36,
        f"Project: {ROOT}",
        f"OS: {platform.platform()}",
        f"Python: {sys.version.split()[0]} ({struct.calcsize('P') * 8}-bit)",
        "",
        "STARTUP DEPENDENCIES",
    ]
    missing = []
    for module, package in _CRITICAL_MODULES.items():
        ok = _module_exists(module)
        lines.append(f"[{'OK' if ok else 'MISSING'}] {module}" +
                     ("" if ok else f" — pip package: {package}"))
        if not ok:
            missing.append(package)

    lines += ["", "PROJECT FILES"]
    for rel in ("main.py", "requirements.txt", "core/action_loader.py"):
        exists = (ROOT / rel).is_file()
        lines.append(f"[{'OK' if exists else 'MISSING'}] {rel}")

    # Parse source without importing or executing it. This is read-only and
    # avoids creating __pycache__ files.
    checked = 0
    syntax_errors = []
    excluded = {".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist"}
    try:
        for path in ROOT.rglob("*.py"):
            if any(part in excluded for part in path.parts):
                continue
            try:
                source = path.read_text(encoding="utf-8-sig")
                compile(source, str(path), "exec")
                checked += 1
            except UnicodeDecodeError:
                continue
            except SyntaxError as exc:
                syntax_errors.append(
                    f"{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}"
                )
            except OSError as exc:
                lines.append(f"[WARN] Could not read {path.name}: {exc}")
            if checked + len(syntax_errors) >= 2500:
                lines.append("[INFO] Source scan capped at 2,500 Python files.")
                break
    except OSError as exc:
        lines.append(f"[WARN] Source scan could not finish: {exc}")

    lines += ["", f"PYTHON SYNTAX SCAN: {checked} files checked"]
    if syntax_errors:
        lines.append(f"[ERROR] Found {len(syntax_errors)} syntax error(s):")
        lines.extend(f"  - {item}" for item in syntax_errors[:20])
        if len(syntax_errors) > 20:
            lines.append(f"  ... and {len(syntax_errors) - 20} more")
    else:
        lines.append("[OK] No syntax errors found in readable scanned files.")

    if missing:
        lines += ["", "MISSING STARTUP PACKAGES: " + ", ".join(missing)]
    if sys.version_info >= (3, 15) or struct.calcsize("P") != 8:
        lines += [
            "",
            "[ACTION NEEDED] This Python environment may not support all JARVIS "
            "dependencies (including ONNX Runtime used by the optional wake-word "
            "feature). Use a supported 64-bit Python 3.12 environment, then run "
            "JARVIS with that same interpreter."
        ]
    if not REQUIREMENTS.is_file():
        lines += ["", "[ERROR] requirements.txt is missing; dependency repair is unavailable."]
    lines += [
        "",
        "SAFETY: Diagnostics did not change files or install packages.",
        'Voice commands: "open auto repair", "diagnose Jarvis", or '
        '"repair Jarvis dependencies".',
    ]
    return "\n".join(lines)


def auto_repair(parameters: dict, player=None, speak=None, response=None,
                session_memory=None) -> str:
    """Open the Auto Repair report, run diagnostics, or repair Python deps."""
    mode = str((parameters or {}).get("mode", "open")).strip().lower()
    if mode not in {"open", "diagnose", "repair"}:
        mode = "open"

    if mode in {"open", "diagnose"}:
        return _diagnose()

    # Do not attempt installs on Python versions/architectures with poor wheel
    # availability. In particular, ONNX Runtime has no suitable wheel for the
    # user's current Python 3.15 environment.
    if sys.version_info >= (3, 15) or struct.calcsize("P") != 8:
        return (
            _diagnose()
            + "\n\n[REPAIR NOT RUN] Dependency installation was skipped because "
              "this interpreter is not a supported 64-bit Python environment. "
              "Install Python 3.12 64-bit and launch JARVIS with it first."
        )
    if not REQUIREMENTS.is_file():
        return "[REPAIR FAILED] requirements.txt was not found. No changes were made."

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (
            "[REPAIR TIMED OUT] Dependency installation exceeded 10 minutes. "
            "No source files were changed; inspect pip output by running the "
            "install command manually in a terminal."
        )
    except OSError as exc:
        return f"[REPAIR FAILED] Could not start pip: {exc}. No source files were changed."

    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    tail = "\n".join(output.splitlines()[-24:])
    status = "SUCCESS" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    return (
        f"JARVIS DEPENDENCY REPAIR: {status}\n"
        "Only packages declared in requirements.txt were targeted; source files "
        "were not edited. Restart JARVIS and run diagnostics again.\n\n"
        f"pip output (last lines):\n{tail or '(no output)'}"
    )


TOOL = {
    "name": "auto_repair",
    "description": (
        "Open JARVIS Auto Repair and diagnose this JARVIS application's local "
        "Python environment and source syntax. Call mode='open' when the user "
        "says 'open auto repair' or 'show auto repair'. Call mode='diagnose' "
        "when they ask to check or diagnose JARVIS errors. Only call mode='repair' "
        "when the user explicitly asks to repair/fix JARVIS dependencies; that "
        "installs packages from the project's requirements.txt, without editing "
        "source code. Do not claim that arbitrary source-code bugs were auto-fixed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "mode": {
                "type": "STRING",
                "enum": ["open", "diagnose", "repair"],
                "description": "open = display read-only report; diagnose = same checks; repair = reinstall declared dependencies only.",
            }
        },
        "required": ["mode"],
    },
    "handler": auto_repair,
}
