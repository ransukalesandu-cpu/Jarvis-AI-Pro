"""Workstream C: window placement, tiling, LRU, workspaces and voice commands."""
import tempfile
import unittest
from pathlib import Path

from core.ui_layout import compute_layout
from core.voice_ui_control import parse_voice_ui_command
from core.window_manager import KINDS, WindowManager, Workspaces


def _no_overlap(geo):
    rects = list(geo.values())
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            if a.overlap_area(b) > 0.5:
                return False
    return True


class WindowManagerTests(unittest.TestCase):
    def setUp(self):
        self.lay = compute_layout(1920, 1080)
        self.wm = WindowManager(self.lay)

    def test_windows_tile_in_docks_and_never_cover_the_stage(self):
        for kind in ("music", "timer", "news", "image"):
            self.wm.open(kind)
        geo = self.wm.geometry()
        self.assertEqual(len(geo), 4)
        self.assertTrue(_no_overlap(geo))
        for r in geo.values():
            self.assertFalse(r.intersects(self.lay.stage))
            self.assertTrue(self.lay.dock_left.contains(r) or self.lay.dock_right.contains(r))

    def test_requested_side_and_reopen_brings_back(self):
        w = self.wm.open("music", "right")
        self.assertEqual(w.side, "right")
        again = self.wm.open("music", "left")
        self.assertIs(again, w)
        self.assertEqual(w.side, "left")
        self.assertEqual(len(self.wm.windows()), 1)
        with self.assertRaises(KeyError):
            self.wm.open("spreadsheet")

    def test_full_dock_minimises_the_least_recently_used(self):
        wm = WindowManager(compute_layout(1366, 768))
        order = ("video", "youtube_music", "music", "news", "image", "downloads", "timer")
        for kind in order:
            wm.open(kind, "left")
        shown = [w for w in wm.in_dock("left") if not w.minimized]
        self.assertLess(len(shown), len(order))
        self.assertTrue(wm.find("video").minimized)             # opened first, used least
        self.assertFalse(wm.find("timer").minimized)            # just opened
        self.assertTrue(_no_overlap(wm.geometry()))

    def test_reflow_on_resize_keeps_everything_inside(self):
        for kind in KINDS:
            self.wm.open(kind)
        for w, h in ((1366, 768), (3840, 2160), (1600, 900)):
            lay = compute_layout(w, h)
            self.wm.set_layout(lay)
            geo = self.wm.geometry()
            self.assertTrue(geo)
            self.assertTrue(_no_overlap(geo), (w, h))
            for r in geo.values():
                self.assertFalse(r.intersects(lay.stage), (w, h))

    def test_drop_moves_to_nearest_dock_and_slot(self):
        a = self.wm.open("timer", "right")
        b = self.wm.open("news", "right")
        self.wm.drop(b.id, self.lay.dock_right.center[0], self.lay.dock_right.y + 5)
        self.assertEqual([w.kind for w in self.wm.in_dock("right")], ["news", "timer"])
        self.wm.drop(a.id, 100, 400)
        self.assertEqual(a.side, "left")

    def test_only_recent_web_windows_stay_live(self):
        wm = WindowManager(self.lay, max_live_web=1)
        v = wm.open("video", "left")
        m = wm.open("music", "right")
        self.assertEqual(wm.frozen(), {v.id})
        wm.focus(v.id)
        self.assertEqual(wm.frozen(), {m.id})
        self.assertNotIn(wm.open("timer").id, wm.frozen())       # not web-backed

    def test_tile_spreads_and_restores(self):
        for kind in ("video", "youtube_music", "music", "timer"):
            self.wm.open(kind, "left")
        self.wm.tile()
        self.assertEqual(len(self.wm.in_dock("left")), 2)
        self.assertEqual(len(self.wm.in_dock("right")), 2)

    def test_workspaces_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspaces(Path(d) / "workspaces.json")
            self.wm.open("music", "left")
            self.wm.open("news", "right", {"query": "tech"})
            ws.save("Study", self.wm)
            other = WindowManager(self.lay)
            self.assertTrue(ws.load("study", other))
            self.assertEqual({(w.kind, w.side) for w in other.windows()},
                             {("music", "left"), ("news", "right")})
            self.assertEqual(other.find("news").payload, {"query": "tech"})
            self.assertFalse(ws.load("missing", other))
            self.assertEqual(ws.names(), ["study"])
            self.assertTrue(ws.delete("study"))


class VoiceTests(unittest.TestCase):
    def test_window_phrases(self):
        cases = {
            "open music on the left": ("window_open", "music", "left"),
            "jarvis open youtube music on the right side": ("window_open", "youtube_music", "right"),
            "show the news": ("window_open", "news", ""),
            "move video to the right": ("window_move", "video", "right"),
            "close the timer window": ("window_close", "timer", ""),
            "save workspace as study": ("workspace_save", "study", ""),
            "load workspace study": ("workspace_load", "study", ""),
            "tile windows": ("window_tile", "", ""),
        }
        for text, want in cases.items():
            cmd = parse_voice_ui_command(text)
            self.assertEqual((cmd.action, cmd.target, cmd.desired_state), want, text)

    def test_other_commands_are_unchanged(self):
        self.assertEqual(parse_voice_ui_command("open settings").action, "click")
        self.assertEqual(parse_voice_ui_command("close window").action, "close_active")
        self.assertIsNone(parse_voice_ui_command("what's the weather like"))


if __name__ == "__main__":
    unittest.main()
