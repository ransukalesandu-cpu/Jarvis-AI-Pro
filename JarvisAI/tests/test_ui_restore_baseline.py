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
    "core.hologram_theme",
    "core.system_status",
    "core.subsystem_probes",
    "core.hud_layout",
    "core.media_transport",
    "core.task_sources",
    "core.battery_settings",
    "ui.task_panels",
    "ui.health_strip",
    "ui.panels.battery_settings",
)

_REMOVED_FILES = (
    "core/hologram_theme.py",
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


def test_the_hud_still_has_its_original_hologram_stack():
    """The restore must keep one face renderer and the separate Bihansa persona."""
    source = (UI_DIR / "hud_main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert {"HUDMainWindow", "HologramHUDUI"} <= defined
    for attribute in (
        "self.wireframe_visualizer",
        "self.bihansa_visualizer",
        "self._visualizer_stack",
        "self._hologram_stage",
        "self._mini_orb",
        "self._heart_reactor",
    ):
        assert attribute in source, f"{attribute} is part of the restored HUD"


def test_the_autonomous_surfaces_are_still_opt_in():
    """The revert must not undo the opt-in flag from the autonomous-task work."""
    source = (UI_DIR / "hud_main.py").read_text(encoding="utf-8")
    assert "def _agent_ui_enabled()" in source
    assert "if _agent_ui_enabled() and AutonomousPanel is not None:" in source
    # The rail button and the dashboard card both key off the built panel, not
    # off the import, or a disabled flag would still add a dead control.
    assert 'if self._panel_agent is not None:\n            left_rail_entries.append' in source


def test_the_hologram_clears_to_the_backdrop_not_to_transparency():
    """``CompositionMode_Clear`` composites to black on a child widget.

    That was a real regression once already; the revert restored the code that
    had it, so the fix is pinned here.
    """
    renderers = (
        UI_DIR / "hologram" / "wireframe_head.py",
        UI_DIR / "hologram" / "bihansa_hologram.py",
    )
    # Match the *call*, not the word: the fixed code explains the old bug in a
    # comment, and that comment must not fail its own regression test.
    clear_call = re.compile(r"setCompositionMode\(\s*QPainter\.CompositionMode\."
                            r"CompositionMode_Clear\s*\)")
    source_call = re.compile(r"setCompositionMode\(\s*QPainter\.CompositionMode\."
                             r"CompositionMode_Source\s*\)")
    for path in renderers:
        source = path.read_text(encoding="utf-8")
        paint = source[source.index("    def paintEvent"):]
        assert not clear_call.search(paint), (
            f"{path.name} clears its frame to transparency, which paints black"
        )
        assert source_call.search(paint), (
            f"{path.name} must repaint its frame in the HUD backdrop colour"
        )
        assert re.search(r"fillRect\(self\.rect\(\), ", paint), (
            f"{path.name} must fill its own rect with that backdrop colour"
        )


def test_the_reverted_test_modules_are_not_referenced():
    """conftest.py and the suite must not list test files that no longer exist."""
    conftest = (JARVIS_DIR / "conftest.py").read_text(encoding="utf-8")
    listed = re.findall(r'"(tests/test_[a-z0-9_]+\.py)"', conftest)
    missing = [name for name in listed if not (JARVIS_DIR / name).exists()]
    assert missing == [], f"conftest.py lists test modules that do not exist: {missing}"
