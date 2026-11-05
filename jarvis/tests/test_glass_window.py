"""Workstream C (Qt side): glass window frame and its contents."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

from jarvis.ui.glass_window import (DownloadsContent, GlassWindow, NewsContent,  # noqa: E402
                             TimerContent, WebMediaContent, make_content, recent_files)


class GlassWindowTests(unittest.TestCase):
    def test_frame_signals_and_paint(self):
        gw = GlassWindow("timer-1", "TIMER", TimerContent())
        closed, mini = [], []
        gw.close_clicked.connect(closed.append)
        gw.minimize_clicked.connect(mini.append)
        gw.resize(320, 200)
        gw.grab()                                    # paints without errors
        buttons = [b for b in gw._bar.children() if hasattr(b, "click")]
        buttons[0].click()
        buttons[1].click()
        self.assertEqual((mini, closed), (["timer-1"], ["timer-1"]))

    def test_timer_counts_down_and_finishes(self):
        t = TimerContent()
        t.add(2)
        t.toggle()
        self.assertTrue(t.running)
        t._last -= 3.0                               # three seconds pass
        done = []
        t.finished.connect(lambda: done.append(True))
        t._step()
        self.assertFalse(t.running)
        self.assertEqual(t.remaining, 0.0)
        self.assertEqual(done, [True])
        self.assertEqual(t._display.text(), "00:00")
        t.add(3700)
        t._render()
        self.assertEqual(t._display.text(), "1:01:40")

    def test_news_and_downloads(self):
        n = NewsContent([{"title": "A", "source": "S", "url": "https://x"}])
        self.assertEqual(n.list.count(), 1)
        n.set_items([])
        self.assertIn("No headlines", n.list.item(0).text())
        with tempfile.TemporaryDirectory() as d:
            for i, name in enumerate(("old.txt", "new.pdf", ".hidden")):
                p = Path(d) / name
                p.write_text("x" * (i + 1))
                os.utime(p, (time.time() - 100 + i * 10,) * 2)
            self.assertEqual([p.name for p in recent_files(Path(d))], ["new.pdf", "old.txt"])
            dl = DownloadsContent(d)
            self.assertEqual(dl.list.count(), 2)
            self.assertIn("new.pdf", dl.list.item(0).text())

    def test_every_kind_has_content(self):
        from jarvis.core.window_manager import KINDS
        for kind in KINDS:
            w = make_content(kind, {})
            self.assertIsNotNone(w, kind)
        self.assertIsInstance(make_content("video"), WebMediaContent)
        with self.assertRaises(KeyError):
            make_content("spreadsheet")


class LazyChromiumTests(unittest.TestCase):
    def test_importing_glass_windows_does_not_load_chromium(self):
        code = ("import sys; import jarvis.ui.glass_window as g; "
                "print(any(m.startswith('PyQt6.QtWebEngine') for m in sys.modules))")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             cwd=str(Path(__file__).resolve().parents[2]),
                             env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, timeout=60)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


if __name__ == "__main__":
    unittest.main()
