"""Qt component gallery — the desktop twin of Storybook.

    python -m jarvis.ui.components.gallery [--theme dark|light|hc]

Every component in its states, in a frameless Fluent window with the shared tokens. The Table tab loads its
rows through qasync to show the loading -> rows path.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from PyQt6.QtWidgets import QApplication, QGridLayout, QLabel, QWidget


def build(theme: str = "dark") -> QWidget:
    from jarvis.ui import components as ui
    from jarvis.ui.components.shell import JarvisShell, run_async

    def grid(*widgets: QWidget) -> QWidget:
        page = QWidget()
        g = QGridLayout(page)
        g.setSpacing(ui.theme.px("space-3"))
        for i, w in enumerate(widgets):
            g.addWidget(w, i // 3, i % 3)
        g.setRowStretch(len(widgets) // 3 + 1, 1)
        for col in range(3):
            g.setColumnStretch(col, 1)
        return page

    buttons = grid(*(ui.Button(f"{v} {t}", variant=v, tone=t) for v in ("solid", "outline", "ghost")
                     for t in ("primary", "neutral", "danger")),
                   ui.Button("Saving", loading=True), ui.Button("Locked", disabled=True),
                   ui.Button("Large", size="lg"))
    fields = grid(ui.Input("Task name", placeholder="e.g. Weekly report", hint="Shown in Task Progress."),
                  ui.Input("Task name", error="Give the task a name."),
                  ui.Input("Locked", value="busy", disabled=True),
                  ui.Textarea("Notes", placeholder="Anything JARVIS should know"),
                  ui.Select("Text brain", [("gemini", "Gemini Live"), ("claude", "Claude"), ("ollama", "Local")]),
                  ui.Select("Empty", [], empty_text="No providers configured"),
                  ui.Checkbox("Show Task Flow on new tasks", checked=True),
                  ui.Switch("Reduced motion"),
                  ui.Segmented("Centre", [("brain", "Neural brain"), ("head", "Hologram head")], value="brain"))
    table = ui.Table("Background jobs", [("name", "Job"), ("state", "State"), ("secs", "Time")], loading=True)

    async def load_jobs():
        await asyncio.sleep(0.8)
        return [{"name": "Backup notes", "state": "done", "secs": 12},
                {"name": "Index Downloads", "state": "running", "secs": 48}]

    run_async(load_jobs(), lambda rows, err: table.set_rows(rows or [], error=str(err) if err else ""))
    data = grid(table, ui.Table("Empty", [("name", "Job")], []),
                ui.Table("Error", [("name", "Job")], error="Could not read jobs.", on_retry=lambda: None),
                ui.SparkChart("CPU", [12, 30, 22, 55, 41, 60, 38], unit="%", max_value=100),
                ui.SparkChart("RAM", [], unit="%"))
    overlay_btns = grid(ui.Button("Dialog"), ui.Button("Sheet", variant="outline", tone="neutral"),
                        ui.Button("Popover", variant="outline", tone="neutral"),
                        ui.Button("Toast", variant="outline", tone="ok"),
                        ui.Collapsible("Advanced", QLabel("Hidden until expanded")))
    tabs = ui.Tabs("Gallery sections", [("buttons", "Buttons", buttons), ("fields", "Fields", fields),
                                        ("data", "Data", data), ("overlays", "Overlays", overlay_btns)])
    win = JarvisShell(f"JARVIS components · {theme}", tabs, theme=theme)
    b_dialog, b_sheet, b_pop, b_toast = (overlay_btns.layout().itemAt(i).widget() for i in range(4))
    sheet = ui.Sheet("Phone", QLabel("Online over Tailscale."), parent=win)
    b_dialog.clicked.connect(lambda: ui.Dialog("Rename routine", parent=win, description="Routines start with their phrase.",
                                               body=ui.Input("Name", value="morning"), primary="Save").exec())
    b_sheet.clicked.connect(sheet.open_sheet)
    b_pop.clicked.connect(lambda: ui.popover(b_pop.button, "Brain route", "Voice: Gemini Live. Text: Claude."))
    b_toast.clicked.connect(lambda: ui.toast(win, "Saved", "Layout saved on this PC.", tone="ok"))
    win.resize(1100, 720)
    return win


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theme", choices=["dark", "light", "hc"], default="dark")
    args = ap.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv)
    from jarvis.ui.components.shell import qt_event_loop

    loop = qt_event_loop(app)
    win = build(args.theme)
    win.show()
    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
