"""What the Computer Control Engine can actually do on this computer, and why not.

``report()`` returns one :class:`Check` per part of the engine. Every check is
read-only and cheap: nothing is launched, no browser is started, no screenshot is
taken and no network request is made. Secrets are never read into the report —
the hosted-vision check only says whether a key is *configured*.

Reason codes (stable, for UI and tests):

``ok`` · ``engine_off`` · ``dry_run`` · ``unsupported_os`` · ``missing_dependency`` ·
``backend_unavailable`` · ``not_installed`` · ``not_configured`` · ``no_prompt`` ·
``stop_engaged`` · ``unknown``
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
from dataclasses import asdict, dataclass

from jarvis.computer_control import approval, estop, flags


@dataclass(frozen=True)
class Check:
    id: str          # "engine", "windows", "browser", "ocr", "vision", "approval", "stop"
    label: str       # owner-facing name
    ok: bool
    reason: str      # reason code (module docstring)
    detail: str      # one owner-facing sentence; no paths, no secrets

    def as_dict(self) -> dict:
        return asdict(self)


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _engine() -> Check:
    if not flags.enabled():
        return Check("engine", "Engine", False, "engine_off", flags.describe())
    if flags.dry_run():
        return Check("engine", "Engine", True, "dry_run",
                     "On in dry-run mode: actions are checked and logged but never performed.")
    return Check("engine", "Engine", True, "ok", "On.")


def _windows() -> Check:
    label = "Windows apps and controls"
    if platform.system() != "Windows":
        return Check("windows", label, False, "unsupported_os",
                     f"Needs Windows; this computer runs {platform.system() or 'an unknown OS'}.")
    if not _has_module("pywinauto"):
        return Check("windows", label, False, "missing_dependency",
                     "The pywinauto package is not installed (pip install -r requirements.txt).")
    try:
        from jarvis.computer_control.windows.backend import get_backend
        ok, reason = get_backend().available()
    except Exception as exc:
        return Check("windows", label, False, "backend_unavailable",
                     f"Windows UI Automation could not start ({type(exc).__name__}).")
    if not ok:
        return Check("windows", label, False, "backend_unavailable", str(reason)[:200])
    return Check("windows", label, True, "ok", "Windows UI Automation is ready.")


def _installed_browsers() -> list[str]:
    """Edge/Chrome found at their usual places. Empty when unknown (checked at launch)."""
    found: list[str] = []
    if platform.system() == "Windows":
        roots = [os.environ.get(name, "") for name in
                 ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        candidates = {
            "Edge": [r"Microsoft\Edge\Application\msedge.exe"],
            "Chrome": [r"Google\Chrome\Application\chrome.exe"],
        }
        for name, relatives in candidates.items():
            if any(root and os.path.isfile(os.path.join(root, rel))
                   for root in roots for rel in relatives):
                found.append(name)
        return found
    for name, commands in (("Edge", ("microsoft-edge", "microsoft-edge-stable")),
                           ("Chrome", ("google-chrome", "google-chrome-stable"))):
        if any(shutil.which(cmd) for cmd in commands):
            found.append(name)
    if platform.system() == "Darwin":
        for name, app in (("Edge", "/Applications/Microsoft Edge.app"),
                          ("Chrome", "/Applications/Google Chrome.app")):
            if os.path.isdir(app) and name not in found:
                found.append(name)
    return found


def _browser() -> Check:
    label = "Web browser (Edge/Chrome)"
    if not _has_module("playwright"):
        return Check("browser", label, False, "missing_dependency",
                     "The playwright package is not installed (pip install -r requirements.txt).")
    browsers = _installed_browsers()
    if not browsers:
        return Check("browser", label, False, "not_installed",
                     "No installed Edge or Chrome was found; JARVIS uses the installed browser, "
                     "never a downloaded one.")
    return Check("browser", label, True, "ok",
                 f"Playwright is installed; found {', '.join(browsers)}.")


def _ocr() -> Check:
    label = "Local text recognition (OCR)"
    try:
        from jarvis.agent.screen_vision import OcrEngine
        engine = OcrEngine()
        if engine.available():
            return Check("ocr", label, True, "ok", "Tesseract is installed.")
        reason = engine.failure_reason or "Tesseract is not available"
    except Exception as exc:
        return Check("ocr", label, False, "unknown", f"OCR check failed ({type(exc).__name__}).")
    code = "missing_dependency" if "missing" in reason else "not_installed"
    return Check("ocr", label, False, code,
                 f"Not available: {reason}. Screen reading falls back to accessibility, "
                 "page elements and hosted vision.")


def _vision() -> Check:
    label = "Hosted vision (Gemini)"
    try:
        from jarvis.agent.screen_vision import GeminiVisionProvider
        configured = GeminiVisionProvider().available()
    except Exception as exc:
        return Check("vision", label, False, "unknown", f"Vision check failed ({type(exc).__name__}).")
    if not configured:
        return Check("vision", label, False, "not_configured",
                     "No Gemini key is configured for screen vision (used only as a last resort, "
                     "with password fields masked).")
    return Check("vision", label, True, "ok",
                 "A Gemini key is configured (used only when accessibility, page elements and OCR "
                 "cannot find the target).")


def _approval() -> Check:
    label = "Approval prompt"
    if isinstance(approval.get_approver(), approval.NativeApprover):
        return Check("approval", label, True, "ok",
                     "High-risk actions ask for approval in the JARVIS window.")
    return Check("approval", label, False, "no_prompt",
                 "No approval prompt is connected (headless or the HUD is not running); every "
                 "high-risk action will be refused.")


def _stop() -> Check:
    stop = estop.get()
    if stop.engaged:
        last = stop.last
        return Check("stop", "Emergency stop", False, "stop_engaged",
                     "The emergency stop is holding" + (f" ({last.reason})." if last else "."))
    return Check("stop", "Emergency stop", True, "ok", "Ready (say 'Jarvis, stop').")


_CHECKS = (_engine, _windows, _browser, _ocr, _vision, _approval, _stop)


def report() -> list[Check]:
    out: list[Check] = []
    for check in _CHECKS:
        try:
            out.append(check())
        except Exception as exc:              # a probe must never break the status tool
            name = check.__name__.lstrip("_")
            out.append(Check(name, name, False, "unknown", f"Check failed ({type(exc).__name__})."))
    return out


def summary(checks: list[Check] | None = None) -> str:
    """One or two spoken sentences: what works, what does not and why."""
    checks = checks if checks is not None else report()
    engine = next(c for c in checks if c.id == "engine")
    if not engine.ok:
        return engine.detail
    ready = [c.label for c in checks if c.ok and c.id not in ("engine", "approval", "stop")]
    blocked = [f"{c.label}: {c.detail}" for c in checks if not c.ok]
    head = engine.detail if engine.reason == "dry_run" else "Computer control is on."
    parts = [head]
    if ready:
        parts.append("Ready: " + ", ".join(ready) + ".")
    if blocked:
        parts.append("Not ready — " + " ".join(blocked))
    return " ".join(parts)


# Public single-part checks (computer_control/routing.py asks only these at connect time).
windows_check = _windows
browser_check = _browser
