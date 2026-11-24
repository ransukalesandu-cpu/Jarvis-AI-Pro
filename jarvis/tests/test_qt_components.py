"""UI P3: Qt component set (jarvis/ui/components) — states, accessibility, snapshots, token parity.

Snapshots are structural (widget class, accessible name/description, style properties, state), so they
are stable across fonts and platforms. Regenerate after an intended change with:
    JARVIS_UPDATE_SNAPSHOTS=1 python -m pytest jarvis/tests/test_qt_components.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("qfluentwidgets")
pytest.importorskip("pytestqt")

from PyQt6.QtWidgets import QLabel, QWidget  # noqa: E402

from jarvis.ui import components as ui  # noqa: E402
from jarvis.ui.theme.tokens import THEMES  # noqa: E402

SNAP = Path(__file__).parent / "snapshots" / "qt_components.json"


def describe(w: QWidget) -> dict:
    """Stable structural snapshot of one component."""
    def props(x):
        return {k: x.property(k) for k in ("variant", "uiSize", "tone", "invalid", "busy") if x.property(k) is not None}

    controls = []
    for child in [w, *w.findChildren(QWidget)]:
        name, desc = child.accessibleName(), child.accessibleDescription()
        if name or desc or props(child):
            controls.append({"class": type(child).__name__, "name": name, "description": desc,
                             "enabled": child.isEnabled(), **props(child)})
    return {"class": type(w).__name__, "controls": controls}


@pytest.fixture(autouse=True)
def _delete_leftovers():
    """Delete every top-level widget a test created, so later tests (style changes) never meet them."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QApplication
    before = set(map(id, QApplication.topLevelWidgets()))
    yield
    for w in QApplication.topLevelWidgets():
        if id(w) not in before:
            w.close()
            w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    QCoreApplication.processEvents()


@pytest.fixture
def root(qtbot):
    w = QWidget()
    ui.apply_theme(w)
    w.resize(900, 640)
    qtbot.addWidget(w)
    return w


def build(root: QWidget) -> dict[str, QWidget]:
    lbl = QLabel
    return {
        "button_solid": ui.Button("Save"),
        "button_outline_danger": ui.Button("Delete", variant="outline", tone="danger", size="sm"),
        "button_ghost": ui.Button("More", variant="ghost", tone="neutral", size="lg"),
        "button_loading": ui.Button("Saving", loading=True),
        "button_disabled": ui.Button("Locked", disabled=True),
        "input": ui.Input("Task name", placeholder="e.g. report", hint="Shown in Task Progress."),
        "input_invalid": ui.Input("Task name", error="Give the task a name."),
        "input_disabled": ui.Input("Task name", value="busy", disabled=True),
        "textarea": ui.Textarea("Notes", placeholder="Anything JARVIS should know"),
        "select": ui.Select("Text brain", [("gemini", "Gemini Live"), ("claude", "Claude")], value="claude"),
        "select_empty": ui.Select("Text brain", [], empty_text="No providers configured"),
        "checkbox": ui.Checkbox("Show Task Flow", checked=True),
        "checkbox_invalid": ui.Checkbox("Agree", error="Required."),
        "switch": ui.Switch("Reduced motion", checked=True),
        "segmented": ui.Segmented("Centre", [("brain", "Neural brain"), ("head", "Hologram head")], value="head"),
        "tabs": ui.Tabs("Settings sections", [("general", "General", lbl("one")), ("voice", "Voice", lbl("two"))]),
        "table": ui.Table("Jobs", [("name", "Job"), ("secs", "Time")], [{"name": "Backup", "secs": 12}]),
        "table_loading": ui.Table("Jobs", [("name", "Job")], loading=True),
        "table_empty": ui.Table("Jobs", [("name", "Job")], [], empty_text="No jobs this session."),
        "table_error": ui.Table("Jobs", [("name", "Job")], error="Could not read jobs.", on_retry=lambda: None),
        "spark": ui.SparkChart("CPU", [10, 50, 30], unit="%", max_value=100),
        "spark_empty": ui.SparkChart("CPU", []),
        "dialog": ui.Dialog("Rename routine", parent=root, description="Routines start with their phrase.",
                            body=lbl("body"), primary="Save"),
        "sheet": ui.Sheet("Phone", lbl("online"), parent=root),
        "collapsible": ui.Collapsible("Advanced", lbl("hidden")),
    }


def test_snapshots(root):
    built = build(root)
    holder = QWidget(root)               # parent everything so it is deleted with the root
    for w in built.values():
        if w.parent() is None:
            w.setParent(holder)
    got = {k: describe(w) for k, w in built.items()}
    if os.environ.get("JARVIS_UPDATE_SNAPSHOTS") == "1" or not SNAP.exists():
        SNAP.write_text(json.dumps(got, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
        if os.environ.get("JARVIS_UPDATE_SNAPSHOTS") != "1":
            pytest.fail("snapshot file was missing; written now, re-run")
    assert json.loads(json.dumps(got, sort_keys=True, default=str)) == json.loads(SNAP.read_text(encoding="utf-8"))


def test_button_states(qtbot):
    b = ui.Button("Save", loading=True)
    qtbot.addWidget(b)
    assert not b.button.isEnabled() and b.button.property("busy") is True
    assert b.button.accessibleName() == "Save"
    b.set_loading(False)
    assert b.button.isEnabled()
    clicks = []
    b.clicked.connect(lambda: clicks.append(1))
    qtbot.mouseClick(b.button, __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.MouseButton.LeftButton)
    assert clicks == [1]
    with pytest.raises(ValueError):
        ui.Button("x", tone="purple")


def test_field_error_is_described_and_cleared(qtbot):
    f = ui.Input("Name", hint="Optional", error="Required")
    qtbot.addWidget(f)
    assert f.control.property("invalid") is True
    assert f.control.accessibleDescription() == "Required"
    f.set_error("")
    assert f.control.property("invalid") is False
    assert f.control.accessibleDescription() == "Optional"


def test_tabs_and_segmented_switch(qtbot):
    t = ui.Tabs("Sections", [("a", "A", QLabel("one")), ("b", "B", QLabel("two"))])
    qtbot.addWidget(t)
    seen = []
    t.changed.connect(seen.append)
    t.select("b")
    assert t.current == "b" and t.stack.currentIndex() == 1 and seen == ["b"]
    s = ui.Segmented("Centre", [("x", "X"), ("y", "Y")], value="x")
    qtbot.addWidget(s)
    assert s.seg.currentRouteKey() == "x"


def test_table_modes(qtbot):
    t = ui.Table("Jobs", [("name", "Job")], [{"name": "a"}])
    qtbot.addWidget(t)
    assert t.mode == "rows" and t.table.rowCount() == 1
    t.set_rows([], loading=True)
    assert t.mode == "loading" and t.table.rowCount() == 0
    t.set_rows([], error="boom")
    assert t.mode == "error" and t.state_text.text() == "boom"
    t.set_rows([])
    assert t.mode == "empty"


def test_sheet_escape_closes(root, qtbot):
    from PyQt6.QtCore import Qt
    root.show()
    s = ui.Sheet("Phone", QLabel("x"), parent=root)
    s.open_sheet()
    assert s.isVisible()
    qtbot.keyClick(s, Qt.Key.Key_Escape)
    assert not s.isVisible()


def test_reduced_motion_zeroes_durations(monkeypatch):
    from jarvis.ui.components import theme
    monkeypatch.setenv("JARVIS_REDUCED_MOTION", "1")
    assert theme.ms("dur") == 0
    monkeypatch.setenv("JARVIS_REDUCED_MOTION", "0")
    assert theme.ms("dur") == int(THEMES["dark"]["dur"].removesuffix("ms"))


@pytest.mark.parametrize("theme", ["dark", "light", "hc"])
def test_palette_parity_with_tokens(qtbot, theme):
    from PyQt6.QtGui import QColor

    from jarvis.ui.components._fluent import fluent
    w = QWidget()
    qtbot.addWidget(w)
    ui.apply_theme(w, theme)
    # The accent Fluent derives its tints from (themeColor() returns a lighter tint on dark themes).
    assert fluent.qconfig.get(fluent.qconfig.themeColor).name() == QColor(THEMES[theme]["primary"]).name()
    assert fluent.isDarkTheme() == (theme != "light")
    assert THEMES[theme]["bg"] in w.styleSheet()
    assert ui.token("text") == THEMES[theme]["text"]
    ui.apply_theme(None, "dark")


# ── P3b: shell, qasync, gallery ────────────────────────────────────────────
def test_window_effect_choice(monkeypatch):
    from jarvis.ui.components import shell
    monkeypatch.setenv("JARVIS_WINDOW_EFFECT", "off")
    assert shell.window_effect() == "off"
    monkeypatch.setenv("JARVIS_WINDOW_EFFECT", "acrylic")
    assert shell.window_effect() == "acrylic"
    monkeypatch.delenv("JARVIS_WINDOW_EFFECT")
    expected = "off" if __import__("sys").platform != "win32" else shell.window_effect()
    assert shell.window_effect() == expected


def test_window_chrome_is_a_noop_off_windows(qtbot):
    import sys

    from jarvis.ui.components import shell
    w = QWidget()
    qtbot.addWidget(w)
    if sys.platform != "win32":
        assert shell.apply_window_chrome(w) is False
    assert shell._colorref("#102030") == 0x302010


def test_run_async_reports_result_and_error(qtbot):
    import asyncio

    from PyQt6.QtWidgets import QApplication

    from jarvis.ui.components.shell import qt_event_loop, run_async
    loop = qt_event_loop(QApplication.instance())
    got = []

    async def ok():
        await asyncio.sleep(0.01)
        return 42

    async def bad():
        raise ValueError("nope")

    run_async(ok(), lambda r, e: got.append((r, e)))
    run_async(bad(), lambda r, e: got.append((r, type(e).__name__)))
    loop.run_until_complete(asyncio.sleep(0.05))
    assert (42, None) in got and (None, "ValueError") in got
    loop.close()
    asyncio.set_event_loop(None)


def test_gallery_builds_with_every_section(qtbot):
    from jarvis.ui.components.gallery import build
    from jarvis.ui.components.shell import JarvisShell
    w = build("hc")
    qtbot.addWidget(w)
    assert isinstance(w, JarvisShell)
    tabs = w.findChildren(ui.Tabs)[0]
    assert set(tabs._pages) == {"buttons", "fields", "data", "overlays"}
    assert len(w.findChildren(ui.Table)) == 3
