"""Shared pytest setup for the JARVIS AI test suite.

Two jobs:

1. **Make the suite runnable from any directory.** JARVIS is a folder-of-packages
   app (``core``, ``actions``, ``memory``, ...) rather than an installed
   distribution, so the repository roots must be importable. Previously every
   test file re-did that ``sys.path`` dance itself, and a test that forgot it
   only passed when pytest happened to be started from ``JarvisAI/``. Doing it
   once here means ``python -m pytest`` works from the repository root, from
   ``JarvisAI/``, and from an IDE test runner.

2. **Skip the GUI tests gracefully when Qt's system libraries are missing.**
   ``PyQt6`` installs fine on a bare Linux server or container but importing it
   fails without ``libGL``/``libEGL``. Without this guard, four GUI test modules
   abort collection and no tests run at all. They are reported as skipped with a
   clear reason instead; on a desktop or the CI runner (which installs those
   libraries) they run normally.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

JARVIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = JARVIS_DIR.parent

# Order matters: JARVIS_DIR first so the app's own top-level packages win over
# anything similarly named that a virtualenv may have installed.
for _path in (JARVIS_DIR, REPO_ROOT, JARVIS_DIR / "voice"):
    _entry = str(_path)
    if _entry in sys.path:
        sys.path.remove(_entry)
    sys.path.insert(0, _entry)


def _qt_is_importable() -> bool:
    """True when PyQt6 can actually load (needs libGL/libEGL on Linux)."""
    try:
        import PyQt6.QtWidgets  # noqa: F401
    except Exception:
        return False
    return True


QT_AVAILABLE = _qt_is_importable()

# Modules that import PyQt6 at module scope and therefore cannot be collected
# without a working Qt runtime.
_QT_TEST_MODULES = (
    "tests/test_avatar.py",
    "tests/test_bihansa_integration.py",
    "tests/test_pr68_fixes.py",
    "tests/test_ui_hologram.py",
)

if not QT_AVAILABLE:
    collect_ignore = list(_QT_TEST_MODULES)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Print what fail-soft handlers swallowed, when asked to.

    Set ``JARVIS_FAILSOFT_REPORT=1`` (the CI lint/test job does not, so a normal
    run stays quiet). This is the cheapest way to answer "is any optional
    feature quietly broken right now?" — two shipped bugs (a memory panel and a
    scheduler panel calling APIs that never existed) were invisible for exactly
    this reason.
    """
    if os.environ.get("JARVIS_FAILSOFT_REPORT", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    try:
        from core import failsoft

        report = failsoft.report(limit=40)
    except Exception:  # pragma: no cover - failsoft is best effort here too
        return
    if report:
        terminalreporter.section("fail-soft suppressions")
        for line in report.splitlines():
            terminalreporter.write_line(line)


def pytest_report_header(config) -> str:
    if QT_AVAILABLE:
        qt_state = "available"
    else:
        excluded = ", ".join(Path(name).name for name in _QT_TEST_MODULES)
        qt_state = f"unavailable — not collected: {excluded}"
    return f"jarvis roots: {JARVIS_DIR} | Qt: {qt_state}"
