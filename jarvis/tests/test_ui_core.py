"""Workstream A: design tokens, state bus + clock, layout manager (all Qt-free)."""
import json
import threading
import unittest

from jarvis.core import ui_layout, ui_state, ui_tokens


class TokenTests(unittest.TestCase):
    def test_exported_files_match_the_tokens(self):
        tok = ui_tokens.tokens()
        self.assertEqual((ui_tokens.ASSETS / "theme.json").read_text(encoding="utf-8"),
                         ui_tokens.to_json(tok), "run: python -m core.ui_tokens")
        self.assertEqual((ui_tokens.ASSETS / "theme.css").read_text(encoding="utf-8"),
                         ui_tokens.to_css(tok))

    def test_personas_change_only_the_hologram(self):
        j, b = ui_tokens.tokens("jarvis"), ui_tokens.tokens("bihansa")
        self.assertEqual(j["color"], b["color"])
        self.assertNotEqual(j["holo"]["primary"], b["holo"]["primary"])
        self.assertEqual(ui_tokens.tokens("nope")["persona"], "jarvis")

    def test_css_and_state_colours(self):
        css = ui_tokens.to_css(ui_tokens.tokens())
        self.assertIn("--jv-color-bg: #080e12;", css)
        self.assertIn("--jv-space-md: 12px;", css)
        self.assertIn("--jv-motion-fast: 120ms;", css)
        self.assertEqual(ui_tokens.state_color("SPEAKING"), ui_tokens.BASE_COLORS["accent"])
        self.assertEqual(ui_tokens.state_color("???"), ui_tokens.BASE_COLORS["primary"])
        json.loads(ui_tokens.to_json(ui_tokens.tokens()))

    def test_qt_palette_reads_the_tokens(self):
        from jarvis.ui import C
        self.assertEqual(C.PRI, ui_tokens.BASE_COLORS["primary"])
        self.assertEqual(C.BG, ui_tokens.BASE_COLORS["bg"])


class ClockTests(unittest.TestCase):
    def test_frame_cap_pause_and_resume(self):
        t = [100.0]
        clk = ui_state.AnimationClock(fps_cap=30, source=lambda: t[0])
        self.assertIsNotNone(clk.frame())
        t[0] += 0.01
        self.assertIsNone(clk.frame())               # too soon for 30 fps
        t[0] += 0.03
        dt = clk.frame()
        self.assertAlmostEqual(dt, 0.04, places=6)
        before = clk.now
        clk.pause()
        t[0] += 5.0
        self.assertIsNone(clk.frame())
        self.assertAlmostEqual(clk.now, before)      # animation time stands still
        clk.resume()
        t[0] += 0.05
        self.assertAlmostEqual(clk.now, before + 0.05)

    def test_long_stalls_do_not_jump(self):
        t = [0.0]
        clk = ui_state.AnimationClock(source=lambda: t[0])
        t[0] += 10.0
        self.assertLessEqual(clk.now, 0.25)


class BusTests(unittest.TestCase):
    def test_notify_on_change_only(self):
        b = ui_state.StateBus()
        seen = []
        b.subscribe(ui_state.ASSISTANT, lambda k, v: seen.append(v))
        b.set(ui_state.ASSISTANT, "speaking")
        b.set(ui_state.ASSISTANT, "speaking")
        b.set(ui_state.ASSISTANT, "idle")
        self.assertEqual(seen, ["speaking", "idle"])

    def test_other_threads_are_queued_until_drain(self):
        b = ui_state.StateBus()
        seen = []
        b.subscribe(ui_state.ALL, lambda k, v: seen.append((k, v)))
        th = threading.Thread(target=lambda: [b.set(ui_state.AUDIO_LEVEL, x) for x in (0.1, 0.5, 0.9)])
        th.start()
        th.join()
        self.assertEqual(seen, [])
        self.assertEqual(b.drain(), 3)
        self.assertEqual(seen, [(ui_state.AUDIO_LEVEL, 0.9)])  # newest value only

    def test_unsubscribe_and_bad_subscriber(self):
        b = ui_state.StateBus()
        seen = []
        b.subscribe("x", lambda k, v: 1 / 0)
        off = b.subscribe("x", lambda k, v: seen.append(v))
        b.set("x", 1)
        off()
        b.set("x", 2)
        self.assertEqual(seen, [1])


class LayoutTests(unittest.TestCase):
    SIZES = [(1366, 768), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160)]

    def test_regions_tile_without_overlap_at_every_size(self):
        for w, h in self.SIZES:
            lay = ui_layout.compute_layout(w, h)
            screen = ui_layout.Rect(0, 0, w, h)
            for name in ("header", "footer", "left_rail", "right_rail", "stage",
                         "dock_left", "dock_right"):
                self.assertTrue(screen.contains(getattr(lay, name)), (w, h, name))
            self.assertFalse(lay.stage.intersects(lay.dock_left), (w, h))
            self.assertFalse(lay.stage.intersects(lay.dock_right), (w, h))
            self.assertAlmostEqual(lay.stage.w / w, 0.40, delta=0.02)
            self.assertAlmostEqual(lay.stage.center[0], w / 2, delta=1)
            self.assertFalse(lay.compact, (w, h))

    def test_scale_tracks_the_screen(self):
        self.assertAlmostEqual(ui_layout.compute_layout(1920, 1080).scale, 1.0)
        self.assertAlmostEqual(ui_layout.compute_layout(3840, 2160).scale, 2.0)
        self.assertLess(ui_layout.compute_layout(1366, 768).scale, 0.75)

    def test_open_menus_shrink_docks_not_the_stage(self):
        closed = ui_layout.compute_layout(1920, 1080)
        opened = ui_layout.compute_layout(1920, 1080, left_open=True, right_open=True)
        self.assertEqual(closed.stage, opened.stage)
        self.assertLess(opened.dock_left.w, closed.dock_left.w)


if __name__ == "__main__":
    unittest.main()
