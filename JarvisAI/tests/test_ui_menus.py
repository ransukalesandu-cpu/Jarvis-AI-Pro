"""Workstream D: menus, command palette and the Dynamic Island."""
import unittest

from PyQt6.QtWidgets import QApplication

from core import ui_menus, ui_state

_APP = QApplication.instance() or QApplication([])


class MenuDataTests(unittest.TestCase):
    def test_sections_are_the_requested_ones(self):
        self.assertEqual(ui_menus.LEFT_SECTIONS, ("Home", "AI Tools", "Media", "Productivity",
                                                  "Automation", "History", "Workspaces"))
        right = [c.title for c in ui_menus.by_section(ui_menus.RIGHT_SECTION)]
        self.assertEqual(right, ["JARVIS Mode", "BIHANSA Mode", "Settings", "System Controls",
                                 "Activity", "Telemetry"])
        for section in ui_menus.LEFT_SECTIONS:
            self.assertTrue(ui_menus.by_section(section), section)

    def test_ids_are_unique_and_windows_exist(self):
        from core.window_manager import KINDS
        ids = [c.id for c in ui_menus.COMMANDS]
        self.assertEqual(len(ids), len(set(ids)))
        for cid in ids:
            if cid.startswith("open:"):
                self.assertIn(cid.split(":", 1)[1], KINDS)

    def test_search_ranks_titles_first(self):
        self.assertEqual(ui_menus.search("timer")[0].id, "open:timer")
        self.assertEqual(ui_menus.search("ytm")[0].id, "open:youtube_music")
        self.assertEqual(ui_menus.search("tele")[0].id, "telemetry")
        self.assertIn("open:news", [c.id for c in ui_menus.search("headlines")])
        self.assertEqual(ui_menus.search("zzzzqqq"), [])
        self.assertEqual(len(ui_menus.search("")), 12)
        extra = [ui_menus.Command("ws:load:study", "Workspace: study", "Workspaces")]
        self.assertEqual(ui_menus.search("study", extra)[0].id, "ws:load:study")


class PaletteAndIslandTests(unittest.TestCase):
    def test_palette_runs_commands_and_free_text(self):
        from PyQt6.QtWidgets import QWidget

        from ui.command_palette import CommandPalette
        host = QWidget()
        host.resize(1000, 700)
        pal = CommandPalette(host)
        chosen, asked = [], []
        pal.command_chosen.connect(chosen.append)
        pal.text_submitted.connect(asked.append)
        pal.open()
        pal.input.setText("news")
        pal._run()
        self.assertEqual(chosen, ["open:news"])
        pal.open()
        pal.input.setText("what is the capital of peru zzqx")
        pal._run()
        self.assertEqual(asked, ["what is the capital of peru zzqx"])
        self.assertFalse(pal.isVisible())

    def test_island_follows_the_bus(self):
        from ui.command_palette import IslandPill
        bus = ui_state.bus()
        isl = IslandPill()
        bus.set(ui_state.ASSISTANT, "speaking")
        bus.set(ui_state.WINDOWS, ("timer", "news"))
        isl.set_timer("04:59")
        self.assertEqual(isl.text(), "SPEAKING   ·   ◷ 04:59   ·   ▣ 2")
        isl.resize(360, 28)
        isl.grab()
        bus.set(ui_state.WINDOWS, ())
        bus.set(ui_state.ASSISTANT, "idle")


if __name__ == "__main__":
    unittest.main()
