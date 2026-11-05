"""Import every UI module once, so a broken import fails CI instead of a user.

The UI package is the largest part of JARVIS with the least test coverage: only
the modules a test happens to import get exercised, and a typo, a stale name or
a deleted import in `ui/panels/modern_dashboard.py` would otherwise only appear
when someone opens that panel. Importing each module proves the module body runs
and every name it uses at module scope still exists.

Skipped entirely when Qt cannot load (headless Linux without libGL/libEGL);
it runs on Windows CI and on any developer desktop.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# exc_type=ImportError is required: since pytest 8.2 only ModuleNotFoundError
# skips by default, and a missing libGL surfaces as a plain ImportError.
pytest.importorskip(
    "PyQt6.QtWidgets",
    reason="Qt cannot load on this machine (missing libGL/libEGL)",
    exc_type=ImportError,
)

UI_DIR = Path(__file__).resolve().parents[1] / "ui"


def _ui_modules() -> list[str]:
    modules = ["ui"]
    for path in sorted(UI_DIR.rglob("*.py")):
        relative = path.relative_to(UI_DIR.parent).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        name = ".".join(parts)
        if name not in modules:
            modules.append(name)
    return modules


@pytest.mark.parametrize("module_name", _ui_modules())
def test_ui_module_imports(module_name):
    try:
        importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - environment dependent
        # A missing optional third-party package or an audio/display backend is
        # an environment problem, not a regression in this module. Anything else
        # (NameError, AttributeError, SyntaxError) fails the test.
        message = str(exc)
        if any(
            hint in message
            for hint in ("libGL", "libEGL", "PortAudio", "DISPLAY", "no Qt platform")
        ):
            pytest.skip(f"{module_name} needs an unavailable system library: {message}")
        raise
