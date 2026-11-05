"""Pins the restored (pre-command-centre) HUD composition.

The holographic "command centre" upgrade added a copper wireframe face, docked
heart/orb cluster, glass task panels, a live health strip, a palette module and a
battery/network status system. It was reverted on request, so these tests stop the
pieces that were removed from creeping back as dangling imports, and they keep
the *good* behaviour that must survive the revert.

Everything here is static: it parses the UI sources instead of importing them, so
it runs on machines where Qt cannot load (no libGL/libxkbcommon).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

JARVIS_DIR = Path(__file__).resolve().parent.parent
UI_DIR = JARVIS_DIR / "ui"

#: Modules that only existed for the command-centre upgrade.
_REMOVED_MODULES = (
    "jarvis.core.system_status",
    "jarvis.core.subsystem_probes",
    "jarvis.core.hud_layout",
    "jarvis.core.media_transport",
    "jarvis.core.task_sources",
    "jarvis.core.battery_settings",
    "jarvis.ui.task_panels",
    "jarvis.ui.health_strip",
    "jarvis.ui.panels.battery_settings",
)

_REMOVED_FILES = (
    "core/system_status.py",
    "core/subsystem_probes.py",
    "core/hud_layout.py",
    "core/media_transport.py",
    "core/task_sources.py",
    "core/battery_settings.py",
    "ui/task_panels.py",
    "ui/health_strip.py",
    "ui/panels/battery_settings.py",
)


def _ui_sources() -> list[Path]:
    return sorted(p for p in UI_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _imports(path: Path) -> set[str]:
    """Every dotted module name the file imports (``from a.b import c`` → ``a.b``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_the_removed_modules_are_gone():
    for relative in _REMOVED_FILES:
        assert not (JARVIS_DIR / relative).exists(), f"{relative} should have been reverted"


def test_no_ui_module_imports_a_removed_module():
    offenders: dict[str, set[str]] = {}
    for path in _ui_sources():
        stale = {
            imported
            for imported in _imports(path)
            if any(imported == removed or imported.startswith(removed + ".")
                   for removed in _REMOVED_MODULES)
        }
        if stale:
            offenders[str(path.relative_to(JARVIS_DIR))] = stale
    assert offenders == {}, f"the HUD still imports reverted modules: {offenders}"


def test_hologram_theme_is_lightweight_and_qt_free():
    """The face palette may return, but it must remain pure Python."""
    theme = JARVIS_DIR / "core" / "hologram_theme.py"
    assert theme.exists()
    imported = _imports(theme)
    assert not any(
        name.startswith(("PyQt", "PySide", "jarvis.ui.", "jarvis.core.system_status"))
        for name in imported
    )


def test_the_hud_still_has_its_original_hologram_stack():
    """The HUD keeps one hologram widget (the WebGL engine) inside the same stage container."""
    source = (UI_DIR / "hud_main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert {"HUDMainWindow", "HologramHUDUI"} <= defined
    for attribute in (
        "self.hologram",
        "self._hologram_stage",
        "self._mini_orb",
    ):
        assert attribute in source, f"{attribute} is part of the HUD"
    # No second, duplicate renderer may be built next to the engine.
    for gone in ("NeuralWireframeHead", "BihansaHologramWidget", "NeuralHeartReactor"):
        assert gone not in source, f"{gone} must not be reintroduced next to the WebGL engine"


def test_the_autonomous_surfaces_are_still_opt_in():
    """The revert must not undo the opt-in flag from the autonomous-task work."""
    source = (UI_DIR / "hud_main.py").read_text(encoding="utf-8")
    assert "def _agent_ui_enabled()" in source
    assert "if _agent_ui_enabled() and AutonomousPanel is not None:" in source
    # The rail button and the dashboard card both key off the built panel, not
    # off the import, or a disabled flag would still add a dead control.
    assert 'if self._panel_agent is not None:\n            left_rail_entries.append' in source


def test_the_hologram_clears_to_the_backdrop_not_to_transparency():
    """A transparent web view over an opaque parent composites to black on some Windows setups.

    The old QPainter hologram hit that exact bug, so the engine host paints the HUD backdrop
    colour as its page background instead of transparency; the fix is pinned here.
    """
    source = (UI_DIR.parent / "hologram" / "host.py").read_text(encoding="utf-8")
    assert "backdrop_rgb" in source
    assert re.search(r"setBackgroundColor\(QColor\(\*backdrop_rgb\(\)\)\)", source)
    assert "QColor(0, 0, 0, 0)" not in source


def test_the_reverted_test_modules_are_not_referenced():
    """conftest.py and the suite must not list test files that no longer exist."""
    conftest = (JARVIS_DIR / "conftest.py").read_text(encoding="utf-8")
    listed = re.findall(r'"(tests/test_[a-z0-9_]+\.py)"', conftest)
    missing = [name for name in listed if not (JARVIS_DIR / name).exists()]
    assert missing == [], f"conftest.py lists test modules that do not exist: {missing}"
